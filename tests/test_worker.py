import threading
from concurrent.futures import ThreadPoolExecutor

from assurance.checkers import evaluate
from assurance.providers import DisabledProvider, FixtureProvider, ProviderError
from assurance.service import get, run_context
from assurance.worker import Worker


def scope(h, sub):
    h.request(
        "POST",
        f"/runs/{sub['run_id']}/scope",
        {
            "plan_hash": sub["plan_hash"],
            "inventory_complete": True,
            "reason": "Test scope",
            "evidence": "Fixture",
        },
    )


class TimeoutProvider(FixtureProvider):
    def extract(self, items):
        raise ProviderError("PROVIDER_TIMEOUT", True)


class MalformedProvider(FixtureProvider):
    def extract(self, items):
        raise ProviderError("MALFORMED_PROVIDER_OUTPUT")


def test_missing_credentials_and_malformed_stay_unknown(h):
    brief, _, _ = h.setup()
    for provider in [DisabledProvider(), MalformedProvider()]:
        sub = h.submit(brief)
        scope(h, sub)
        worker = Worker(h.db, h.app.state.settings, provider)
        assert worker.once()
        run = h.request("GET", f"/runs/{sub['run_id']}")
        assert run["snapshot"]["provider_error"]
        assert not run["release_eligible"] and run["snapshot"]["score"]["index"] is None
        assert all(
            c["outcome"] == "unknown"
            for key, c in run["snapshot"]["checks"].items()
            if key.startswith("claims:")
        )


def test_timeout_bounded_retries_and_visible_failure(h):
    brief, _, _ = h.setup()
    sub = h.submit(brief)
    scope(h, sub)
    worker = Worker(h.db, h.app.state.settings, TimeoutProvider())
    for attempt in range(3):
        assert worker.once()
        with h.db.write() as c:
            c.execute("UPDATE jobs SET available_at=0 WHERE run_id=?", (sub["run_id"],))
    run = h.request("GET", f"/runs/{sub['run_id']}")
    assert run["state"] == "failed" and run["job"]["attempts"] == 3
    assert run["job"]["last_error"] == "PROVIDER_TIMEOUT"
    assert not worker.once() and not run["release_eligible"]


def test_duplicate_completion_and_out_of_order_edit(h):
    brief, _, _ = h.setup()
    first = h.submit(brief)
    scope(h, first)
    job = h.worker.claim()
    with h.db.read() as c:
        context = run_context(c, get(c, "runs", "tenant-a", first["run_id"]))
    result = evaluate(context, FixtureProvider())
    second = h.submit(
        brief, asset_id=first["asset_id"], expected_version_id=first["version_id"], origin="revision"
    )
    assert not h.worker.finish(job, result)
    h.run(second)
    assert not h.worker.finish(job, result)
    asset = h.request("GET", f"/assets/{first['asset_id']}")
    assert asset["current_run_id"] == second["run_id"]
    with h.db.read() as c:
        assert (
            c.execute("SELECT COUNT(*) FROM machine_results WHERE run_id=?", (first["run_id"],)).fetchone()[0]
            == 0
        )


def test_worker_lease_recovery_fencing_and_single_result(h):
    brief, _, _ = h.setup()
    sub = h.submit(brief)
    scope(h, sub)
    first = h.worker.claim()
    with h.db.write() as c:
        c.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (first["id"],))
    second = h.worker.claim()
    assert second["id"] == first["id"] and second["lease_token"] != first["lease_token"]
    assert not h.worker.renew(first)
    assert h.worker.process(second)
    assert not h.worker.process(first)
    assert not h.worker.process(second)
    with h.db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM machine_results").fetchone()[0] == 1


def test_final_attempt_worker_crash_does_not_strand_job(h):
    brief, _, _ = h.setup()
    sub = h.submit(brief)
    scope(h, sub)
    job = h.worker.claim()
    with h.db.write() as c:
        c.execute("UPDATE jobs SET lease_until=0,attempts=3 WHERE id=?", (job["id"],))
    assert h.worker.claim() is None
    assert h.request("GET", f"/runs/{sub['run_id']}")["state"] == "failed"


def test_two_workers_cannot_claim_one_job(h):
    brief, _, _ = h.setup()
    sub = h.submit(brief)
    scope(h, sub)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(lambda _: h.worker.claim(), range(2)))
    assert sum(j is not None for j in jobs) == 1


def test_release_serializes_with_source_revocation(h, monkeypatch):
    import assurance.service as service_module

    brief, source, _ = h.setup()
    sub = h.submit(brief)
    h.run(sub)
    snapshot = h.complete_review(sub["run_id"])
    approval = h.approve(sub["run_id"])
    reached, resume, revocation_started = threading.Event(), threading.Event(), threading.Event()
    real = service_module.resource_valid

    def paused(*args, **kwargs):
        if threading.current_thread().name.startswith("release"):
            reached.set()
            assert resume.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(service_module, "resource_valid", paused)
    outcome = {}

    def release():
        outcome["release"] = h.release(sub, snapshot, approval)

    # Call the service directly to retain the test thread name at its transaction.
    from assurance.auth import authenticate
    from assurance.schemas import Reason, ReleaseIn

    with h.db.read() as c:
        owner = authenticate(c, h.identities["owner"][1], "local")
        admin = authenticate(c, h.identities["admin"][1], "local")

    def direct_release():
        outcome["release"] = h.app.state.service.release(
            owner,
            sub["asset_id"],
            ReleaseIn(
                version_id=sub["version_id"],
                snapshot_id=snapshot["id"],
                snapshot_hash=snapshot["hash"],
                approval_id=approval["id"],
            ),
        )

    def revoke():
        revocation_started.set()
        outcome["revoke"] = h.app.state.service.resource_decision(
            admin, "source", source["id"], Reason(reason="Revoked", evidence="Authority changed"), False
        )

    t1 = threading.Thread(target=direct_release, name="release-test")
    t1.start()
    assert reached.wait(5)
    t2 = threading.Thread(target=revoke)
    t2.start()
    assert revocation_started.wait(2)
    resume.set()
    t1.join(5)
    t2.join(5)
    assert not t1.is_alive() and not t2.is_alive()
    assert outcome["release"]["status"] == "released"
    assert outcome["revoke"]["status"] == "revoked"
    assert h.request("GET", f"/assets/{sub['asset_id']}")["released_id"] is None
    h.release(sub, snapshot, approval, 409)
