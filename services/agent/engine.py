from copy import deepcopy
from datetime import datetime, timedelta
import secrets
import hmac
import httpx
from sqlalchemy import select
from contracts.models import ApprovalRequest, CandidatePlan, HandoffRecord, PlanProgress, RecipientClarification, TaskPlan, TaskStep
from pact.audit import record
from pact.common import DomainError, digest, now, stamp, uid
from pact.storage import ApprovalRow, Commitment, Guard, PlanRow
from services.banking import service as bank
from services.policy.engine import enforce_constraints, evaluate


def get_plan(session, user, plan_id):
    row = bank.owned(session, PlanRow, plan_id, user)
    return row, TaskPlan.model_validate(row.document)


def save(row, plan):
    plan.schema_version = "0.2"
    plan.progress = PlanProgress(completed=sum(s.status == "succeeded" for s in plan.steps), failed=sum(s.status == "failed" for s in plan.steps), pending_verification=sum(s.status == "pending_verification" for s in plan.steps), remaining=sum(s.status not in {"succeeded", "failed", "pending_verification"} for s in plan.steps))
    row.document = plan.model_dump(mode="json")


def expire_approvals(session, user, plan_id):
    for a in session.scalars(select(ApprovalRow).where(ApprovalRow.user_id == user)):
        if a.document["plan_id"] == plan_id and a.document["status"] in {"pending", "approved"}:
            a.document = {**a.document, "status": "expired"}
            a.challenge_hash, a.challenge_expires = None, None


def scope_hash(user, plan, step):
    return digest({"user_id": user, "plan_id": plan.plan_id, "version": plan.version, "step_id": step.step_id, "minimum_balance_cents": plan.minimum_balance_cents, "action": step.action.model_dump(mode="json")})


def resolve_target(session, user, plan, step):
    action = step.action.model_dump(mode="json")
    if action["tool"] not in {"transfer", "schedule_transfer"} or action.get("recipient_id"):
        return True
    matches = bank.recipient_matches(session, user, action)
    if step.clarification:
        if datetime.fromisoformat(step.clarification.expires_at) > now() and [o.model_dump() for o in step.clarification.options] == matches:
            step.status, plan.status = "waiting_clarification", "waiting_clarification"
            return False
        step.clarification = RecipientClarification(clarification_id=uid("clar"), query=action["recipient_query"], options=matches, expires_at=(now() + timedelta(minutes=10)).isoformat())
        step.status, plan.status = "waiting_clarification", "waiting_clarification"
        return False
    if len(matches) == 1:
        action.update(recipient_id=matches[0]["recipient_id"])
        action.pop("recipient_query", None)
        step.action = type(step.action).model_validate(action)
        step.clarification = None
        return True
    step.clarification = RecipientClarification(clarification_id=uid("clar"), query=action["recipient_query"], options=matches, expires_at=(now() + timedelta(minutes=10)).isoformat())
    step.status, plan.status = "waiting_clarification", "waiting_clarification"
    return False


def create_plan(session, user, candidate, planner="structured"):
    for step in candidate.steps:
        bank.validate_action(session, user, step.action.model_dump(mode="json"))
    plan = TaskPlan(plan_id=uid("plan"), title=candidate.title, planner=planner, minimum_balance_cents=candidate.minimum_balance_cents, created_at=stamp(), steps=[TaskStep(**s.model_dump()) for s in candidate.steps])
    for step in plan.steps:
        resolve_target(session, user, plan, step)
    row = PlanRow(id=plan.plan_id, user_id=user, document={}, history=[])
    save(row, plan)
    session.add(row)
    session.flush()
    record(session, user, "plan.created", plan.plan_id, {"planner": planner, "steps": len(plan.steps), "version": 1})
    return plan


def check_guard(session, user):
    guard = session.get(Guard, user)
    if guard and guard.blocked_until:
        if datetime.fromisoformat(guard.blocked_until) > now():
            raise DomainError("CIRCUIT_OPEN", "连续异常触发熔断，稍后再试；不会继续变账", 429, {"until": guard.blocked_until})
        guard.blocked_until, guard.failures = None, 0


def fail_guard(session, user):
    guard = session.get(Guard, user)
    if not guard:
        guard = Guard(user_id=user, failures=0)
        session.add(guard)
    guard.failures += 1
    if guard.failures >= 3:
        guard.blocked_until = (now() + timedelta(seconds=60)).isoformat()
        record(session, user, "circuit.opened", user, {"until": guard.blocked_until})


