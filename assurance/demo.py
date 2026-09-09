"""Executable HTTP integration example. Every simulated judgment is labelled a fixture."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from .cli import init_demo
from .db import Database
from .util import now, uid

SOURCE = "The warranty lasts 24 months. Contact support if the device fails."


class ExampleClient:
    def __init__(self, base_url, credentials):
        self.client = httpx.Client(base_url=base_url, timeout=15, trust_env=False)
        self.identities = credentials["identities"]

    def request(self, method, path, data=None, *, who="owner", expected=(200, 201, 202), idem=None):
        headers = {"Authorization": "Bearer " + self.identities[who]["token"]}
        if idem:
            headers["Idempotency-Key"] = idem
        response = self.client.request(method, "/v1" + path, headers=headers, json=data)
        if response.status_code not in expected:
            raise RuntimeError(f"{method} {path}: {response.status_code}: {response.text}")
        return response.json()

    def wait(self, rid, deadline_seconds=30):
        deadline = time.monotonic() + deadline_seconds
        while time.monotonic() < deadline:
            run = self.request("GET", f"/runs/{rid}")
            if run["state"] in {"completed", "failed", "stale"}:
                if run["state"] != "completed":
                    raise RuntimeError("Assessment did not complete: " + run["state"])
                return run
            time.sleep(0.1)
        raise TimeoutError("Worker did not finish the local demonstration")

    def execute_fixture_demo(self):
        print(
            "Offline demonstration: synthetic data, fixture model responses and scripted human-review identities.",
            flush=True,
        )
        scope = {
            "markets": ["IE"],
            "languages": ["en"],
            "profiles": ["Support and knowledge"],
            "uses": ["assessment", "generation"],
            "effective_from": "2020-01-01T00:00:00Z",
        }
        suffix = uid()[:8]
        source = self.request(
            "POST",
            "/resources/source",
            {
                "key": "warranty-" + suffix,
                "title": "Synthetic manufacturer record",
                "scope": scope,
                "text": SOURCE,
            },
            who="admin",
        )
        policy = self.request(
            "POST",
            "/resources/policy",
            {
                "key": "support-" + suffix,
                "title": "Synthetic support policy",
                "scope": scope,
                "text": "State the warranty duration and support escalation.",
                "required_text": ["Contact support"],
            },
            who="admin",
        )
        for kind, resource in [("source", source), ("policy", policy)]:
            self.request(
                "POST",
                f"/resources/{kind}/{resource['id']}/approve",
                {
                    "reason": "OFFLINE FIXTURE source authority approved for this synthetic example",
                    "evidence": "Synthetic manufacturer record and local demo rights.",
                },
                who="admin",
            )
        brief = self.request(
            "POST",
            "/briefs",
            {
                "title": "Synthetic warranty support brief",
                "purpose": "Explain warranty duration and escalation",
                "audience": "Device owners",
                "acceptance_criteria": ["Explain duration and when to contact support"],
                "owner_id": self.identities["owner"]["id"],
                "profile": "Support and knowledge",
                "tier": "Standard",
                "market": "IE",
                "language": "en",
                "policy_key": policy["key"],
                "source_keys": [source["key"]],
                "required_text": ["24 months", "Contact support"],
            },
        )
        context = self.request("GET", f"/generation-context/{brief['id']}", who="submitter")
        # A deterministic generator demonstrates the integration seam. A platform
        # may replace this line with its own generator using this approved context.
        draft = context["sources"][0]["text"]
        sub = self.request(
            "POST",
            "/versions",
            {
                "brief_id": brief["id"],
                "title": "Synthetic warranty guidance",
                "format": "text/plain",
                "content": draft,
                "origin": "generated",
            },
            who="submitter",
            idem="generated-" + suffix,
        )
        rid = sub["run_id"]
        initial = self.request("GET", f"/runs/{rid}")
        self.request(
            "POST",
            f"/runs/{rid}/scope",
            {
                "plan_hash": initial["plan_hash"],
                "inventory_complete": True,
                "reason": "OFFLINE FIXTURE: paragraph, required text and all 24 criterion examinations reviewed before execution",
                "evidence": "Synthetic scope inventory reviewed by the LOCAL DEMO owner identity.",
            },
        )
        run = self.wait(rid)
        first_snapshot = run["snapshot"]
        blocked = self.request(
            "POST",
            f"/runs/{rid}/approve",
            {
                "snapshot_id": first_snapshot["id"],
                "snapshot_hash": first_snapshot["hash"],
                "reason": "Demonstrate missing review prevents approval",
                "evidence": "Fixture attempt",
            },
            expected=(409,),
        )
        print(
            "Automatic checks finished. Approval correctly blocked while human examinations are incomplete.",
            flush=True,
        )
        source_evidence = self.request(
            "POST",
            f"/runs/{rid}/evidence",
            {
                "kind": "source",
                "note": "OFFLINE FIXTURE exact synthetic warranty passage",
                "method": "fixture-passage-comparison-1",
                "source_id": source["id"],
                "start": 0,
                "end": len(SOURCE),
                "quote": SOURCE,
            },
            who="reviewer",
        )
        notes = {
            "E": "Synthetic authority, fact support, source locators and absence of source conflicts checked against the single supplied warranty record.",
            "M": "Both sentences match the source; quantities, qualifications, internal consistency and the representation are unchanged.",
            "C": "The duration and escalation fulfill the synthetic brief; there is no multi-step procedure in this paragraph.",
            "G": "Synthetic policy wording, local-only data permissions, named review ownership and version records checked.",
            "U": "Synthetic plain-text comprehension, sentence order and plain-text delivery/accessibility review completed for this test fixture only.",
            "B": "Synthetic neutral support voice, naming, English/IE wording and plain-text channel review completed.",
        }
        evidence = {}
        for dim, note in notes.items():
            ev = self.request(
                "POST",
                f"/runs/{rid}/evidence",
                {
                    "kind": "review",
                    "note": "OFFLINE FIXTURE — "
                    + note
                    + " This scripted record is not real expert validation.",
                    "method": "scripted-human-review-fixture-1",
                },
                who="reviewer",
            )
            evidence[dim] = ev["id"]
        review = {
            "expected_snapshot_id": first_snapshot["id"],
            "criteria": [
                {
                    "criterion": k,
                    "rating": 4,
                    "evidence_ids": [evidence[k[0]], source_evidence["id"]],
                    "method_version": "scripted-human-review-fixture-1",
                    "reason": "OFFLINE FIXTURE judgment against the criterion-specific review note and exact source passage.",
                }
                for k in first_snapshot["criteria"]
            ],
            "examinations": [
                {
                    "examination_id": e["id"],
                    "outcome": "pass",
                    "evidence_ids": [evidence.get(e["criterion"][0], evidence["G"]), source_evidence["id"]],
                    "reason": "OFFLINE FIXTURE original paragraph and specified requirement manually simulated; no missing material in this seeded example.",
                }
                for e in run["plan"]
                if not e["id"].startswith("criterion:")
                and first_snapshot["checks"][e["id"]]["outcome"] == "unknown"
            ],
            "gates": [
                {
                    "gate": f"R{i}",
                    "state": "pass",
                    "evidence_ids": [evidence["G"]],
                    "reason": "OFFLINE FIXTURE pre-release gate review against the synthetic brief.",
                }
                for i in range(2, 7)
            ],
        }
        snapshot = self.request("POST", f"/runs/{rid}/reviews", review, who="reviewer")["snapshot"]
        if not snapshot["score"]["readiness"]:
            raise RuntimeError("Complete fixture should be ready: " + json.dumps(snapshot["score"]))
        approval = self.request(
            "POST",
            f"/runs/{rid}/approve",
            {
                "snapshot_id": snapshot["id"],
                "snapshot_hash": snapshot["hash"],
                "reason": "OFFLINE FIXTURE named owner approval of this exact content and assessment",
                "evidence": "Scripted decision by the authenticated LOCAL DEMO owner identity.",
            },
        )
        release_body = {
            "version_id": sub["version_id"],
            "snapshot_id": snapshot["id"],
            "snapshot_hash": snapshot["hash"],
            "approval_id": approval["id"],
        }
        released = self.request("POST", f"/assets/{sub['asset_id']}/release", release_body)
        print("Complete fixture scored 100 and released the exact approved version locally.", flush=True)
        change = self.request(
            "POST",
            f"/resources/source/{source['id']}/revoke",
            {
                "reason": "OFFLINE FIXTURE source authority withdrawn",
                "evidence": "Synthetic source-change test",
            },
            who="admin",
        )
        stale_release = self.request(
            "POST", f"/assets/{sub['asset_id']}/release", release_body, expected=(409,)
        )
        asset = self.request("GET", f"/assets/{sub['asset_id']}")
        if asset["released_id"] is not None:
            raise RuntimeError("Source revocation must remove current release eligibility")
        print("Source revocation queued reassessment and made the old approval unusable.", flush=True)
        events = self.request("GET", "/events", who="reviewer")
        if not events["chain_valid"]:
            raise RuntimeError("Audit verification failed")
        return {
            "executed_at": now(),
            "mode": "offline_fixture",
            "transport": "real local HTTP API and separate durable worker process",
            "notice": "Synthetic judgments test workflow and enforcement, not model accuracy or genuine expert approval. Nothing was published externally.",
            "live_provider_verified": False,
            "platform_integration_verified": False,
            "initial_assessment": {
                "index": first_snapshot["score"]["index"],
                "route": first_snapshot["score"]["route"],
                "rubric_coverage": first_snapshot["score"]["rubric_coverage"],
            },
            "premature_approval_error": blocked["error"]["code"],
            "reviewed_score": snapshot["score"],
            "local_release": released,
            "old_approval_rejection": stale_release["error"]["code"],
            "reassessment_ids": change["reassessments"],
            "audit_chain_valid": events["chain_valid"],
            "audit_event_count": len(events["events"]),
            "identifiers": sub,
        }


def run_demo(output, keep=False):
    base = Path("var")
    base.mkdir(exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="fixture-demo-", dir=base)).resolve()
    db = Database(directory / "demo.sqlite3")
    db.migrate()
    cred_path = Path(init_demo(db, directory / "credentials.json"))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {
        **os.environ,
        "CAS_DB": db.path,
        "CAS_MODE": "local",
        "CAS_PROVIDER": "fixture",
        "CAS_ALLOW_EXTERNAL": "false",
        "CAS_PROVIDER_API_KEY": "",
        "CAS_PROVIDER_URL": "",
        "CAS_PROVIDER_MODEL": "",
    }
    processes = []
    try:
        with (directory / "process.log").open("w") as log:
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "assurance.cli", "serve", "--port", str(port)],
                    env=env,
                    stdout=log,
                    stderr=log,
                )
            )
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "assurance.cli", "worker"], env=env, stdout=log, stderr=log
                )
            )
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 20
            while True:
                try:
                    with httpx.Client(timeout=1, trust_env=False) as client:
                        if client.get(url + "/health").status_code == 200:
                            break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline or any(p.poll() is not None for p in processes):
                    raise RuntimeError(
                        "Demo service did not start; inspect " + str(directory / "process.log")
                    )
                time.sleep(0.1)
            example = ExampleClient(url, json.loads(cred_path.read_text()))
            try:
                report = example.execute_fixture_demo()
            finally:
                example.client.close()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2) + "\n")
            print("Demonstration passed. Report: " + str(output.resolve()))
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if not keep:
            import shutil

            shutil.rmtree(directory)
        else:
            print("Local demo database and private development credentials retained at: " + str(directory))
