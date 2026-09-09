from datetime import UTC, datetime, timedelta

import pytest

from assurance.api import create_app
from assurance.auth import authenticate, provision
from assurance.schemas import Scope
from assurance.service import resource_valid
from assurance.settings import Settings


def test_source_scope_effective_dates_and_permitted_use():
    scope = {
        "markets": ["IE"],
        "languages": ["en"],
        "profiles": ["General"],
        "uses": ["assessment"],
        "effective_from": "2020-01-01T00:00:00+00:00",
        "effective_until": "2030-01-01T00:00:00+00:00",
    }
    source = {"payload": {"scope": scope, "origin": "external"}}
    brief = {"market": "IE", "language": "en", "profile": "General"}
    assert resource_valid(source, "approved", brief, at=datetime(2026, 1, 1, tzinfo=UTC))[0]
    assert not resource_valid(source, "candidate", brief)[0]
    assert not resource_valid(source, "approved", brief, use="generation")[0]
    assert not resource_valid(source, "approved", {**brief, "market": "US"})[0]
    assert not resource_valid(source, "approved", {**brief, "language": "fr"})[0]
    assert not resource_valid(source, "approved", brief, at=datetime(2030, 1, 1, tzinfo=UTC))[0]
    assert not resource_valid(source, "approved", brief, at=datetime(2019, 1, 1, tzinfo=UTC))[0]
    with pytest.raises(ValueError):
        Scope(**{**scope, "effective_from": "2020-01-01"})


def test_source_expiry_invalidates_on_read_and_worker_schedules(h, monkeypatch):
    import assurance.service as service

    brief, _, _ = h.setup()
    source = h.request("GET", "/resources/source/product", who="admin")
    end = datetime.now(UTC) + timedelta(days=1)
    payload = source["payload"]
    payload["scope"]["effective_until"] = end.isoformat()
    source = h.request("POST", "/resources/source", payload, "admin", 201)
    h.request(
        "POST",
        f"/resources/source/{source['id']}/approve",
        {"reason": "Authority time limited", "evidence": "Expires tomorrow"},
        "admin",
    )
    sub = h.submit(brief)
    h.run(sub)
    snapshot = h.complete_review(sub["run_id"])
    approval = h.approve(sub["run_id"])

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return end + timedelta(seconds=1)

    monkeypatch.setattr(service, "datetime", Future)
    assert h.request("GET", f"/runs/{sub['run_id']}")["state"] == "stale"
    h.release(sub, snapshot, approval, 409)
    h.worker.refresh_stale()
    asset = h.request("GET", f"/assets/{sub['asset_id']}")
    assert asset["current_run_id"] != sub["run_id"]
    assert h.request("GET", f"/runs/{asset['current_run_id']}")["state"] == "awaiting_scope"


def test_production_rejects_local_development_credentials_and_fixture(h, tmp_path):
    pid, token = provision(h.db, "tenant-a", "Local only", ["reviewer"], local_only=True)
    with h.db.read() as c:
        assert authenticate(c, token, "local")
        assert authenticate(c, token, "production") is None
    with pytest.raises(ValueError):
        create_app(Settings(db=str(tmp_path / "prod.sqlite3"), mode="production", provider="fixture"))
    with pytest.raises(ValueError):
        provision(h.db, "tenant-a", "Machine approver", ["approver"], human=False)


def test_atomic_submission_rolls_back_when_scheduling_fails(h, monkeypatch):
    import assurance.service as service
    from assurance.auth import authenticate
    from assurance.schemas import Submit

    brief, _, _ = h.setup()
    with h.db.read() as c:
        p = authenticate(c, h.identities["submitter"][1], "local")

    def fail(*args, **kwargs):
        raise RuntimeError("Injected outbox persistence failure")

    monkeypatch.setattr(service, "schedule", fail)
    with pytest.raises(RuntimeError):
        h.app.state.service.submit(
            p, Submit(brief_id=brief, title="test", content="text", format="txt"), "transaction-test"
        )
    with h.db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_evaluator_configuration_change_invalidates_exact_approval(h):
    from dataclasses import replace

    from assurance.auth import authenticate
    from assurance.schemas import ReleaseIn
    from assurance.service import DomainError, Service

    brief, _, _ = h.setup()
    sub = h.submit(brief)
    h.run(sub)
    snapshot = h.complete_review(sub["run_id"])
    approval = h.approve(sub["run_id"])
    changed = replace(h.app.state.settings, provider_model="changed-model")
    service = Service(h.db, changed)
    with h.db.read() as c:
        owner = authenticate(c, h.identities["owner"][1], "local")
    with pytest.raises(DomainError, match="no longer current"):
        service.release(
            owner,
            sub["asset_id"],
            ReleaseIn(
                version_id=sub["version_id"],
                snapshot_id=snapshot["id"],
                snapshot_hash=snapshot["hash"],
                approval_id=approval["id"],
            ),
        )
    assert changed.evaluator()["implementation_hash"] and changed.evaluator()["libraries"]