def assess(session, user, plan, step):
    action = step.action.model_dump(mode="json")
    bank.validate_action(session, user, action)
    if action.get("recipient_query"):
        raise DomainError("CLARIFICATION_REQUIRED", "尚未核实收款人，不能进行交易授权", 422)
    result = evaluate(action["tool"], action.get("amount_cents", 0), bank.spent_today(session, user))
    result["spent_today_cents"] = bank.spent_today(session, user)
    if "amount_cents" in action:
        result["constraints"] = bank.snapshot(session, user, action["account_id"], plan.minimum_balance_cents, action["amount_cents"], action.get("commitment_id"))
    return result


def approval_for(session, user, plan, step, decision):
    action = step.action.model_dump(mode="json")
    old = session.get(ApprovalRow, step.approval_id) if step.approval_id else None
    if old:
        doc = deepcopy(old.document)
        expired = datetime.fromisoformat(doc["expires_at"]) <= now()
        changed = doc["action_hash"] != digest(action) or doc["plan_version"] != plan.version or doc["level"] != decision["level"] or doc.get("scope_hash") != scope_hash(user, plan, step)
        if expired or changed:
            doc["status"] = "expired"
            old.document = doc
            old = None
        elif doc["status"] in {"pending", "approved", "rejected"}:
            return old
        else:
            old = None
    approval = ApprovalRequest(approval_id=uid("appr"), plan_id=plan.plan_id, plan_version=plan.version, step_id=step.step_id, action_hash=digest(action), level=decision["level"], status="pending", expires_at=(now() + timedelta(minutes=10)).isoformat(), reason=decision["reason"], action=action, scope_hash=scope_hash(user, plan, step))
    row = ApprovalRow(id=approval.approval_id, user_id=user, document=approval.model_dump(mode="json"))
    session.add(row)
    step.approval_id = row.id
    record(session, user, "approval.requested", row.id, {"level": approval.level, "plan_id": plan.plan_id, "version": plan.version})
    return row


def valid_pending_approval(session, user, approval_id):
    approval = bank.owned(session, ApprovalRow, approval_id, user)
    doc = approval.document
    _, plan = get_plan(session, user, doc["plan_id"])
    step = next((x for x in plan.steps if x.step_id == doc["step_id"]), None)
    if plan.status in {"handed_off", "pending_verification", "partially_completed", "failed", "paused"} or doc["status"] != "pending" or datetime.fromisoformat(doc["expires_at"]) <= now() or plan.version != doc["plan_version"] or not step or step.approval_id != approval.id or digest(step.action.model_dump(mode="json")) != doc["action_hash"] or doc.get("scope_hash") != scope_hash(user, plan, step):
        raise DomainError("STALE_APPROVAL", "审批已处理、过期或计划已变更")
    return approval


def challenge(session, user, approval_id):
    approval = valid_pending_approval(session, user, approval_id)
    if approval.document["level"] != "red":
        raise DomainError("CHALLENGE_NOT_REQUIRED", "该操作只需用户确认")
    code = f"{secrets.randbelow(1_000_000):06d}"
    approval.challenge_hash = digest({"code": code, "approval_id": approval.id})
    approval.challenge_expires = (now() + timedelta(minutes=2)).isoformat()
    record(session, user, "strong_verification.challenge", approval.id, {"simulation": True})
    return {"simulation": True, "demo_code": code, "expires_at": approval.challenge_expires, "message": "仅模拟强验证：演示码不构成真实多因素认证"}


def decide(session, user, approval_id, command):
    approval = valid_pending_approval(session, user, approval_id)
    doc = deepcopy(approval.document)
    if command.decision == "reject":
        doc["status"] = "rejected"
    else:
        if doc["level"] == "red":
            valid = approval.challenge_hash and approval.challenge_expires and datetime.fromisoformat(approval.challenge_expires) > now() and hmac.compare_digest(approval.challenge_hash, digest({"code": command.challenge_code, "approval_id": approval.id}))
            if not valid:
                approval.attempts += 1
                if approval.attempts >= 3:
                    doc["status"] = "rejected"
                    approval.document = doc
                record(session, user, "strong_verification.failed", approval.id, {"attempt": approval.attempts})
                return {"error": {"code": "STRONG_VERIFICATION_REQUIRED", "message": "模拟强验证代码错误、未申请或已过期", "details": {"remaining_attempts": max(0, 3 - approval.attempts)}}}
        doc["status"] = "approved"
    approval.document = doc
    approval.challenge_hash = None
    record(session, user, "approval." + doc["status"], approval.id)
    return doc


