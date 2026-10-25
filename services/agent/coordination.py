"""Persisted business conflicts; no implicit FIFO and no authorization authority."""
from copy import deepcopy
from datetime import datetime, timedelta
from sqlalchemy import select
from contracts.models import TaskPlan
from pact.audit import record
from pact.common import DomainError, now, stamp, uid
from pact.storage import ApprovalRow, ConflictRow, PlanRow, PreferenceRow
from services.banking import service as bank

TERMINAL = {"succeeded", "failed", "partially_completed", "cancelled", "handed_off", "paused"}
GREEN = {"balance", "transactions", "analyze_bills", "commitments", "recipients"}


def invalidate(session, user, plan_id):
    for row in session.scalars(select(ApprovalRow).where(ApprovalRow.user_id == user)):
        if row.document["plan_id"] == plan_id and row.document["status"] in {"pending", "approved"}:
            row.document = {**row.document, "status": "expired"}
            row.challenge_hash, row.challenge_expires = None, None


def close_for_plan(session, user, plan_id):
    """An edited/stopped participant invalidates the whole earlier choice."""
    for conflict in session.scalars(select(ConflictRow).where(ConflictRow.user_id == user)):
        doc = deepcopy(conflict.document)
        if doc["status"] != "open" or plan_id not in doc["versions"]:
            continue
        doc["status"], doc["stale_at"] = "stale", stamp()
        conflict.document = doc
        for pid in doc["versions"]:
            row = session.get(PlanRow, pid)
            if not row or row.user_id != user:
                continue
            updated = deepcopy(row.document)
            updated["conflict_ids"] = [x for x in updated.get("conflict_ids", []) if x != conflict.id]
            if updated["status"] == "waiting_conflict":
                updated["status"], updated["activated_until"] = "paused", None
            updated["ready_step_ids"] = []
            row.document = updated
            invalidate(session, user, pid)
        record(session, user, "conflict.stale", conflict.id, {"changed_plan_id": plan_id})


def keep_intent(session, user, account_id, subscription_id):
    bank.validate_action(session, user, {"tool": "cancel_subscription", "account_id": account_id, "subscription_id": subscription_id})
    old = session.scalars(select(PreferenceRow).where(PreferenceRow.user_id == user, PreferenceRow.subscription_id == subscription_id)).first()
    if old:
        old.active = True
    else:
        session.add(PreferenceRow(id=uid("pref"), user_id=user, account_id=account_id, subscription_id=subscription_id))
    record(session, user, "intent.keep_subscription", subscription_id, {"account_id": account_id})


def pending_money(plan):
    return [s for s in plan.steps if s.status not in {"succeeded", "failed", "cancelled"} and s.action.tool in {"transfer", "schedule_transfer"}]


