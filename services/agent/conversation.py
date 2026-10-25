"""Bounded contextual interpretation with persisted, version-bound clarification.

Understanding edits/ellipsis is separate from executing bank tools. Context is
owned task state, never retrieved text or model confidence. Unknown language asks.
"""
from copy import deepcopy
from datetime import datetime, timedelta
import re
from sqlalchemy import select
from contracts.models import CandidatePlan, ConversationResponse, InterruptInput, TaskPlan
from pact.audit import record
from pact.common import DomainError, digest, now, stamp, uid
from pact.storage import ClarificationRow, ConversationRow, PlanRow, Subscription, TurnRow
from services.agent import coordination, engine, planner, templates
from services.banking import service as bank

EDIT = re.compile(r"(?:(?:把)?(?:那个|这笔|刚才那笔|转账金额|最低留存|保留金额))?\s*改成\s*(\d+(?:\.\d+)?)\s*(?:元)?(?:吧)?")
KEEP = re.compile(r"(?:算了[，,、\s]*)?(?:那个|视频会员|音乐会员)?(?:先)?(?:留着|保留)(?:吧)?|(?:刚才(?:那个)?)?别取消了|保留(?:视频会员|音乐会员)")
PAUSE = {"先停一下", "暂停", "暂停一下", "先暂停", "暂停这个任务"}
STOP = {"整个任务都不要做了", "取消整个任务", "停止整个任务", "停止这条任务"}
RESUME = {"继续", "继续执行", "继续刚才的任务", "恢复任务"}
SAVINGS = {"帮我省点钱", "帮我节省开支", "帮我减少支出"}


def text(message):
    return message.strip().rstrip("。！？!?").strip()


def contextual(message):
    value = text(message)
    return bool(EDIT.fullmatch(value) or re.fullmatch(r"\d+(?:\.\d+)?(?:元)?", value) or KEEP.fullmatch(value) or value in PAUSE | STOP | RESUME | SAVINGS or re.search(r"那个|改成|留着|别取消|省点钱|一样|给他|给她", value))


def prior(session, user, command):
    row = session.scalars(select(TurnRow).where(TurnRow.user_id == user, TurnRow.request_id == command.request_id)).first()
    if row:
        if row.input_hash != digest(command.model_dump(mode="json")):
            raise DomainError("MESSAGE_ID_CONFLICT", "同一请求编号不能用于不同消息或上下文")
        return ConversationResponse.model_validate(row.response)
    return None


def context_row(session, user, command):
    if command.conversation_id:
        return bank.owned(session, ConversationRow, command.conversation_id, user)
    row = ConversationRow(id=uid("conversation"), user_id=user, document={"plan_ids": []})
    session.add(row)
    session.flush()
    return row


def linked_plans(session, user, conversation, command):
    if command.focus_plan_id:
        row, plan = engine.get_plan(session, user, command.focus_plan_id)
        if command.focus_plan_version is not None and command.focus_plan_version != plan.version:
            raise DomainError("CONTEXT_VERSION_CHANGED", "选中的任务已发生变化，请刷新后重新表达")
        if command.focus_step_id and not any(s.step_id == command.focus_step_id for s in plan.steps):
            raise DomainError("CONTEXT_TARGET_INVALID", "选中的步骤不存在", 404)
        return [(row, plan)]
    result = []
    for pid in conversation.document.get("plan_ids", []):
        row = session.get(PlanRow, pid)
        if row and row.user_id == user:
            result.append((row, TaskPlan.model_validate(row.document)))
    active = [(r, p) for r, p in result if p.status not in {"succeeded", "failed", "partially_completed", "cancelled"}]
    return active or result


def respond(session, user, conversation, command, outcome, message, plan=None, clarification=None, recommendations=None):
    turn = uid("turn")
    result = ConversationResponse(conversation_id=conversation.id, turn_id=turn, outcome=outcome, message=message, plan=plan, clarification=clarification, recommendations=recommendations or [])
    state = deepcopy(conversation.document)
    if plan and plan.plan_id not in state.get("plan_ids", []):
        state["plan_ids"] = (state.get("plan_ids", []) + [plan.plan_id])[-30:]
    state["last_turn_id"] = turn
    conversation.document = state
    session.add(TurnRow(id=turn, user_id=user, conversation_id=conversation.id, request_id=command.request_id, input_hash=digest(command.model_dump(mode="json")), response=result.model_dump(mode="json")))
    record(session, user, "conversation." + outcome, turn, {"conversation_id": conversation.id, "plan_id": plan.plan_id if plan else None})
    return result