def execute_step(session, user, row, plan, step, command=None):
    action = step.action.model_dump(mode="json")
    key = bank.execution_key(plan, step)
    if command and (command.plan_version != plan.version or command.idempotency_key != key or command.action.model_dump(mode="json") != action):
        raise DomainError("REQUEST_BINDING_MISMATCH", "版本、幂等键或执行参数与已保存计划不一致")
    if plan.status == "handed_off":
        raise DomainError("HUMAN_TAKEOVER", "人工接管中，自动执行已冻结")
    cached = bank.owned(session, bank.ReceiptRow, step.receipt_id, user) if step.receipt_id else bank.find_receipt(session, user, key)
    if cached:
        return verify_step(session, user, plan, step, cached)
    if plan.status in {"failed", "partially_completed", "paused", "pending_verification"}:
        raise DomainError("PLAN_NOT_EXECUTABLE", "失败计划需重规划，暂停计划需显式恢复")
    if any(next(x for x in plan.steps if x.step_id == d).status != "succeeded" for d in step.depends_on):
        raise DomainError("DEPENDENCIES_NOT_READY", "前置步骤尚未成功")
    check_guard(session, user)
    if not resolve_target(session, user, plan, step):
        return None
    action = step.action.model_dump(mode="json")
    decision = assess(session, user, plan, step)
    step.risk_level = decision["level"]
    if decision.get("constraints"):
        enforce_constraints(decision["constraints"])
    approval = None
    if decision["level"] != "green":
        approval = approval_for(session, user, plan, step, decision)
        if approval.document["status"] == "rejected":
            raise DomainError("APPROVAL_REJECTED", "用户拒绝了该操作，需重规划")
        if approval.document["status"] != "approved":
            step.status, plan.status = "waiting_approval", "waiting_approval"
            save(row, plan)
            return None
    step.status, plan.status = "executing", "executing"
    # All monetary mutations, approval consumption and receipts share the write transaction.
    with session.begin_nested():
        receipt = bank.post_action(session, user, plan, step, key)
    if approval:
        approval.document = {**approval.document, "status": "consumed"}
    step.receipt_id = receipt.id
    record(session, user, "banking.executed", receipt.id, {"operation": action["tool"], "plan_id": plan.plan_id, "action_hash": digest(action)})
    # Query canonical persisted receipt and ledger; do not trust the tool's prose.
    save(row, plan)
    session.flush()
    return verify_step(session, user, plan, step, receipt)


def verify_step(session, user, plan, step, receipt):
    step.receipt_id = receipt.id
    try:
        result = bank.verify_receipt(session, user, receipt.id)
        if not result["verified"]:
            raise DomainError("RECEIPT_UNVERIFIED", "回执完整性或账务绑定未通过核验")
    except (TimeoutError, ConnectionError, httpx.TransportError, DomainError) as error:
        step.status, step.result = "pending_verification", None
        step.error = {"code": "RECEIPT_PENDING", "message": "交易结果待核验；只允许查询原交易或人工接管，不得重付", "details": {"cause": error.code if isinstance(error, DomainError) else type(error).__name__}}
        if plan.status != "handed_off":
            plan.status = "pending_verification"
        record(session, user, "receipt.pending", receipt.id, {"step_id": step.step_id})
        return None
    step.status, step.result, step.error = "succeeded", result, None
    return receipt


def refresh_status(plan):
    if plan.status == "handed_off":
        return
    if any(s.status == "pending_verification" for s in plan.steps):
        plan.status = "pending_verification"
    elif any(s.status == "failed" for s in plan.steps):
        plan.status = "partially_completed" if any(s.status == "succeeded" for s in plan.steps) else "failed"
    elif all(s.status == "succeeded" for s in plan.steps):
        plan.status = "succeeded"
    elif plan.status in {"executing", "pending_verification"}:
        plan.status = "planned"


