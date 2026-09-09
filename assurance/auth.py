import hashlib
import json
import secrets
from dataclasses import dataclass

from .db import audit
from .util import canonical, now, uid

ROLES = {"submitter", "source_admin", "policy_admin", "reviewer", "specialist", "approver"}


@dataclass(frozen=True)
class Principal:
    id: str
    tenant_id: str
    name: str
    roles: frozenset[str]
    human: bool
    local_only: bool


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def provision(db, tenant, name, roles, *, human=True, local_only=False, token=None, principal_id=None):
    if not set(roles) <= ROLES:
        raise ValueError("Unknown role")
    if not human and set(roles) & {"reviewer", "specialist", "approver"}:
        raise ValueError("Human decision roles require a human principal")
    token = token or secrets.token_urlsafe(40)
    pid = principal_id or uid()
    with db.write() as c:
        c.execute("INSERT OR IGNORE INTO tenants VALUES(?,?)", (tenant, tenant))
        c.execute(
            "INSERT INTO principals(id,tenant_id,name,roles,token_hash,human,local_only,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                pid,
                tenant,
                name,
                canonical(sorted(roles)),
                token_hash(token),
                int(human),
                int(local_only),
                now(),
            ),
        )
        audit(c, tenant, "operator", "principal.provisioned", pid, {"roles": roles, "local_only": local_only})
    return pid, token


def authenticate(c, token, mode):
    row = c.execute(
        "SELECT * FROM principals WHERE token_hash=? AND active=1", (token_hash(token),)
    ).fetchone()
    if not row or (row["local_only"] and mode != "local"):
        return None
    return Principal(
        row["id"],
        row["tenant_id"],
        row["name"],
        frozenset(json.loads(row["roles"])),
        bool(row["human"]),
        bool(row["local_only"]),
    )
