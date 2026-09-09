import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .util import canonical, digest, now, uid

IMMUTABLE = (
    "resources",
    "briefs",
    "versions",
    "machine_results",
    "evidence",
    "decisions",
    "snapshots",
    "approvals",
    "releases",
    "events",
)


class Database:
    """SQLite WAL on one host. Every mutation uses one serialized write transaction.

    Keeping release checks and all invalidating mutations behind BEGIN IMMEDIATE
    gives a linearization point even with multiple API and worker processes.
    """

    def __init__(self, path):
        self.path = str(path)

    def connect(self):
        con = sqlite3.connect(self.path, isolation_level=None, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=15000")
        return con

    @contextmanager
    def read(self):
        con = self.connect()
        try:
            con.execute("BEGIN")
            yield con
            con.commit()
        finally:
            con.close()

    @contextmanager
    def write(self):
        con = self.connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def migrate(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        con = self.connect()
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        con.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, hash TEXT NOT NULL)"
        )
        con.close()
        with self.write() as c:
            for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                content = path.read_text()
                checksum = hashlib.sha256(content.encode()).hexdigest()
                old = c.execute("SELECT hash FROM schema_migrations WHERE version=?", (path.name,)).fetchone()
                if old:
                    if old["hash"] != checksum:
                        raise RuntimeError("Applied migration has changed")
                    continue
                for statement in content.split(";"):
                    if statement.strip():
                        c.execute(statement)
                c.execute("INSERT INTO schema_migrations VALUES(?,?)", (path.name, checksum))
            for table in IMMUTABLE:
                for verb in ("UPDATE", "DELETE"):
                    c.execute(
                        f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{verb} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'append-only record'); END"
                    )
            c.execute("""CREATE TRIGGER IF NOT EXISTS immutable_run_config BEFORE UPDATE ON runs
                WHEN NEW.plan != OLD.plan OR NEW.config != OLD.config OR NEW.plan_hash != OLD.plan_hash
                  OR NEW.config_hash != OLD.config_hash OR NEW.version_id != OLD.version_id
                  OR NEW.tenant_id != OLD.tenant_id OR NEW.asset_id != OLD.asset_id
                BEGIN SELECT RAISE(ABORT,'immutable assessment configuration'); END""")


def audit(c, tenant, actor, kind, subject, payload):
    previous = c.execute(
        "SELECT hash FROM events WHERE tenant_id=? ORDER BY seq DESC LIMIT 1", (tenant,)
    ).fetchone()
    previous_hash = previous["hash"] if previous else "0" * 64
    event = {
        "id": uid(),
        "tenant_id": tenant,
        "actor_id": actor,
        "kind": kind,
        "subject_id": subject,
        "payload": payload,
        "previous_hash": previous_hash,
        "created_at": now(),
    }
    c.execute(
        "INSERT INTO events(id,tenant_id,actor_id,kind,subject_id,payload,previous_hash,hash,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            event["id"],
            tenant,
            actor,
            kind,
            subject,
            canonical(payload),
            previous_hash,
            digest(event),
            event["created_at"],
        ),
    )


def check_audit(c, tenant):
    previous = "0" * 64
    for row in c.execute("SELECT * FROM events WHERE tenant_id=? ORDER BY seq", (tenant,)):
        e = dict(row)
        expected = e.pop("hash")
        e.pop("seq")
        e["payload"] = json.loads(e["payload"])
        if e["previous_hash"] != previous or digest(e) != expected:
            return False
        previous = expected
    return True
