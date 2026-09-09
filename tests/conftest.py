import uuid

import pytest
from fastapi.testclient import TestClient

from assurance.api import create_app
from assurance.auth import provision
from assurance.settings import Settings
from assurance.worker import Worker

SOURCE_TEXT = "The warranty lasts 24 months. Contact support if the device fails."


class Harness:
    def __init__(self, client, app):
        self.client, self.app = client, app
        self.db = app.state.db
        self.worker = Worker(self.db, app.state.settings)
        self.identities = {}
        for name, roles in {
            "owner": ["approver", "reviewer", "submitter"],
            "reviewer": ["reviewer"],
            "specialist": ["reviewer", "specialist"],
            "admin": ["source_admin", "policy_admin"],
            "submitter": ["submitter"],
        }.items():
            pid, token = provision(self.db, "tenant-a", name, roles)
            self.identities[name] = (pid, token)
        pid, token = provision(
            self.db,
            "tenant-b",
            "other",
            ["reviewer", "approver", "submitter", "source_admin", "policy_admin"],
        )
        self.identities["other"] = (pid, token)

    def request(self, method, path, data=None, who="owner", status=200, **kwargs):
        headers = {"Authorization": "Bearer " + self.identities[who][1]}
        headers.update(kwargs.pop("headers", {}))
        r = self.client.request(method, "/v1" + path, json=data, headers=headers, **kwargs)
        if status is not None:
            assert r.status_code == status, (r.status_code, r.text)
        return r.json()

    def setup(
        self, *, profile="Support and knowledge", tier="Standard", source_text=SOURCE_TEXT, brief_extra=None
    ):
        scope = {
            "markets": ["IE"],
            "languages": ["en"],
            "profiles": [profile],
            "uses": ["assessment", "generation"],
            "effective_from": "2020-01-01T00:00:00Z",
        }
        source = self.request(
            "POST",
            "/resources/source",
            {"key": "product", "title": "Approved product facts", "scope": scope, "text": source_text},
            "admin",
            201,
        )
        policy = self.request(
            "POST",
            "/resources/policy",
            {"key": "policy", "title": "Pilot policy", "scope": scope, "text": "Use accurate information."},
            "admin",
            201,
        )
        for kind, resource in [("source", source), ("policy", policy)]:
            self.request(
                "POST",
                f"/resources/{kind}/{resource['id']}/approve",
                {"reason": "Fixture authority reviewed", "evidence": "Synthetic source-owner record"},
                "admin",
            )
        brief = {
            "title": "Support brief",
            "purpose": "Explain warranty and escalation",
            "audience": "Device owners",
            "acceptance_criteria": ["Warranty duration and escalation are clear"],
            "owner_id": self.identities["owner"][0],
            "profile": profile,
            "tier": tier,
            "market": "IE",
            "language": "en",
            "policy_key": "policy",
            "source_keys": ["product"],
        }
        if tier == "High":
            brief["specialist_requirements"] = ["Domain-qualified warranty review"]
        brief.update(brief_extra or {})
        b = self.request("POST", "/briefs", brief, status=201)
        return b["id"], source, policy

    def submit(self, brief_id, *, content=SOURCE_TEXT, fmt="text/plain", **extra):
        data = {"brief_id": brief_id, "title": "Warranty help", "format": fmt, "content": content, **extra}
        return self.request(
            "POST",
            "/versions",
            data,
            who="submitter",
            status=202,
            headers={"Idempotency-Key": uuid.uuid4().hex},
        )

    def run(self, submission, *, inventory_complete=True):
        self.request(
            "POST",
            f"/runs/{submission['run_id']}/scope",
            {
                "plan_hash": submission["plan_hash"],
                "inventory_complete": inventory_complete,
                "reason": "Synthetic owner inspected the complete fixture inventory",
                "evidence": "Fixture scope record",
            },
        )
        assert self.worker.once()
        return self.request("GET", f"/runs/{submission['run_id']}")

    def evidence(self, rid, who="reviewer"):
        return self.request(
            "POST",
            f"/runs/{rid}/evidence",
            {
                "kind": "review",
                "note": "Synthetic test fixture: complete passage and requirement inspection, not real expert validation.",
                "method": "fixture-human-review-1",
            },
            who,
            201,
        )["id"]

    def complete_review(self, rid, *, who="reviewer", ratings=None):
        run = self.request("GET", f"/runs/{rid}")
        sid = run["snapshot"]["id"]
        ev = self.evidence(rid, who)
        source = self.request("GET", "/resources/source/product", who=who)
        text = source["payload"]["text"]
        source_ev = self.request(
            "POST",
            f"/runs/{rid}/evidence",
            {
                "kind": "source",
                "note": "Synthetic fixture claim-to-source review",
                "method": "fixture-manual-comparison-1",
                "source_id": source["id"],
                "start": 0,
                "end": len(text),
                "quote": text,
            },
            who,
            201,
        )["id"]
        data = {
            "expected_snapshot_id": sid,
            "criteria": [
                {
                    "criterion": key,
                    "rating": (ratings or {}).get(key, 4),
                    "evidence_ids": [ev, source_ev],
                    "method_version": "fixture-human-1",
                    "reason": "Synthetic fixture reviewer judgment",
                }
                for key, value in run["snapshot"]["criteria"].items()
                if value.get("applicable", True)
            ],
            "examinations": [
                {
                    "examination_id": ex["id"],
                    "outcome": "pass",
                    "evidence_ids": [ev],
                    "reason": "Synthetic manual fixture examination",
                }
                for ex in run["plan"]
                if not ex["id"].startswith("criterion:") and ex["mode"] != "specialist"
            ],
            "gates": [
                {
                    "gate": f"R{i}",
                    "state": "pass",
                    "evidence_ids": [ev],
                    "reason": "Synthetic fixture gate verification",
                }
                for i in range(2, 7)
            ],
            "resolutions": [
                {
                    "finding_id": f["id"],
                    "disposition": "dismissed",
                    "reason": "Synthetic fixture adjudication with recorded evidence",
                    "evidence_ids": [ev],
                }
                for f in run["snapshot"]["findings"]
                if f["state"] == "open"
            ],
        }
        return self.request("POST", f"/runs/{rid}/reviews", data, who)["snapshot"]

    def approve(self, rid, snapshot=None, status=200):
        snapshot = snapshot or self.request("GET", f"/runs/{rid}")["snapshot"]
        return self.request(
            "POST",
            f"/runs/{rid}/approve",
            {
                "snapshot_id": snapshot["id"],
                "snapshot_hash": snapshot["hash"],
                "reason": "Synthetic demo owner approves this exact version",
                "evidence": "Fixture decision",
            },
            status=status,
        )

    def release(self, submission, snapshot, approval, status=200):
        return self.request(
            "POST",
            f"/assets/{submission['asset_id']}/release",
            {
                "version_id": submission["version_id"],
                "snapshot_id": snapshot["id"],
                "snapshot_hash": snapshot["hash"],
                "approval_id": approval["id"],
            },
            status=status,
        )


@pytest.fixture
def h(tmp_path):
    app = create_app(Settings(db=str(tmp_path / "test.sqlite3"), provider="fixture", lease_seconds=3))
    with TestClient(app) as client:
        yield Harness(client, app)