def check(session, user, row, plan):
    # Held choices always require an explicit user decision, including after restart.
    open_ids = [cid for cid in plan.conflict_ids if (c := session.get(ConflictRow, cid)) and c.user_id == user and c.document["status"] == "open"]
    plan.conflict_ids = open_ids
    if open_ids:
        plan.status = "waiting_conflict"
        return True
    plan.activated_until = (now() + timedelta(minutes=10)).isoformat()
    participants = {plan.plan_id: (row, plan)}
    for other in session.scalars(select(PlanRow).where(PlanRow.user_id == user)):
        if other.id == plan.plan_id:
            continue
        p = TaskPlan.model_validate(other.document)
        if p.status not in TERMINAL and p.activated_until and datetime.fromisoformat(p.activated_until) > now():
            participants[p.plan_id] = (other, p)
    affected, reasons, preference_ids = set(), [], []
    accounts = {s.action.account_id for s in pending_money(plan)}
    for account_id in accounts:
        claims = [(pid, p, s) for pid, (_, p) in participants.items() for s in pending_money(p) if s.action.account_id == account_id]
        ids = {pid for pid, _, _ in claims}
        if len(ids) < 2:
            continue
        floor = max(p.minimum_balance_cents for _, p, _ in claims)
        own_commitments = {getattr(s.action, "commitment_id", None) for _, _, s in claims} - {None}
        available = bank.snapshot(session, user, account_id, floor)["spendable_cents"]
        # Due-transfer reservations are already in the commitment total: count once.
        available += sum(bank.owned(session, bank.Commitment, cid, user).amount_cents for cid in own_commitments)
        requested = sum(s.action.amount_cents for _, _, s in claims)
        if requested > available:
            affected.update(ids)
            reasons.append({"kind": "funds", "account_id": account_id, "available_cents": available, "requested_cents": requested})
    for step in plan.steps:
        if step.status in {"succeeded", "failed", "cancelled"} or step.action.tool != "cancel_subscription":
            continue
        preferences = session.scalars(select(PreferenceRow).where(PreferenceRow.user_id == user, PreferenceRow.subscription_id == step.action.subscription_id, PreferenceRow.active.is_(True))).all()
        if preferences:
            affected.add(plan.plan_id)
            preference_ids += [p.id for p in preferences]
            reasons.append({"kind": "subscription_intent", "subscription_id": step.action.subscription_id, "message": "已有明确保留意图；取消与保留需要用户选择"})
    if not affected:
        return False
    conflict_id = uid("conflict")
    doc = {"conflict_id": conflict_id, "status": "open", "created_at": stamp(), "versions": {pid: participants[pid][1].version for pid in affected}, "plans": [{"plan_id": pid, "title": participants[pid][1].title} for pid in sorted(affected)], "reasons": reasons, "preference_ids": preference_ids, "message": "相关请求不能同时满足，请选择；不会按先来后到执行"}
    session.add(ConflictRow(id=conflict_id, user_id=user, document=doc))
    for pid in affected:
        target_row, target = participants[pid]
        target.conflict_ids = list(dict.fromkeys(target.conflict_ids + [conflict_id]))
        target.status = "waiting_conflict"
        invalidate(session, user, pid)
        target_row.document = target.model_dump(mode="json")
    record(session, user, "conflict.detected", conflict_id, {"plan_ids": sorted(affected), "reasons": reasons})
    return True


def decide(session, user, conflict_id, command):
    conflict = bank.owned(session, ConflictRow, conflict_id, user)
    doc = deepcopy(conflict.document)
    if doc["status"] == "resolved" and doc.get("decision") == command.model_dump():
        plans = [TaskPlan.model_validate(bank.owned(session, PlanRow, pid, user).document) for pid in doc["versions"]]
        return {"conflict": doc, "plans": plans, "message": "原选择已保存，本次重试未执行任何业务"}
    if doc["status"] != "open":
        raise DomainError("STALE_CONFLICT", "该选择已处理或关联任务已变化")
    participants = []
    for pid, version in doc["versions"].items():
        row = bank.owned(session, PlanRow, pid, user)
        plan = TaskPlan.model_validate(row.document)
        if plan.version != version or conflict_id not in plan.conflict_ids or plan.status != "waiting_conflict":
            raise DomainError("STALE_CONFLICT", "任务版本或状态变化，请刷新冲突")
        participants.append((row, plan))
    if command.choice == "execute_plan" and command.selected_plan_id not in doc["versions"]:
        raise DomainError("INVALID_CONFLICT_CHOICE", "只能选择本次冲突中的任务", 422)
    if command.choice == "keep_subscription" and not doc["preference_ids"]:
        raise DomainError("INVALID_CONFLICT_CHOICE", "资金冲突不能使用保留会员选项", 422)
    if command.choice == "execute_plan":
        for pref_id in doc["preference_ids"]:
            bank.owned(session, PreferenceRow, pref_id, user).active = False
    for row, plan in participants:
        plan.conflict_ids = [x for x in plan.conflict_ids if x != conflict_id]
        selected = command.choice == "execute_plan" and plan.plan_id == command.selected_plan_id
        plan.status = "waiting_conflict" if plan.conflict_ids else "planned" if selected else "paused"
        plan.activated_until = (now() + timedelta(minutes=10)).isoformat() if selected else None
        invalidate(session, user, plan.plan_id)
        row.document = plan.model_dump(mode="json")
    doc.update(status="resolved", decision=command.model_dump(), resolved_at=stamp())
    conflict.document = doc
    record(session, user, "conflict.resolved", conflict_id, command.model_dump())
    return {"conflict": doc, "plans": [p for _, p in participants], "message": "选择已保存，未执行付款；选中任务仍需最新授权和资金检查"}
