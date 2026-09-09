import hashlib
import json
import uuid
from datetime import UTC, datetime


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def uid():
    return uuid.uuid4().hex


def now():
    return datetime.now(UTC).isoformat()


def unpack(row):
    return dict(row) if row else None