def run(session, user, plan_id, resume=False, command=None):
    row, plan = get_plan(session, user, plan_id)
    if plan.status == "handed_off":
        raise DomainError("HUMAN_TAKEOVER", "人工接管中；先显式交还，不能通过恢复接口绕过")
    if plan.status == "pending_verification" or any(s.status == "pending_verification" for s in plan.steps):
        if command:
            step = next((s for s in plan.steps if s.step_id == command.step_id), None)
            if not step or command.plan_version != plan.version or command.idempotency_key != bank.execution_key(plan, step) or command.action.model_dump(mode="json") != step.action.model_dump(mode="json"):
                raise DomainError("REQUEST_BINDING_MISMATCH", "待核验请求参数不一致")
            return {"receipt": None, "plan": plan.model_dump(mode="json")}
        return plan
    if command:
        requested = next((s for s in plan.steps if s.step_id == command.step_id), None)
        if not requested:
            raise DomainError("NOT_FOUND", "步骤不存在", 404)
        if requested.receipt_id or bank.find_receipt(session, user, bank.execution_key(plan, requested)):
            receipt = execute_step(session, user, row, plan, requested, command)
            save(row, plan)
            refresh_status(plan)
            save(row, plan)
            return {"receipt": receipt.document if receipt else None, "plan": plan.model_dump(mode="json")}
    if plan.status == "succeeded":
        if command:
            step = next((s for s in plan.steps if s.step_id == command.step_id), None)
            if not step:
                raise DomainError("NOT_FOUND", "步骤不存在", 404)
            receipt = execute_step(session, user, row, plan, step, command)
            return {"receipt": receipt.document, "plan": plan.model_dump(mode="json")}
        return plan
    if plan.status in {"failed", "partially_completed"}:
        raise DomainError("REPLAN_REQUIRED", "计划已失败，请根据最新资金约束重规划")
    if plan.status == "paused" and not resume:
        return plan
    check_guard(session, user)
    if resume:
        plan.status = "planned"
    if command and not any(s.step_id == command.step_id for s in plan.steps):
        raise DomainError("NOT_FOUND", "步骤不存在", 404)
    for _ in range(12):
        done = {s.step_id for s in plan.steps if s.status == "succeeded"}
        step = next((s for s in plan.steps if s.status in {"planned", "waiting_approval", "waiting_clarification"} and set(s.depends_on) <= done and (not command or s.step_id == command.step_id)), None)
        if not step:
            if command:
                raise DomainError("DEPENDENCIES_NOT_READY", "请求的步骤尚不能执行")
            break
        try:
            result = execute_step(session, user, row, plan, step, command)
        except DomainError as error:
            step.status, step.error, plan.status = "failed", error.as_dict(), "failed"
            if error.code != "APPROVAL_REJECTED":
                fail_guard(session, user)
            record(session, user, "step.failed", plan.plan_id, {"step_id": step.step_id, "code": error.code})
            break
        if result is None or command:
            break
    refresh_status(plan)
    save(row, plan)
    if command:
        command_step = next(s for s in plan.steps if s.step_id == command.step_id)
        receipt = bank.find_receipt(session, user, bank.execution_key(plan, command_step)) if command_step.status == "succeeded" else None
        return {"receipt": receipt.document if receipt else None, "plan": plan.model_dump(mode="json")}
    return plan


def replan(session, user, plan_id, candidate, planner):
    row, old = get_plan(session, user, plan_id)
    if old.status == "handed_off" or any(s.status == "pending_verification" for s in old.steps):
        raise DomainError("RESOLUTION_REQUIRED", "先完成原交易核验或交还人工接管，不能重规划付款")
    if old.status == "succeeded":
        raise DomainError("PLAN_COMPLETE", "已完成计划不能重规划，请新建请求")
    for s in candidate.steps:
        bank.validate_action(session, user, s.action.model_dump(mode="json"))
    retained = [s for s in old.steps if s.status == "succeeded"]
    for step in retained:
        if not step.receipt_id or not bank.verify_receipt(session, user, step.receipt_id)["verified"]:
            raise DomainError("RECEIPT_UNVERIFIED", "已有完成步骤的回执异常，需人工检查")
    retained_by_hash = {digest(s.action.model_dump(mode="json")): s.step_id for s in retained}
    mapping = {s.step_id: retained_by_hash.get(digest(s.action.model_dump(mode="json")), f"v{old.version+1}_{s.step_id}") for s in candidate.steps}
    new = []
    for step in candidate.steps:
        if digest(step.action.model_dump(mode="json")) in retained_by_hash:
            continue
        deps = [mapping[d] for d in step.depends_on] or [s.step_id for s in retained]
        new.append(TaskStep(step_id=mapping[step.step_id], action=step.action, depends_on=list(dict.fromkeys(deps))))
    if not new:
        raise DomainError("NOTHING_TO_REPLAN", "新请求只包含已核验完成的动作")
    CandidatePlan(title=candidate.title, steps=[{"step_id": s.step_id, "depends_on": s.depends_on, "action": s.action} for s in retained + new])
    row.history = row.history + [old.model_dump(mode="json")]
    expire_approvals(session, user, plan_id)
    old.version += 1
    old.status, old.steps, old.title, old.planner = "planned", retained + new, candidate.title, planner
    old.minimum_balance_cents = max(old.minimum_balance_cents, candidate.minimum_balance_cents)
    for step in old.steps:
        if step.status != "succeeded":
            resolve_target(session, user, old, step)
    save(row, old)
    record(session, user, "plan.replanned", plan_id, {"version": old.version, "retained_receipts": [s.receipt_id for s in retained]})
    return old


