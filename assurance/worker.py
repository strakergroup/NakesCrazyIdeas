import threading
import time

from .checkers import evaluate
from .db import audit
from .providers import get_provider
from .service import assemble_snapshot, fresh, get, run_context, schedule
from .util import canonical, digest, now, uid


class Worker:
    def __init__(self, db, settings, provider=None):
        self.db, self.settings = db, settings
        self.provider = provider or get_provider(settings)

    def refresh_stale(self):
        with self.db.write() as c:
            assets = c.execute("SELECT * FROM assets WHERE current_run_id IS NOT NULL").fetchall()
            for a in assets:
                run = get(c, "runs", a["tenant_id"], a["current_run_id"])
                valid, reason = fresh(c, run, self.settings)
                if not valid:
                    version = get(c, "versions", a["tenant_id"], a["latest_version_id"])
                    schedule(c, a["tenant_id"], dict(a), version, self.settings, "worker")

    def claim(self):
        stamp = time.time()
        with self.db.write() as c:
            # A crash on the final permitted attempt cannot strand a lease forever.
            exhausted = c.execute(
                "SELECT j.* FROM jobs j JOIN runs r ON r.id=j.run_id WHERE j.state='running' AND j.lease_until<=? AND j.attempts>=? AND r.state='processing'",
                (stamp, self.settings.max_attempts),
            ).fetchall()
            for j in exhausted:
                c.execute(
                    "UPDATE jobs SET state='failed',lease_token=NULL,last_error='WORKER_LEASE_EXHAUSTED' WHERE id=?",
                    (j["id"],),
                )
                c.execute("UPDATE runs SET state='failed' WHERE id=?", (j["run_id"],))
                audit(
                    c, j["tenant_id"], "worker", "job.failed", j["id"], {"reason": "WORKER_LEASE_EXHAUSTED"}
                )
            row = c.execute(
                """SELECT j.* FROM jobs j JOIN runs r ON r.id=j.run_id
                JOIN assets a ON a.current_run_id=r.id
                WHERE ((j.state='queued' AND j.available_at<=? AND r.state='queued')
                OR (j.state='running' AND j.lease_until<=? AND r.state='processing'))
                AND j.attempts<? ORDER BY j.created_at,j.id LIMIT 1""",
                (stamp, stamp, self.settings.max_attempts),
            ).fetchone()
            if not row:
                return None
            token = uid()
            c.execute(
                "UPDATE jobs SET state='running',attempts=attempts+1,lease_token=?,lease_until=? WHERE id=?",
                (token, stamp + self.settings.lease_seconds, row["id"]),
            )
            c.execute("UPDATE runs SET state='processing' WHERE id=?", (row["run_id"],))
            audit(c, row["tenant_id"], "worker", "job.claimed", row["id"], {"attempt": row["attempts"] + 1})
            return {**dict(row), "lease_token": token, "attempts": row["attempts"] + 1}

    def renew(self, job):
        with self.db.write() as c:
            cur = c.execute(
                "UPDATE jobs SET lease_until=? WHERE id=? AND state='running' AND lease_token=? AND lease_until>?",
                (time.time() + self.settings.lease_seconds, job["id"], job["lease_token"], time.time()),
            )
            return cur.rowcount == 1

    def finish(self, job, result):
        with self.db.write() as c:
            current = c.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if (
                not current
                or current["state"] != "running"
                or current["lease_token"] != job["lease_token"]
                or current["lease_until"] <= time.time()
            ):
                return False
            run = get(c, "runs", job["tenant_id"], job["run_id"])
            valid, reason = fresh(c, run, self.settings)
            if not valid:
                c.execute("UPDATE jobs SET state='cancelled',lease_token=NULL WHERE id=?", (job["id"],))
                c.execute("UPDATE runs SET state='stale' WHERE id=?", (run["id"],))
                audit(
                    c,
                    job["tenant_id"],
                    "worker",
                    "job.stale_completion_discarded",
                    job["id"],
                    {"reason": reason},
                )
                return False
            error = result.get("provider_error")
            if error and error["retryable"] and current["attempts"] < self.settings.max_attempts:
                delay = min(30, 2 ** current["attempts"])
                c.execute(
                    "UPDATE jobs SET state='queued',available_at=?,lease_token=NULL,lease_until=NULL,last_error=? WHERE id=?",
                    (time.time() + delay, error["code"], job["id"]),
                )
                c.execute("UPDATE runs SET state='queued' WHERE id=?", (run["id"],))
                audit(
                    c,
                    job["tenant_id"],
                    "worker",
                    "job.retry_scheduled",
                    job["id"],
                    {"reason": error["code"], "attempt": current["attempts"]},
                )
                return True
            failed = bool(error and error["retryable"])
            c.execute(
                "INSERT INTO machine_results VALUES(?,?,?,?,?)",
                (run["id"], run["tenant_id"], canonical(result), digest(result), now()),
            )
            c.execute(
                "UPDATE jobs SET state=?,lease_token=NULL,lease_until=NULL,last_error=? WHERE id=?",
                ("failed" if failed else "done", error["code"] if error else None, job["id"]),
            )
            c.execute("UPDATE runs SET state=? WHERE id=?", ("failed" if failed else "completed", run["id"]))
            assemble_snapshot(c, run)
            audit(
                c,
                job["tenant_id"],
                "worker",
                "job.failed" if failed else "job.completed",
                job["id"],
                {"provider_error": error, "fixture": result["fixture"]},
            )
            return True

    def process(self, job):
        with self.db.read() as c:
            run = get(c, "runs", job["tenant_id"], job["run_id"])
            context = run_context(c, run)
        stop = threading.Event()

        def heartbeat():
            while not stop.wait(self.settings.lease_seconds / 3):
                try:
                    if not self.renew(job):
                        return
                except Exception:
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            try:
                result = evaluate(context, self.provider)
            except Exception:
                # Persist only a safe error code, never document text or secrets.
                from .checkers import base_result

                result = {
                    "checks": {
                        e["id"]: base_result(
                            e, context["extraction"], reason="INTERNAL_CHECKER_FAILURE"
                        ).model_dump()
                        for e in context["plan"]
                    },
                    "claims": [],
                    "comparisons": [],
                    "provider_error": {"code": "INTERNAL_CHECKER_FAILURE", "retryable": True},
                    "provider_label": self.provider.label,
                    "fixture": "fixture" in self.provider.label,
                }
            return self.finish(job, result)
        finally:
            stop.set()
            thread.join(timeout=1)

    def once(self):
        self.refresh_stale()
        job = self.claim()
        if not job:
            return False
        self.process(job)
        return True
