from copy import deepcopy
from datetime import datetime, timedelta
import secrets
import hmac
from sqlalchemy import select
from contracts.models import ApprovalRequest, CandidatePlan, TaskPlan, TaskStep
from pact.audit import record
from pact.common import DomainError, digest, now, stamp, uid
from pact.storage import ApprovalRow, Commitment, Guard, PlanRow
from services.banking import service as bank
from services.policy.engine import evaluate


def get_plan(session, user, plan_id):
    row = bank.owned(session, PlanRow, plan_id, user)
    return row, TaskPlan.model_validate(row.document)


def save(row, plan):
    row.document = plan.model_dump(mode="json")


def create_plan(session, user, candidate, planner="structured"):
    for step in candidate.steps:
        bank.validate_action(session, user, step.action.model_dump(mode="json"))
    plan = TaskPlan(plan_id=uid("plan"), title=candidate.title, planner=planner, minimum_balance_cents=candidate.minimum_balance_cents, created_at=stamp(), steps=[TaskStep(**s.model_dump()) for s in candidate.steps])
    session.add(PlanRow(id=plan.plan_id, user_id=user, document=plan.model_dump(mode="json"), history=[]))
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
        changed = doc["action_hash"] != digest(action) or doc["plan_version"] != plan.version or doc["level"] != decision["level"]
        if expired or changed:
            doc["status"] = "expired"
            old.document = doc
            old = None
        elif doc["status"] in {"pending", "approved", "rejected"}:
            return old
        else:
            old = None
    approval = ApprovalRequest(approval_id=uid("appr"), plan_id=plan.plan_id, plan_version=plan.version, step_id=step.step_id, action_hash=digest(action), level=decision["level"], status="pending", expires_at=(now() + timedelta(minutes=10)).isoformat(), reason=decision["reason"], action=action)
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
    if doc["status"] != "pending" or datetime.fromisoformat(doc["expires_at"]) <= now() or plan.version != doc["plan_version"] or not step or step.approval_id != approval.id or digest(step.action.model_dump(mode="json")) != doc["action_hash"]:
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
    cached = bank.find_receipt(session, user, key)
    if cached:
        verified = bank.verify_receipt(session, user, cached.id)
        if not verified["verified"]:
            raise DomainError("RECEIPT_UNVERIFIED", "后端回执核验失败；请人工检查，不得盲目重付")
        step.receipt_id, step.result, step.status = cached.id, verified, "succeeded"
        return cached
    if plan.status in {"failed", "paused"}:
        raise DomainError("PLAN_NOT_EXECUTABLE", "失败计划需重规划，暂停计划需显式恢复")
    if any(next(x for x in plan.steps if x.step_id == d).status != "succeeded" for d in step.depends_on):
        raise DomainError("DEPENDENCIES_NOT_READY", "前置步骤尚未成功")
    check_guard(session, user)
    decision = assess(session, user, plan, step)
    step.risk_level = decision["level"]
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
    result = bank.verify_receipt(session, user, receipt.id)
    if not result["verified"]:
        raise DomainError("RECEIPT_UNVERIFIED", "交易结果尚未核验；不要盲目重付")
    step.status, step.result, step.error = "succeeded", result, None
    return receipt


def run(session, user, plan_id, resume=False, command=None):
    row, plan = get_plan(session, user, plan_id)
    if command:
        requested = next((s for s in plan.steps if s.step_id == command.step_id), None)
        if not requested:
            raise DomainError("NOT_FOUND", "步骤不存在", 404)
        if bank.find_receipt(session, user, bank.execution_key(plan, requested)):
            receipt = execute_step(session, user, row, plan, requested, command)
            save(row, plan)
            return {"receipt": receipt.document, "plan": plan.model_dump(mode="json")}
    if plan.status == "succeeded":
        if command:
            step = next((s for s in plan.steps if s.step_id == command.step_id), None)
            if not step:
                raise DomainError("NOT_FOUND", "步骤不存在", 404)
            receipt = execute_step(session, user, row, plan, step, command)
            return {"receipt": receipt.document, "plan": plan.model_dump(mode="json")}
        return plan
    if plan.status == "failed":
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
        step = next((s for s in plan.steps if s.status in {"planned", "waiting_approval"} and set(s.depends_on) <= done and (not command or s.step_id == command.step_id)), None)
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
    if all(s.status == "succeeded" for s in plan.steps):
        plan.status = "succeeded"
    elif plan.status == "executing":
        plan.status = "planned"
    save(row, plan)
    if command:
        receipt = bank.find_receipt(session, user, bank.execution_key(plan, next(s for s in plan.steps if s.step_id == command.step_id)))
        return {"receipt": receipt.document if receipt else None, "plan": plan.model_dump(mode="json")}
    return plan


def replan(session, user, plan_id, candidate, planner):
    row, old = get_plan(session, user, plan_id)
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
    for a in session.scalars(select(ApprovalRow).where(ApprovalRow.user_id == user)):
        if a.document["plan_id"] == plan_id and a.document["status"] in {"pending", "approved"}:
            a.document = {**a.document, "status": "expired"}
    old.version += 1
    old.status, old.steps, old.title, old.planner = "planned", retained + new, candidate.title, planner
    old.minimum_balance_cents = max(old.minimum_balance_cents, candidate.minimum_balance_cents)
    save(row, old)
    record(session, user, "plan.replanned", plan_id, {"version": old.version, "retained_receipts": [s.receipt_id for s in retained]})
    return old


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
