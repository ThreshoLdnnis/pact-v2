from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from contracts.models import ExecutionReceipt
from pact.common import DomainError, digest, now, stamp, uid
from pact.storage import Account, Commitment, Ledger, PlanRow, ReceiptRow, Recipient, Subscription
from services.policy.engine import constraint_snapshot, enforce_constraints, READ_TOOLS

SHANGHAI = ZoneInfo("Asia/Shanghai")


def owned(session, model, key, user):
    row = session.get(model, key)
    if row is None or row.user_id != user:
        raise DomainError("NOT_FOUND", "资源不存在或不属于当前用户", 404)
    return row


def account_view(row):
    return {"account_id": row.id, "name": row.name, "currency": "CNY", "balance_cents": row.balance_cents, "minimum_balance_cents": row.floor_cents}


def commitment_view(row):
    return {"commitment_id": row.id, "name": row.name, "account_id": row.account_id, "amount_cents": row.amount_cents, "due_at": row.due_at, "status": row.status, "kind": row.kind, "execution_plan_id": row.execution_plan_id}


def reserved(session, account_id, exclude=None):
    query = select(func.coalesce(func.sum(Commitment.amount_cents), 0)).where(Commitment.account_id == account_id, Commitment.status == "active")
    if exclude:
        query = query.where(Commitment.id != exclude)
    return session.scalar(query)


def spent_today(session, user):
    start = now().astimezone(SHANGHAI).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat()
    return -(session.scalar(select(func.coalesce(func.sum(Ledger.amount_cents), 0)).join(Account, Account.id == Ledger.account_id).where(Account.user_id == user, Ledger.category == "transfer", Ledger.amount_cents < 0, Ledger.created_at >= start)) or 0)


def snapshot(session, user, account_id, floor=0, amount=0, exclude=None):
    account = owned(session, Account, account_id, user)
    return constraint_snapshot(account.balance_cents, max(floor, account.floor_cents), reserved(session, account.id, exclude), amount)


def validate_action(session, user, action):
    owned(session, Account, action["account_id"], user)
    if action["tool"] in {"transfer", "schedule_transfer"}:
        if not action.get("recipient_id"):
            if action.get("commitment_id"):
                raise DomainError("COMMITMENT_MISMATCH", "定时承诺必须绑定已核实收款人", 422)
            return
        recipient = owned(session, Recipient, action["recipient_id"], user)
        if recipient.account_id == action["account_id"]:
            raise DomainError("SELF_TRANSFER", "不能向同一账户转账", 422)
    if action["tool"] == "cancel_subscription":
        sub = owned(session, Subscription, action["subscription_id"], user)
        if sub.account_id != action["account_id"]:
            raise DomainError("ACCOUNT_MISMATCH", "订阅不属于该账户", 422)
    if action.get("commitment_id"):
        c = owned(session, Commitment, action["commitment_id"], user)
        if c.kind != "scheduled_transfer" or c.account_id != action["account_id"] or c.recipient_id != action["recipient_id"] or c.amount_cents != action["amount_cents"]:
            raise DomainError("COMMITMENT_MISMATCH", "定时承诺与交易参数不一致", 422)


def recipient_view(row):
    return {"recipient_id": row.id, "name": row.name, "account_hint": "模拟账户 · " + row.account_id.removeprefix("acct-")}


def recipient_matches(session, user, action):
    owned(session, Account, action["account_id"], user)
    return [recipient_view(r) for r in session.scalars(select(Recipient).where(Recipient.user_id == user, Recipient.name == action["recipient_query"], Recipient.account_id != action["account_id"]).order_by(Recipient.id))]