def describe(session, user, plan, step):
    action = step.action
    name = action.tool
    if action.tool in {"transfer", "schedule_transfer"}:
        if action.recipient_id:
            name = bank.owned(session, bank.Recipient, action.recipient_id, user).name
        else:
            name = action.recipient_query
        name = f"给{name} {action.amount_cents / 100:g}元"
    return f"{name} · {plan.title[:35]}"


def ask(session, user, conversation, question, options, targets):
    versions = {}
    for _, plan in targets:
        if plan.plan_id in versions:
            continue
        versions[plan.plan_id] = plan.version
        if plan.status not in {"succeeded", "failed", "partially_completed", "pending_verification", "handed_off", "cancelled"}:
            engine.pause_plan(session, user, plan.plan_id)
    cid = uid("question")
    document = {"clarification_id": cid, "status": "pending", "question": question, "versions": versions, "expires_at": (now() + timedelta(minutes=10)).isoformat(), "options": [{"option_id": f"choice_{i}", **option} for i, option in enumerate(options)]}
    row = ClarificationRow(id=cid, user_id=user, conversation_id=conversation.id, document=document)
    session.add(row)
    return document


def intent_fingerprint(session, user, candidate):
    expanded, _ = templates.compile_candidate(candidate)
    ids = {s.step_id: i for i, s in enumerate(expanded.steps)}
    actions = []
    for step in expanded.steps:
        action = step.action.model_dump(mode="json")
        if action.get("recipient_query"):
            matches = bank.recipient_matches(session, user, action)
            if len(matches) == 1:
                action.pop("recipient_query")
                action["recipient_id"] = matches[0]["recipient_id"]
        actions.append({"action": action, "deps": sorted(ids[d] for d in step.depends_on)})
    return digest({"floor": expanded.minimum_balance_cents, "steps": actions})


def apply_option(session, user, option):
    operation = option["operation"]
    pid = option.get("plan_id")
    if operation == "amend":
        _, original = engine.get_plan(session, user, pid)
        target = next((s for s in original.steps if s.step_id == option.get("step_id")), None)
        if original.status in {"succeeded", "pending_verification", "handed_off"} or (target and target.receipt_id):
            return "informational", "原动作已完成、待核验或人工接管中，不能直接改写金额，也不会自动退款。请检查原回执后明确新安排。", original
        plan = engine.amend(session, user, pid, option.get("step_id"), option["field"], option["value"])
        return "amended", "已关联原任务并生成新版本，旧授权失效；已完成动作保留。", engine.run(session, user, plan.plan_id)
    if operation in {"pause", "resume", "stop"}:
        _, plan = engine.get_plan(session, user, pid)
        if operation == "pause":
            return "interrupted", "任务已暂停，尚未撤销已发生动作。", engine.pause_plan(session, user, pid)
        if operation == "resume":
            return "planned", "按当前状态恢复检查，原授权不会自动继承。", engine.run(session, user, pid, resume=True)
        updated = engine.interrupt(session, user, pid, InterruptInput(plan_version=plan.version, reason="用户明确停止整个任务"))
        return "interrupted", updated.interruption.message, updated
    if operation == "keep":
        coordination.keep_intent(session, user, option["account_id"], option["subscription_id"])
        if not pid:
            return "informational", "已记录保留该订阅的意图；这不是重新开通或恢复协议，未改变银行业务状态。", None
        _, plan = engine.get_plan(session, user, pid)
        step = next(s for s in plan.steps if s.step_id == option["step_id"])
        if step.receipt_id:
            return "informational", "该取消动作已经发生或待核验，不能假装恢复；保留意图已记录，恢复代扣需另外处理。", plan
        updated = engine.interrupt(session, user, pid, InterruptInput(plan_version=plan.version, step_id=step.step_id, reason="用户明确保留会员，停止取消"))
        return "interrupted", "已停止尚未执行的取消；依赖它的后续动作暂停，需明确新的安排。未恢复任何已取消协议。", updated
    if operation == "reuse":
        _, plan = engine.get_plan(session, user, pid)
        return "reused", "沿用原任务和原回执，没有新建第二笔付款。若已暂停，可显式恢复。", plan
    if operation == "new":
        candidate = CandidatePlan.model_validate(option["candidate"])
        plan = engine.create_plan(session, user, candidate, option.get("planner", "structured"))
        return "planned", "按你的选择创建一份新任务，仍需独立授权。", engine.run(session, user, plan.plan_id)
    raise DomainError("CLARIFICATION_INVALID", "未知澄清选项", 422)