def select_recipient(session, user, plan_id, command):
    row, plan = get_plan(session, user, plan_id)
    if plan.status != "waiting_clarification" or command.plan_version != plan.version:
        raise DomainError("STALE_CLARIFICATION", "计划版本或状态已变化")
    step = next((s for s in plan.steps if s.step_id == command.step_id), None)
    choice = step.clarification if step else None
    if not choice or choice.clarification_id != command.clarification_id or datetime.fromisoformat(choice.expires_at) <= now():
        raise DomainError("STALE_CLARIFICATION", "澄清请求已过期或不属于该步骤")
    current = bank.recipient_matches(session, user, step.action.model_dump(mode="json"))
    if command.recipient_id not in {o.recipient_id for o in choice.options} or command.recipient_id not in {o["recipient_id"] for o in current}:
        raise DomainError("RECIPIENT_SELECTION_INVALID", "只能选择当前用户澄清列表中的收款人", 403)
    previous = plan.model_dump(mode="json")
    action = step.action.model_dump(mode="json")
    action.pop("recipient_query", None)
    action["recipient_id"] = command.recipient_id
    step.action = type(step.action).model_validate(action)
    bank.validate_action(session, user, action)
    row.history = row.history + [previous]
    expire_approvals(session, user, plan_id)
    plan.version += 1
    plan.status = "planned"
    for item in plan.steps:
        if item.status != "succeeded":
            item.clarification, item.approval_id, item.status = None, None, "planned"
    save(row, plan)
    record(session, user, "recipient.selected", plan_id, {"step_id": step.step_id, "recipient_id": command.recipient_id, "version": plan.version})
    return plan


def reconcile_plan(session, user, plan_id):
    row, plan = get_plan(session, user, plan_id)
    for step in plan.steps:
        if step.status not in {"pending_verification", "succeeded"}:
            continue
        receipt = session.get(bank.ReceiptRow, step.receipt_id) if step.receipt_id else None
        if receipt and receipt.user_id == user:
            verify_step(session, user, plan, step, receipt)
        else:
            step.status, step.result = "pending_verification", None
            step.error = {"code": "RECEIPT_PENDING", "message": "原回执缺失，需人工检查，不能重付"}
        record(session, user, "receipt.rechecked", plan_id, {"step_id": step.step_id, "status": step.status})
    refresh_status(plan)
    save(row, plan)
    return plan


def handoff_plan(session, user, plan_id, command):
    row, plan = get_plan(session, user, plan_id)
    if command.plan_version != plan.version or plan.status in {"succeeded", "handed_off"}:
        raise DomainError("HANDOFF_NOT_ALLOWED", "版本已改变、计划已完成或已接管")
    plan.handoff = HandoffRecord(handoff_id=uid("handoff"), requested_by=user, reason=command.reason, created_at=stamp(), prior_status=plan.status)
    plan.status = "handed_off"
    expire_approvals(session, user, plan_id)
    save(row, plan)
    record(session, user, "handoff.requested", plan_id, plan.handoff.model_dump(mode="json"))
    return plan


def release_handoff(session, user, plan_id, command):
    row, plan = get_plan(session, user, plan_id)
    if plan.status != "handed_off" or not plan.handoff or command.plan_version != plan.version:
        raise DomainError("HANDOFF_NOT_ACTIVE", "没有匹配版本的人工接管")
    plan.handoff.status, plan.handoff.released_at, plan.handoff.resolution_note = "released", stamp(), command.note
    plan.status = "paused"
    refresh_status(plan)
    save(row, plan)
    record(session, user, "handoff.released", plan_id, plan.handoff.model_dump(mode="json"))
    return plan


def prepare_due(session, user):
    created = []
    rows = session.scalars(select(Commitment).where(Commitment.user_id == user, Commitment.kind == "scheduled_transfer", Commitment.status == "active", Commitment.due_at <= stamp())).all()
    for c in rows:
        if c.execution_plan_id:
            continue
        candidate = CandidatePlan(title=f"到期执行：{c.name}", minimum_balance_cents=c.minimum_balance_cents, steps=[{"step_id": "due_transfer", "action": {"tool": "transfer", "account_id": c.account_id, "recipient_id": c.recipient_id, "amount_cents": c.amount_cents, "commitment_id": c.id}}])
        plan = create_plan(session, user, candidate, "schedule")
        c.execution_plan_id = plan.plan_id
        run(session, user, plan.plan_id)
        created.append(plan.plan_id)
    return {"created_plan_ids": created, "message": "到期任务需要新确认/模拟强验证；未自动扣款"}