def read_tool(session, user, action, *, subscription_authorized=False):
    account = owned(session, Account, action["account_id"], user)
    tool = action["tool"]
    if tool == "balance":
        return {**account_view(account), "constraints": snapshot(session, user, account.id)}
    if tool == "recipients":
        return {"items": [recipient_view(r) for r in session.scalars(select(Recipient).where(Recipient.user_id == user))]}
    if tool == "subscriptions":
        if not subscription_authorized:
            raise DomainError("APPROVAL_REQUIRED", "订阅查询需先创建查询计划并明确确认；直调接口不绕过黄色权限", 403)
        return {"items": [{"subscription_id": x.id, "name": x.name, "amount_cents": x.amount_cents, "active": x.active} for x in session.scalars(select(Subscription).where(Subscription.user_id == user, Subscription.account_id == account.id))]}
    if tool == "commitments":
        rows = session.scalars(select(Commitment).where(Commitment.user_id == user, Commitment.account_id == account.id)).all()
        return {"items": [commitment_view(x) for x in rows if x.kind != "subscription"], "subscription_reserved_cents": sum(x.amount_cents for x in rows if x.kind == "subscription" and x.status == "active"), "constraints": snapshot(session, user, account.id)}
    rows = session.scalars(select(Ledger).where(Ledger.account_id == account.id).order_by(Ledger.id.desc())).all()
    if tool == "transactions":
        return {"items": [{"transaction_id": x.transaction_id, "amount_cents": x.amount_cents, "category": x.category, "memo": x.memo, "created_at": x.created_at} for x in rows[:100]]}
    if tool == "analyze_bills":
        local = now().astimezone(SHANGHAI)
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0) if action.get("period", "month") == "month" else local - timedelta(days=30)
        start = start.astimezone(timezone.utc).isoformat()
        end = stamp()
        relevant = [r for r in rows if start <= r.created_at <= end]
        categories = {}
        for row in relevant:
            if row.amount_cents < 0 and row.category != "transfer":
                categories[row.category] = categories.get(row.category, 0) - row.amount_cents
        anomalies = [{"transaction_id": r.transaction_id, "reason": "大额支出≥3000元，仅提示待核查，不代表欺诈"} for r in relevant if r.amount_cents <= -300_000 and r.category != "transfer"]
        return {"period_start": start, "period_end": end, "timezone": "Asia/Shanghai", "income_cents": sum(r.amount_cents for r in relevant if r.amount_cents > 0 and r.category != "transfer"), "expense_cents": sum(categories.values()), "transfer_out_cents": -sum(r.amount_cents for r in relevant if r.amount_cents < 0 and r.category == "transfer"), "categories": categories, "transaction_count": len(relevant), "source": "banking_ledger", "transaction_ids": [r.transaction_id for r in relevant], "anomalies": anomalies}
    raise DomainError("TOOL_NOT_ALLOWED", "未知工具", 422)


def execution_key(plan, step):
    return f"{plan.plan_id}:v{plan.version}:{step.step_id}"


def subscription_snapshot(session, user, account_id, receipt_id):
    owned(session, Account, account_id, user)
    if not receipt_id:
        raise DomainError("APPROVAL_REQUIRED", "订阅查询需先创建查询计划并明确确认", 403)
    row = owned(session, ReceiptRow, receipt_id, user)
    plan = owned(session, PlanRow, row.plan_id, user)
    matches = [s for p in [plan.document] + plan.history if p["version"] == row.plan_version for s in p["steps"] if s["step_id"] == row.step_id and s["action"]["tool"] == "subscriptions" and s["action"]["account_id"] == account_id]
    from pact.storage import ApprovalRow
    confirmed = any(a.document["plan_id"] == row.plan_id and a.document["plan_version"] == row.plan_version and a.document["step_id"] == row.step_id and a.document["action_hash"] == row.document["action_hash"] and a.document["level"] == "yellow" and a.document["status"] == "consumed" for a in session.scalars(select(ApprovalRow).where(ApprovalRow.user_id == user)))
    if row.document["operation"] != "subscriptions" or not matches or not confirmed or not verify_receipt(session, user, receipt_id)["verified"]:
        raise DomainError("SUBSCRIPTION_GRANT_INVALID", "仅能读取本账户已获确认的订阅查询快照", 403)
    return {**row.document["data"], "source_receipt_id": row.id, "snapshot_at": row.document["created_at"]}


def find_receipt(session, user, key):
    return session.scalars(select(ReceiptRow).where(ReceiptRow.user_id == user, ReceiptRow.idempotency_key == key)).first()