def handle(session, user, command, prepared=None, preparation_error=None):
    if planner.INJECTION.search(command.message):
        raise DomainError("UNTRUSTED_INSTRUCTION", "检测到覆盖执行规则的内容，未执行任何操作", 422)
    cached = prior(session, user, command)
    if cached:
        return cached
    conversation = context_row(session, user, command)
    for question in session.scalars(select(ClarificationRow).where(ClarificationRow.user_id == user, ClarificationRow.conversation_id == conversation.id)):
        if question.document["status"] == "pending":
            question.document = {**question.document, "status": "superseded"}
    plans = linked_plans(session, user, conversation, command)
    value = text(command.message)
    match = EDIT.fullmatch(value)
    if not match and re.fullmatch(r"\d+(?:\.\d+)?(?:元)?", value):
        match = EDIT.fullmatch("那个改成" + value)
    if match:
        amount = planner.cents(match.group(1))
        if amount > 100_000_000:
            raise DomainError("CLARIFICATION_REQUIRED", "金额超出本沙箱范围", 422)
        options = []
        field = command.focus_field or ("minimum_balance_cents" if "留存" in value or "保留金额" in value else "amount_cents" if "转账金额" in value or "这笔" in value or "那笔" in value else None)
        for _, plan in plans:
            for step in plan.steps:
                if step.action.tool in {"transfer", "schedule_transfer"} and (not command.focus_step_id or command.focus_step_id == step.step_id) and field != "minimum_balance_cents":
                    options.append({"label": describe(session, user, plan, step) + "：修改转账金额", "operation": "amend", "plan_id": plan.plan_id, "step_id": step.step_id, "field": "amount_cents", "value": amount})
            if (plan.minimum_balance_cents > 0 or field == "minimum_balance_cents") and field != "amount_cents":
                options.append({"label": plan.title[:35] + "：修改最低留存", "operation": "amend", "plan_id": plan.plan_id, "field": "minimum_balance_cents", "value": amount})
        if len(options) == 1:
            outcome, message, plan = apply_option(session, user, options[0])
            return respond(session, user, conversation, command, outcome, message, plan)
        question = "请选要修改的任务和字段。" if options else "当前没有能唯一关联的任务，请明确收款人、金额或选中已有计划。"
        clarification = ask(session, user, conversation, question, options, plans)
        return respond(session, user, conversation, command, "clarification", question, clarification=clarification)
    if KEEP.fullmatch(value):
        options = []
        named = "视频会员" if "视频会员" in value else "音乐会员" if "音乐会员" in value else None
        for _, plan in plans:
            for step in plan.steps:
                if step.action.tool != "cancel_subscription":
                    continue
                sub = bank.owned(session, Subscription, step.action.subscription_id, user)
                if named and sub.name != named:
                    continue
                options.append({"label": "保留" + sub.name + " · " + plan.title[:30], "operation": "keep", "plan_id": plan.plan_id, "step_id": step.step_id, "account_id": step.action.account_id, "subscription_id": sub.id})
        if not options and named:
            for sub in session.scalars(select(Subscription).where(Subscription.user_id == user, Subscription.name == named)):
                options.append({"label": "记录保留" + named + "的意图", "operation": "keep", "account_id": sub.account_id, "subscription_id": sub.id})
        if len(options) == 1:
            outcome, message, plan = apply_option(session, user, options[0])
            return respond(session, user, conversation, command, outcome, message, plan)
        question = "你想保留哪一项？请选择具体会员和任务。"
        clarification = ask(session, user, conversation, question, options, plans)
        return respond(session, user, conversation, command, "clarification", question, clarification=clarification)
    if value in PAUSE | STOP | RESUME:
        operation = "pause" if value in PAUSE else "stop" if value in STOP else "resume"
        options = [{"label": p.title, "operation": operation, "plan_id": p.plan_id} for _, p in plans]
        if len(options) == 1:
            outcome, message, plan = apply_option(session, user, options[0])
            return respond(session, user, conversation, command, outcome, message, plan)
        question = "请选择要暂停、停止或恢复的任务。"
        clarification = ask(session, user, conversation, question, options, plans)
        return respond(session, user, conversation, command, "clarification", question, clarification=clarification)
    if value in SAVINGS:
        accounts = session.scalars(select(bank.Account).where(bank.Account.user_id == user)).all()
        if len(accounts) != 1:
            clarification = ask(session, user, conversation, "请先明确要分析的账户。", [], [])
            return respond(session, user, conversation, command, "clarification", clarification["question"], clarification=clarification)
        candidate = CandidatePlan(title="节省开支：先分析本月账单", steps=[{"step_id": "bills", "action": {"tool": "analyze_bills", "account_id": accounts[0].id}}])
        plan = engine.create_plan(session, user, candidate, "rules")
        plan = engine.run(session, user, plan.plan_id)
        recommendations = ["先核对本月消费分类和大额提示；金额高不代表不需要。", "如需筛选会员，可另行查询订阅协议并选择具体调整项。", "保留已有房租等资金承诺；不会自行取消会员、转账或购买理财。"]
        return respond(session, user, conversation, command, "planned", "按当前唯一账户、本月范围分析账单，先给建议，不自动执行节省措施。", plan, recommendations=recommendations)
    if contextual(value) or not prepared:
        question = "请明确对象、金额、时间或与旧任务的关系；当前表达不能唯一理解，尚未新增执行动作。"
        if preparation_error and preparation_error.code not in {"CLARIFICATION_REQUIRED", "UNSUPPORTED_OPERATION"}:
            raise preparation_error
        clarification = ask(session, user, conversation, question, [], plans)
        return respond(session, user, conversation, command, "clarification", question, clarification=clarification)
    candidate, source = prepared
    if any(s.action.tool in {"transfer", "schedule_transfer", "cancel_subscription"} for s in candidate.steps) and not re.match(r"再|另外|另给|又给", value):
        fingerprint = intent_fingerprint(session, user, candidate)
        duplicates = []
        for row, p in plans:
            old = CandidatePlan(title=p.title, minimum_balance_cents=p.minimum_balance_cents, steps=[{"step_id": s.step_id, "depends_on": s.depends_on, "action": s.action} for s in p.steps])
            if intent_fingerprint(session, user, old) == fingerprint:
                duplicates.append((row, p))
        if duplicates:
            options = [{"label": "沿用原任务，不新增付款 · " + p.title[:30], "operation": "reuse", "plan_id": p.plan_id} for _, p in duplicates]
            options.append({"label": "明确新增一份任务（另行授权）", "operation": "new", "candidate": candidate.model_dump(mode="json"), "planner": source})
            question = "这条请求与已有任务相同：是沿用原任务，还是确实新增一次？"
            clarification = ask(session, user, conversation, question, options, duplicates)
            return respond(session, user, conversation, command, "clarification", question, clarification=clarification)
    plan = engine.create_plan(session, user, candidate, source)
    plan = engine.run(session, user, plan.plan_id)
    return respond(session, user, conversation, command, "planned", "已生成并检查候选任务；需确认的动作等待你的决定。", plan)


