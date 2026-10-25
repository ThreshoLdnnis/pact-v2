from sqlalchemy import select
from pact.common import digest, stamp
from pact.storage import Audit


def event_payload(row):
    return {"user_id": row.user_id, "event": row.event, "entity_id": row.entity_id, "details": row.details, "created_at": row.created_at}


def record(session, user, event, entity, details=None):
    session.flush()
    previous = session.scalars(select(Audit).order_by(Audit.id.desc()).limit(1)).first()
    row = Audit(user_id=user, event=event, entity_id=entity, details=details or {}, created_at=stamp(), previous_hash=previous.event_hash if previous else "0" * 64)
    row.event_hash = digest({"previous_hash": row.previous_hash, "event": event_payload(row)})
    session.add(row)
    session.flush()


def verify_chain(session):
    previous = "0" * 64
    rows = session.scalars(select(Audit).order_by(Audit.id)).all()
    for row in rows:
        if row.previous_hash != previous or row.event_hash != digest({"previous_hash": previous, "event": event_payload(row)}):
            return False
        previous = row.event_hash
    return True