def post_action(session, user, plan, step, key, *, fail_after_mutation=False):
    """Caller has rechecked approval; transaction lock covers policy, limits and posting."""
    action = step.action.model_dump(mode="json")
    old = find_receipt(session, user, key)
    if old:
        if old.document["action_hash"] != digest(action):
            raise DomainError("IDEMPOTENCY_CONFLICT", "幂等键已用于不同请求")
        return old
    validate_action(session, user, action)
    account = owned(session, Account, action["account_id"], user)
    tool, tx, status = action["tool"], None, "succeeded"
    if tool in READ_TOOLS:
        result = read_tool(session, user, action, subscription_authorized=True)
    elif tool == "cancel_subscription":
        sub = owned(session, Subscription, action["subscription_id"], user)
        already_inactive = not sub.active
        sub.active = False
        released = 0
        for c in session.scalars(select(Commitment).where(Commitment.subscription_id == sub.id, Commitment.status == "active", Commitment.due_at > stamp())):
            c.status = "cancelled"
            released += c.amount_cents
        result = {"subscription_id": sub.id, "name": sub.name, "active": False, "already_inactive": already_inactive, "released_next_commitment_cents": released}
    elif tool == "schedule_transfer":
        due = datetime.fromisoformat(action["due_at"])
        if due <= now():
            raise DomainError("INVALID_DUE_DATE", "定时转账必须是未来时间", 422)
        constraints = snapshot(session, user, account.id, plan.minimum_balance_cents, action["amount_cents"])
        enforce_constraints(constraints)
        c = Commitment(id=uid("com"), user_id=user, account_id=account.id, name="定时转账", amount_cents=action["amount_cents"], due_at=due.astimezone(timezone.utc).isoformat(), status="active", kind="scheduled_transfer", recipient_id=action["recipient_id"], minimum_balance_cents=plan.minimum_balance_cents)
        session.add(c)
        session.flush()
        result, status = {"commitment": commitment_view(c), "paid": False, "requires_fresh_approval_when_due": True}, "scheduled"
    elif tool == "transfer":
        commitment = None
        if action.get("commitment_id"):
            commitment = owned(session, Commitment, action["commitment_id"], user)
            if commitment.status != "active" or datetime.fromisoformat(commitment.due_at) > now():
                raise DomainError("SCHEDULE_NOT_DUE", "定时承诺未到期或已处理")
        constraints = snapshot(session, user, account.id, plan.minimum_balance_cents, action["amount_cents"], action.get("commitment_id"))
        enforce_constraints(constraints)
        recipient = owned(session, Recipient, action["recipient_id"], user)
        target = session.get(Account, recipient.account_id)
        tx = uid("tx")
        amount = action["amount_cents"]
        account.balance_cents -= amount
        target.balance_cents += amount
        when = stamp()
        session.add_all([Ledger(transaction_id=tx, account_id=account.id, amount_cents=-amount, category="transfer", memo=f"转给{recipient.name}", created_at=when), Ledger(transaction_id=tx, account_id=target.id, amount_cents=amount, category="transfer", memo="模拟转账入账", created_at=when)])
        if commitment:
            commitment.status = "fulfilled"
        result = {"amount_cents": amount, "recipient_id": recipient.id, "recipient_name": recipient.name, "balance_after_cents": account.balance_cents, "constraints_at_execution": constraints}
    else:
        raise DomainError("TOOL_NOT_ALLOWED", "工具不受支持", 422)
    if fail_after_mutation:
        session.flush()
        raise DomainError("INJECTED_ROLLBACK", "测试环境在变更后注入异常；本次事务应完整回滚")
    receipt = ExecutionReceipt(receipt_id=uid("rec"), plan_id=plan.plan_id, plan_version=plan.version, step_id=step.step_id, action_hash=digest(action), operation=tool, status=status, transaction_id=tx, data=result, created_at=stamp())
    doc = receipt.model_dump(mode="json")
    row = ReceiptRow(id=receipt.receipt_id, user_id=user, plan_id=plan.plan_id, plan_version=plan.version, step_id=step.step_id, idempotency_key=key, document=doc, document_hash=digest(doc))
    session.add(row)
    session.flush()
    return row


def verify_receipt(session, user, receipt_id):
    row = owned(session, ReceiptRow, receipt_id, user)
    doc = row.document
    valid = row.document_hash == digest(doc)
    plan = owned(session, PlanRow, row.plan_id, user)
    versions = [plan.document] + plan.history
    matches = [s for p in versions if p["version"] == row.plan_version for s in p["steps"] if s["step_id"] == doc["step_id"] and digest(s["action"]) == doc["action_hash"]]
    valid = valid and bool(matches) and doc["operation"] == matches[0]["action"]["tool"] and doc["receipt_id"] == row.id and doc["plan_id"] == row.plan_id and doc["plan_version"] == row.plan_version
    if doc["operation"] == "transfer" and matches and matches[0]["action"]["tool"] == "transfer":
        entries = session.scalars(select(Ledger).where(Ledger.transaction_id == doc["transaction_id"])).all()
        valid = valid and len(entries) == 2 and sum(e.amount_cents for e in entries) == 0
        if matches:
            action = matches[0]["action"]
            valid = valid and doc["data"].get("amount_cents") == action["amount_cents"] and doc["data"].get("recipient_id") == action["recipient_id"]
            recipient = session.get(Recipient, action["recipient_id"])
            valid = valid and recipient is not None and any(e.account_id == action["account_id"] and e.amount_cents == -action["amount_cents"] for e in entries) and any(e.account_id == recipient.account_id and e.amount_cents == action["amount_cents"] for e in entries)
    if doc["operation"] == "cancel_subscription" and matches and matches[0]["action"]["tool"] == "cancel_subscription":
        sub = session.get(Subscription, matches[0]["action"]["subscription_id"])
        valid = valid and sub is not None and sub.user_id == user and not sub.active and doc["data"].get("active") is False
    return {"verified": bool(valid), "receipt_id": row.id, "source": "banking_backend", "checked_at": stamp(), "receipt": doc}


