"""One-shot, exact-plan faults. Claims are outside the business savepoint."""
from datetime import datetime
from sqlalchemy import select
from pact.audit import record
from pact.common import now
from pact.storage import FaultRow


def claim(session, user, plan, step, point):
    if not session.info.get("sandbox_controls_enabled"):
        return False
    rows = session.scalars(select(FaultRow).where(FaultRow.user_id == user, FaultRow.plan_id == plan.plan_id, FaultRow.plan_version == plan.version, FaultRow.step_id == step.step_id, FaultRow.point == point, FaultRow.remaining > 0).order_by(FaultRow.id)).all()
    for row in rows:
        if datetime.fromisoformat(row.expires_at) <= now():
            continue
        row.remaining = 0
        session.flush()
        record(session, user, "sandbox.fault.consumed", row.id, {"plan_id": plan.plan_id, "step_id": step.step_id, "point": point})
        return True
    return False


def claim_post(session, user, plan, step):
    for point in ("before_post_reject", "after_mutation_rollback"):
        if claim(session, user, plan, step, point):
            return point
    return None
