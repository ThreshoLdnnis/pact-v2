import hashlib
import json
import uuid
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc)


def stamp():
    return now().isoformat()


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class DomainError(Exception):
    def __init__(self, code, message, status=409, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details
        super().__init__(message)

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}