def seed(session):
    if session.get(Account, "acct-alice"):
        for key, target in [("rcp-wang-a", "acct-bob"), ("rcp-wang-b", "acct-clearing")]:
            if not session.get(Recipient, key):
                session.add(Recipient(id=key, user_id="alice", name="王五", account_id=target))
        return
    alice = Account(id="acct-alice", user_id="alice", name="日常账户 · Alice", opening_cents=1_000_000, balance_cents=1_000_000, floor_cents=100_000)
    bob = Account(id="acct-bob", user_id="bob", name="日常账户 · Bob", opening_cents=500_000, balance_cents=500_000, floor_cents=100_000)
    clearing = Account(id="acct-clearing", user_id="sandbox", name="沙箱清算账户", opening_cents=5_000_000, balance_cents=5_000_000, floor_cents=0)
    session.add_all([alice, bob, clearing])
    session.flush()
    session.add_all([Recipient(id="rcp-zhang", user_id="alice", name="张三", account_id=bob.id), Recipient(id="rcp-li", user_id="alice", name="李四", account_id=clearing.id), Recipient(id="rcp-alice", user_id="bob", name="Alice", account_id=alice.id), Recipient(id="rcp-wang-a", user_id="alice", name="王五", account_id=bob.id), Recipient(id="rcp-wang-b", user_id="alice", name="王五", account_id=clearing.id)])
    session.add_all([Subscription(id="sub-video", user_id="alice", account_id=alice.id, name="视频会员", amount_cents=9800), Subscription(id="sub-music", user_id="alice", account_id=alice.id, name="音乐会员", amount_cents=1800)])
    session.flush()
    for key, name, amount, sub, days in [("com-rent", "下期房租", 200000, None, 3), ("com-video", "视频会员下次扣款", 9800, "sub-video", 7), ("com-music", "音乐会员下次扣款", 1800, "sub-music", 9)]:
        session.add(Commitment(id=key, user_id="alice", account_id=alice.id, name=name, amount_cents=amount, due_at=(now() + timedelta(days=days)).isoformat(), subscription_id=sub, kind="subscription" if sub else "bill"))
    for i, (amount, category, memo) in enumerate([(-200000, "住房", "模拟房租"), (-35000, "餐饮", "模拟日常餐饮"), (-9800, "订阅", "视频会员模拟扣款"), (-1800, "订阅", "音乐会员模拟扣款"), (800000, "工资", "模拟工资")]):
        when = (now() - timedelta(days=5-i)).isoformat()
        alice.balance_cents += amount
        clearing.balance_cents -= amount
        session.add_all([Ledger(transaction_id=f"seed-{i}", account_id=alice.id, amount_cents=amount, category=category, memo=memo, created_at=when), Ledger(transaction_id=f"seed-{i}", account_id=clearing.id, amount_cents=-amount, category=category, memo="模拟对手账", created_at=when)])


def withdraw_schedule(session, user, receipt_id):
    """Withdraw an unexecuted registration; never reverse posted funds."""
    row = owned(session, ReceiptRow, receipt_id, user)
    if row.document["operation"] != "schedule_transfer" or not verify_receipt(session, user, receipt_id)["verified"]:
        raise DomainError("SCHEDULE_RECEIPT_INVALID", "登记回执未通过核验")
    commitment_id = row.document["data"]["commitment"]["commitment_id"]
    commitment = owned(session, Commitment, commitment_id, user)
    posted = session.scalars(select(ReceiptRow).where(ReceiptRow.user_id == user, ReceiptRow.plan_id == commitment.execution_plan_id)).all() if commitment.execution_plan_id else []
    if commitment.status == "fulfilled" or any(r.document["operation"] == "transfer" for r in posted):
        return {"withdrawn": False, "commitment_id": commitment_id, "execution_plan_id": commitment.execution_plan_id, "reason": "付款已经发生或需要核验，不能撤回登记冒充撤销付款"}
    commitment.status = "cancelled"
    return {"withdrawn": True, "commitment_id": commitment_id, "execution_plan_id": commitment.execution_plan_id, "reason": "仅撤销尚未执行的定时安排，原登记回执保留"}
