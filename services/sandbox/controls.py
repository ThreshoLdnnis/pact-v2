"""Administrative synthetic fixtures. No real bank or arbitrary SQL surface."""
from datetime import timedelta
from sqlalchemy import delete, select
from pact.audit import record
from pact.common import DomainError, now, stamp, uid
from pact.storage import Account, Audit, Base, Commitment, FaultRow, Ledger, PlanRow
from services.banking import service as bank


def reset(session, scenario):
    # The caller must hold Database.session(write=True). Keep the audit history.
    for table in reversed(Base.metadata.sorted_tables):
        if table.name != Audit.__tablename__:
            session.execute(delete(table))
    session.expire_all()
    bank.seed(session)
    session.flush()
    if scenario == "tight_budget":
        account = session.get(Account, "acct-alice")
        adjustment = account.balance_cents - 200_000
        account.balance_cents -= adjustment
        session.get(Account, "acct-clearing").balance_cents += adjustment
        when = stamp()
        session.add_all([
            Ledger(transaction_id="fixture-tight-budget", account_id=account.id, amount_cents=-adjustment, category="合成场景支出", memo="资金紧张测试初值", created_at=when),
            Ledger(transaction_id="fixture-tight-budget", account_id="acct-clearing", amount_cents=adjustment, category="合成场景支出", memo="资金紧张测试对手账", created_at=when),
        ])
        session.get(Commitment, "com-rent").amount_cents = 50_000
        # Only the selected next video renewal is cancellable in this fixture.
        session.get(Commitment, "com-music").status = "fulfilled"
    epoch = uid("reset")
    record(session, "sandbox_admin", "sandbox.reset", epoch, {"scenario": scenario, "sessions_revoked": True})
    return {"reset": True, "scenario": scenario, "epoch": epoch, "sessions_revoked": True, "audit_preserved": True, "message": "合成业务数据已重置，旧会话、审批、回执和故障失效，请重新登录"}


def arm(session, command):
    row = session.get(PlanRow, command.plan_id)
    if not row or row.document["version"] != command.plan_version:
        raise DomainError("FAULT_TARGET_INVALID", "故障目标计划不存在或版本已变化", 404)
    step = next((s for s in row.document["steps"] if s["step_id"] == command.step_id), None)
    if not step or step["status"] in {"succeeded", "failed", "pending_verification"} or row.document["status"] in {"succeeded", "failed", "partially_completed", "handed_off", "pending_verification"}:
        raise DomainError("FAULT_TARGET_INVALID", "只能针对尚未执行的当前步骤注入单次故障")
    if command.point == "after_mutation_rollback" and step["action"]["tool"] not in {"transfer", "cancel_subscription", "schedule_transfer"}:
        raise DomainError("FAULT_POINT_INVALID", "变更后回滚仅适用于写操作", 422)
    active = session.scalars(select(FaultRow).where(FaultRow.plan_id == command.plan_id, FaultRow.plan_version == command.plan_version, FaultRow.step_id == command.step_id, FaultRow.remaining > 0, FaultRow.expires_at > now().isoformat())).first()
    if active:
        raise DomainError("FAULT_ALREADY_ARMED", "此步骤已有待触发故障，请先清除")
    fault = FaultRow(id=uid("fault"), user_id=row.user_id, plan_id=command.plan_id, plan_version=command.plan_version, step_id=command.step_id, point=command.point, remaining=1, expires_at=(now() + timedelta(minutes=10)).isoformat())
    session.add(fault)
    record(session, "sandbox_admin", "sandbox.fault.armed", fault.id, command.model_dump())
    return {"fault_id": fault.id, "remaining": 1, "expires_at": fault.expires_at, **command.model_dump()}


def clear(session):
    session.execute(delete(FaultRow))
    record(session, "sandbox_admin", "sandbox.faults.cleared", "all")
    return {"cleared": True}