def resolve(session, user, clarification_id, command):
    row = bank.owned(session, ClarificationRow, clarification_id, user)
    doc = deepcopy(row.document)
    if doc["status"] == "resolved":
        if doc.get("selected_option_id") == command.option_id:
            return ConversationResponse.model_validate(doc["response"])
        raise DomainError("STALE_CLARIFICATION", "澄清已处理，不能换选项重放")
    if doc["status"] != "pending" or datetime.fromisoformat(doc["expires_at"]) <= now():
        raise DomainError("STALE_CLARIFICATION", "澄清已过期，请重新表达")
    for pid, version in doc["versions"].items():
        _, plan = engine.get_plan(session, user, pid)
        if plan.version != version:
            raise DomainError("STALE_CLARIFICATION", "关联任务版本已变，请刷新后重新表达")
    option = next((o for o in doc["options"] if o["option_id"] == command.option_id), None)
    if not option:
        raise DomainError("CLARIFICATION_CHOICE_INVALID", "只能选择此澄清列出的选项", 422)
    outcome, message, plan = apply_option(session, user, option)
    result = ConversationResponse(conversation_id=row.conversation_id, turn_id=uid("clarified"), outcome=outcome, message=message, plan=plan)
    doc.update(status="resolved", selected_option_id=command.option_id, response=result.model_dump(mode="json"))
    row.document = doc
    conversation = bank.owned(session, ConversationRow, row.conversation_id, user)
    if plan and plan.plan_id not in conversation.document.get("plan_ids", []):
        conversation.document = {**conversation.document, "plan_ids": (conversation.document.get("plan_ids", []) + [plan.plan_id])[-30:]}
    record(session, user, "conversation.clarified", row.id, {"option_id": command.option_id, "plan_id": plan.plan_id if plan else None})
    return result
