import copy
import hashlib
import json
import time
from datetime import UTC, datetime

from .checkers import plan_examinations
from .db import audit
from .extraction import extract, normalize_format
from .rubric import CRITERIA, PROFILES, RUBRIC, calculate
from .util import canonical, digest, now, uid


class DomainError(Exception):
    def __init__(self, code, message, status=409, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details
        super().__init__(message)


def reject(code, message, status=409, details=None):
    raise DomainError(code, message, status, details)


def get(c, table, tenant, record_id):
    row = c.execute(f"SELECT * FROM {table} WHERE id=? AND tenant_id=?", (record_id, tenant)).fetchone()
    if not row:
        reject("NOT_FOUND", "Record not found in your tenant.", 404)
    return dict(row)


def authorize(c, p, role=None, human=False):
    row = c.execute(
        "SELECT * FROM principals WHERE id=? AND tenant_id=? AND active=1", (p.id, p.tenant_id)
    ).fetchone()
    if not row:
        reject("UNAUTHENTICATED", "Credential is inactive.", 401)
    roles = json.loads(row["roles"])
    if role and role not in roles:
        reject("ROLE_REQUIRED", "This operation requires the " + role + " role.", 403)
    if human and not row["human"]:
        reject("HUMAN_REQUIRED", "This decision requires an authenticated human.", 403)


def owner_only(c, p, brief):
    authorize(c, p, "approver", True)
    if p.id != brief["owner_id"]:
        reject("OWNER_REQUIRED", "Only the named content owner can make this decision.", 403)


def resource_valid(resource, status, brief, use="assessment", at=None):
    p = resource["payload"]
    scope = p["scope"]
    at = at or datetime.now(UTC)
    if status != "approved":
        return False, "SOURCE_OR_POLICY_NOT_APPROVED"
    if p["origin"] == "generated":
        return False, "GENERATED_CONTENT_IS_NOT_AUTHORITY"
    if at < datetime.fromisoformat(scope["effective_from"]) or (
        scope["effective_until"] and at >= datetime.fromisoformat(scope["effective_until"])
    ):
        return False, "OUTSIDE_EFFECTIVE_DATES"
    if (
        brief["market"] not in scope["markets"]
        or brief["language"] not in scope["languages"]
        or brief["profile"] not in scope["profiles"]
        or use not in scope["uses"]
    ):
        return False, "OUTSIDE_APPROVED_SCOPE"
    return True, "APPROVED_CURRENT_APPLICABLE"


def head_resource(c, tenant, kind, key, brief=None, use="assessment"):
    row = c.execute(
        "SELECT r.*,h.status,h.revision,h.approved_by,h.approval_evidence FROM resource_heads h JOIN resources r ON r.id=h.resource_id WHERE h.tenant_id=? AND h.kind=? AND h.resource_key=?",
        (tenant, kind, key),
    ).fetchone()
    if not row:
        reject("RESOURCE_NOT_FOUND", "A required source or policy is not registered in your tenant.", 404)
    out = dict(row)
    out["payload"] = json.loads(out["payload"])
    if brief:
        out["valid"], out["validity_reason"] = resource_valid(out, out["status"], brief, use)
    return out


def run_context(c, run):
    config = json.loads(run["config"])
    version = get(c, "versions", run["tenant_id"], run["version_id"])
    payload = json.loads(version["payload"])
    return {
        "run_id": run["id"],
        "version_id": version["id"],
        "brief_id": version["brief_id"],
        "brief": config["brief"],
        "extraction": payload["extraction"],
        "plan": json.loads(run["plan"]),
        "sources": config["sources"],
        "policy": config["policy"],
        "external_required": config["evaluators"]["provider"] == "chat",
    }


def fresh(c, run, settings):
    asset = get(c, "assets", run["tenant_id"], run["asset_id"])
    if (
        asset["latest_version_id"] != run["version_id"]
        or asset["current_run_id"] != run["id"]
        or run["state"] == "stale"
    ):
        return False, "SUPERSEDED_CONTENT_OR_ASSESSMENT"
    cfg = json.loads(run["config"])
    if cfg["rubric_hash"] != digest(RUBRIC) or cfg["evaluators"] != settings.evaluator():
        return False, "EVALUATOR_OR_RUBRIC_CHANGED"
    for dep in c.execute("SELECT * FROM dependencies WHERE run_id=?", (run["id"],)):
        current = head_resource(c, run["tenant_id"], dep["kind"], dep["resource_key"], cfg["brief"])
        if current["id"] != dep["resource_id"] or current["revision"] != dep["revision"]:
            return False, "DEPENDENCY_CHANGED"
        # Invalid candidate sources are assessed as failures, rather than forever
        # rescheduling. Previously valid evidence that expires makes the run stale.
        original = next((r for r in cfg["sources"] + [cfg["policy"]] if r["id"] == dep["resource_id"]), None)
        if original and original["valid"] and not current["valid"]:
            return False, "DEPENDENCY_EXPIRED_OR_INAPPLICABLE"
    return True, None


def require_current(c, run, settings):
    valid, reason = fresh(c, run, settings)
    if not valid:
        reject(
            "STALE_ASSESSMENT",
            "This assessment is no longer current; reassessment is required.",
            details={"reason": reason},
        )


def schedule(c, tenant, asset, version, settings, actor):
    old = asset.get("current_run_id")
    if old:
        c.execute("UPDATE runs SET state='stale' WHERE id=?", (old,))
        c.execute(
            "UPDATE jobs SET state='cancelled',lease_token=NULL,lease_until=NULL WHERE run_id=? AND state NOT IN ('done','failed')",
            (old,),
        )
        audit(c, tenant, actor, "assessment.invalidated", old, {"version_id": version["id"]})
    briefrow = get(c, "briefs", tenant, version["brief_id"])
    brief = json.loads(briefrow["payload"])
    sources = [head_resource(c, tenant, "source", key, brief) for key in brief["source_keys"]]
    policy = head_resource(c, tenant, "policy", brief["policy_key"], brief)
    payload = json.loads(version["payload"])
    plan = plan_examinations(payload["extraction"], brief, payload.get("derived_from_version_id"))
    cfg = {
        "brief": brief,
        "brief_hash": briefrow["hash"],
        "sources": sources,
        "policy": policy,
        "rubric": RUBRIC,
        "rubric_hash": digest(RUBRIC),
        "evaluators": settings.evaluator(),
        "content_hash": version["hash"],
        "scope_convention": "inventory-v1",
    }
    rid, jid = uid(), uid()
    c.execute(
        "INSERT INTO runs(id,tenant_id,asset_id,version_id,plan,plan_hash,config,config_hash,state,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            rid,
            tenant,
            asset["id"],
            version["id"],
            canonical(plan),
            digest(plan),
            canonical(cfg),
            digest(cfg),
            "awaiting_scope",
            now(),
        ),
    )
    for r in sources + [policy]:
        c.execute(
            "INSERT INTO dependencies VALUES(?,?,?,?,?,?)",
            (rid, tenant, r["kind"], r["resource_key"], r["id"], r["revision"]),
        )
    c.execute(
        "INSERT INTO jobs(id,tenant_id,run_id,state,available_at,created_at) VALUES(?,?,?,?,?,?)",
        (jid, tenant, rid, "queued", time.time(), now()),
    )
    c.execute("UPDATE assets SET current_run_id=?,released_id=NULL WHERE id=?", (rid, asset["id"]))
    audit(
        c,
        tenant,
        actor,
        "assessment.scheduled",
        rid,
        {"version_id": version["id"], "job_id": jid, "plan_hash": digest(plan), "config_hash": digest(cfg)},
    )
    return {
        "asset_id": asset["id"],
        "version_id": version["id"],
        "run_id": rid,
        "job_id": jid,
        "state": "awaiting_scope",
        "plan_hash": digest(plan),
    }


def invalidate_dependents(c, tenant, kind, key, settings, actor):
    rows = c.execute(
        "SELECT DISTINCT a.* FROM assets a JOIN dependencies d ON d.run_id=a.current_run_id WHERE d.tenant_id=? AND d.kind=? AND d.resource_key=?",
        (tenant, kind, key),
    ).fetchall()
    ids = []
    for row in rows:
        asset = dict(row)
        v = get(c, "versions", tenant, asset["latest_version_id"])
        ids.append(schedule(c, tenant, asset, v, settings, actor)["run_id"])
    return ids


def add_decision(c, p, run_id, kind, payload):
    did = uid()
    c.execute(
        "INSERT INTO decisions VALUES(?,?,?,?,?,?,?)",
        (did, p.tenant_id, run_id, kind, canonical(payload), p.id, now()),
    )
    audit(
        c,
        p.tenant_id,
        p.id,
        "decision." + kind,
        run_id,
        {"decision_id": did, "payload_hash": digest(payload)},
    )
    return did


def assemble_snapshot(c, run):
    context = run_context(c, run)
    brief = context["brief"]
    row = c.execute("SELECT * FROM machine_results WHERE run_id=?", (run["id"],)).fetchone()
    if not row:
        reject("ASSESSMENT_UNFINISHED", "The worker has not completed this assessment.")
    machine = json.loads(row["payload"])
    checks = copy.deepcopy(machine["checks"])
    criteria = {
        key: {"applicable": True, "rating": None, "method": None, "method_version": None, "evidence": []}
        for key in CRITERIA
    }
    gates = {}
    findings = {}
    decisions = c.execute("SELECT * FROM decisions WHERE run_id=? ORDER BY rowid", (run["id"],)).fetchall()
    inventory_complete = False
    specialist = False
    specialist_decision = None
    decision_ids = []
    for e in context["plan"]:
        check = checks[e["id"]]
        if check["outcome"] == "fail":
            fid = digest({"run": run["id"], "check": e["id"]})[:32]
            findings[fid] = {
                "id": fid,
                "primary_criterion": e["criterion"],
                "severity": "major",
                "state": "open",
                "item_id": e["item_id"],
                "content_locator": check["content_locator"],
                "description": check["reason"],
                "correction": check.get("suggested_correction")
                or "Review the qualification and source evidence, then revise or adjudicate with evidence.",
                "evidence": check["evidence"],
                "origin": "model_suggestion" if e["mode"] == "model" else "deterministic",
                "examination_id": e["id"],
                "history": [],
            }
    # Only bounded, mechanically established rubric judgments are automatic.
    source_check = checks["source-status"]
    if source_check["outcome"] in {"pass", "fail"} and "E1" not in brief["exclusions"]:
        criteria["E1"] = {
            "applicable": True,
            "rating": 4 if source_check["outcome"] == "pass" else 0,
            "method": "automated",
            "method_version": "deterministic-1",
            "evidence": source_check["evidence"],
        }
    if "G4" not in brief["exclusions"]:
        criteria["G4"] = {
            "applicable": True,
            "rating": 4,
            "method": "automated",
            "method_version": "provenance-1",
            "evidence": [
                {
                    "run_id": run["id"],
                    "config_hash": run["config_hash"],
                    "content_hash": json.loads(run["config"])["content_hash"],
                }
            ],
        }
    for d in decisions:
        p = json.loads(d["payload"])
        decision_ids.append(d["id"])
        if d["kind"] == "scope":
            inventory_complete = p["inventory_complete"]
            gates["R1"] = {"state": "pass", "evidence": [d["id"]]}
            for key, ex in brief["exclusions"].items():
                criteria[key] = {
                    "applicable": False,
                    "exclusion": {**ex, "approved_by": d["actor_id"], "evidence": [d["id"], ex["evidence"]]},
                }
        elif d["kind"] == "review":
            specialist = False
            for cr in p["criteria"]:
                criteria[cr["criterion"]] = {
                    "applicable": True,
                    "rating": cr["rating"],
                    "method": "human",
                    "method_version": cr["method_version"],
                    "evidence": cr["evidence_ids"],
                    "reason": cr["reason"],
                    "reviewer": d["actor_id"],
                }
            for ex in p["examinations"]:
                old = checks[ex["examination_id"]]
                checks[ex["examination_id"]] = {
                    **old,
                    "outcome": ex["outcome"],
                    "evidence": ex["evidence_ids"],
                    "method": "human",
                    "method_version": "human-review-1",
                    "reason": ex["reason"],
                    "decision_id": d["id"],
                }
            for gate in p["gates"]:
                gates[gate["gate"]] = {
                    "state": gate["state"],
                    "evidence": gate["evidence_ids"],
                    "reason": gate["reason"],
                    "scope": gate["scope"],
                    "approved_by": d["actor_id"],
                }
            for finding in p["findings"]:
                findings[finding["id"]] = {
                    **finding,
                    "state": "open",
                    "origin": "human",
                    "evidence": finding["evidence_ids"],
                    "history": [],
                }
            for resolution in p["resolutions"]:
                f = findings[resolution["finding_id"]]
                f["state"] = resolution["disposition"]
                f["history"].append({**resolution, "reviewer": d["actor_id"], "decision_id": d["id"]})
        elif d["kind"] == "specialist":
            specialist = True
            specialist_decision = d["id"]
    for exam in context["plan"]:
        if exam["mode"] == "specialist":
            checks[exam["id"]] = {
                **checks[exam["id"]],
                "outcome": "pass" if specialist else "unknown",
                "method": "human",
                "method_version": "specialist-review-1",
                "evidence": [specialist_decision] if specialist else [],
                "reason": "Declared specialist requirement reviewed."
                if specialist
                else "Authenticated specialist examination required.",
            }
    for key, cr in criteria.items():
        eid = "criterion:" + key
        if eid in checks and cr.get("rating") is not None:
            checks[eid] = {
                **checks[eid],
                "outcome": "pass" if cr["rating"] >= 3 else "fail",
                "evidence": cr["evidence"],
                "method": cr["method"],
                "method_version": cr["method_version"],
                "reason": "Criterion judgment recorded with evidence.",
            }
    planned = len(context["plan"])
    completed = sum(ch["outcome"] in {"pass", "fail"} and bool(ch["evidence"]) for ch in checks.values())
    critical = [e for e in context["plan"] if e["critical"]]
    verified = sum(
        checks[e["id"]]["outcome"] == "pass" and bool(checks[e["id"]]["evidence"]) for e in critical
    )
    # A failed examination cannot disappear by entering a high criterion rating.
    unresolved_failures = [ch["examination_id"] for ch in checks.values() if ch["outcome"] == "fail"]
    format_supported = context["extraction"]["supported"] and all(
        m in {"text", "visual", "rendered"} for m in brief["declared_modalities"]
    )
    score = calculate(
        criteria,
        brief["profile"],
        brief["tier"],
        gates=gates,
        findings=list(findings.values()),
        planned=planned,
        completed=completed,
        critical_planned=len(critical),
        critical_verified=verified,
        inventory_complete=inventory_complete,
        setup_valid=format_supported,
        specialist=specialist,
    )
    if (
        brief["specialist_requirements"]
        and not specialist
        and "SPECIALIST_REVIEW_REQUIRED" not in score["reasons"]
    ):
        score["reasons"].append("SPECIALIST_REVIEW_REQUIRED")
    if any(not r["valid"] for r in context["sources"] + [context["policy"]]):
        score.update(
            readiness=False,
            release_eligible=False,
            route="hold_for_correction",
            explanation="The governed source or policy context is not approved and applicable.",
        )
        score["reasons"].append("GOVERNED_CONTEXT_INVALID")
    # All applicable required checks must have a result, even if a numerical coverage
    # threshold alone would permit skipping a small number of checks.
    unknown_checks = [e["id"] for e in context["plan"] if checks[e["id"]]["outcome"] == "unknown"]
    if unknown_checks and score["readiness"]:
        score.update(
            readiness=False,
            release_eligible=False,
            route="complete_assessment",
            explanation="Planned checks remain unassessed.",
        )
    if unknown_checks:
        score["reasons"].append("REQUIRED_CHECKS_INCOMPLETE")
    if unresolved_failures and score["readiness"]:
        score.update(
            readiness=False,
            release_eligible=False,
            route="revise_major_issues",
            explanation="Failed examinations require verified resolution.",
        )
    if unresolved_failures:
        score["reasons"].append("FAILED_EXAMINATIONS")
    if not format_supported:
        score["reasons"].append("FORMAT_OR_EXTRACTION_INCOMPLETE")
    modalities = {}
    for modality in {e["modality"] for e in context["plan"]}:
        es = [e for e in context["plan"] if e["modality"] == modality]
        modalities[modality] = {
            "planned": len(es),
            "completed": sum(
                checks[e["id"]]["outcome"] in {"pass", "fail"} and bool(checks[e["id"]]["evidence"])
                for e in es
            ),
            "critical_planned": sum(e["critical"] for e in es),
            "critical_verified": sum(
                e["critical"] and checks[e["id"]]["outcome"] == "pass" and bool(checks[e["id"]]["evidence"])
                for e in es
            ),
        }
    payload = {
        "run_id": run["id"],
        "version_id": run["version_id"],
        "content_hash": json.loads(run["config"])["content_hash"],
        "config_hash": run["config_hash"],
        "plan_hash": run["plan_hash"],
        "machine_hash": row["hash"],
        "decision_ids": decision_ids,
        "criteria": criteria,
        "gates": gates,
        "checks": checks,
        "findings": list(findings.values()),
        "score": score,
        "coverage_by_modality": modalities,
        "provider_label": machine["provider_label"],
        "provider_error": machine["provider_error"],
        "fixture": machine["fixture"],
        "specialist_reviewed": specialist,
    }
    sid, stamp = uid(), now()
    c.execute(
        "INSERT INTO snapshots VALUES(?,?,?,?,?,?)",
        (sid, run["tenant_id"], run["id"], canonical(payload), digest(payload), stamp),
    )
    c.execute("UPDATE runs SET head_snapshot_id=? WHERE id=?", (sid, run["id"]))
    c.execute(
        "UPDATE assets SET released_id=NULL WHERE id=? AND current_run_id=?", (run["asset_id"], run["id"])
    )
    audit(
        c,
        run["tenant_id"],
        "system",
        "assessment.snapshot_created",
        run["id"],
        {"snapshot_id": sid, "hash": digest(payload), "route": score["route"]},
    )
    return {"id": sid, "hash": digest(payload), **payload}


class Service:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def put_resource(self, p, kind, data):
        if kind not in {"source", "policy"}:
            reject("INVALID_RESOURCE_KIND", "Use source or policy.", 422)
        payload = data.model_dump(mode="json")
        with self.db.write() as c:
            authorize(c, p, kind + "_admin", True)
            old = c.execute(
                "SELECT * FROM resource_heads WHERE tenant_id=? AND kind=? AND resource_key=?",
                (p.tenant_id, kind, data.key),
            ).fetchone()
            version = c.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM resources WHERE tenant_id=? AND kind=? AND resource_key=?",
                (p.tenant_id, kind, data.key),
            ).fetchone()[0]
            rid = uid()
            c.execute(
                "INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?)",
                (rid, p.tenant_id, kind, data.key, version, canonical(payload), digest(payload), p.id, now()),
            )
            c.execute(
                "INSERT INTO resource_heads VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,kind,resource_key) DO UPDATE SET resource_id=excluded.resource_id,status=excluded.status,revision=excluded.revision,approved_by=NULL,approval_evidence=NULL",
                (
                    p.tenant_id,
                    kind,
                    data.key,
                    rid,
                    "candidate",
                    old["revision"] + 1 if old else 1,
                    None,
                    None,
                ),
            )
            runs = invalidate_dependents(c, p.tenant_id, kind, data.key, self.settings, p.id)
            audit(
                c,
                p.tenant_id,
                p.id,
                kind + ".candidate_created",
                rid,
                {"key": data.key, "version": version, "hash": digest(payload), "reassessments": runs},
            )
            return {
                "id": rid,
                "key": data.key,
                "version": version,
                "status": "candidate",
                "reassessments": runs,
            }

    def resource_decision(self, p, kind, resource_id, data, approve):
        if kind not in {"source", "policy"}:
            reject("INVALID_RESOURCE_KIND", "Use source or policy.", 422)
        with self.db.write() as c:
            authorize(c, p, kind + "_admin", True)
            resource = get(c, "resources", p.tenant_id, resource_id)
            if resource["kind"] != kind:
                reject("NOT_FOUND", "Resource not found.", 404)
            head = head_resource(c, p.tenant_id, kind, resource["resource_key"])
            if head["id"] != resource_id:
                reject("SUPERSEDED_RESOURCE", "Only the current resource version can be approved or revoked.")
            if approve and json.loads(resource["payload"])["origin"] == "generated":
                reject(
                    "GENERATED_CONTENT_IS_NOT_AUTHORITY",
                    "A generated output cannot establish its own factual authority. Register independent evidence.",
                )
            c.execute(
                "UPDATE resource_heads SET status=?,revision=revision+1,approved_by=?,approval_evidence=? WHERE tenant_id=? AND kind=? AND resource_key=?",
                (
                    "approved" if approve else "revoked",
                    p.id,
                    canonical(data.model_dump()),
                    p.tenant_id,
                    kind,
                    resource["resource_key"],
                ),
            )
            runs = invalidate_dependents(c, p.tenant_id, kind, resource["resource_key"], self.settings, p.id)
            audit(
                c,
                p.tenant_id,
                p.id,
                kind + (".approved" if approve else ".revoked"),
                resource_id,
                {**data.model_dump(), "reassessments": runs},
            )
            return {"id": resource_id, "status": "approved" if approve else "revoked", "reassessments": runs}

    def create_brief(self, p, data):
        brief = data.model_dump(mode="json")
        if data.profile not in PROFILES:
            reject("INVALID_PROFILE", "Choose one of the nine rubric profiles.", 422)
        if data.tier == "High" and not data.specialist_requirements:
            reject(
                "SPECIALIST_REQUIREMENTS_MISSING",
                "High consequence briefs must define specialist examination requirements.",
                422,
            )
        if len(data.source_keys) != len(set(data.source_keys)):
            reject("DUPLICATE_SOURCE", "Source keys must be unique.", 422)
        if any(
            not path.startswith("/")
            for path in data.required_fields + [v.path for v in data.structured_values]
        ):
            reject(
                "INVALID_JSON_POINTER",
                "Structured field paths must use RFC 6901 pointers beginning with /.",
                422,
            )
        with self.db.write() as c:
            owner_only(c, p, brief)
            for key in data.source_keys:
                head_resource(c, p.tenant_id, "source", key)
            head_resource(c, p.tenant_id, "policy", data.policy_key)
            bid = uid()
            c.execute(
                "INSERT INTO briefs VALUES(?,?,?,?,?,?)",
                (bid, p.tenant_id, canonical(brief), digest(brief), p.id, now()),
            )
            audit(c, p.tenant_id, p.id, "brief.approved", bid, {"hash": digest(brief)})
            return {"id": bid, "hash": digest(brief), "brief": brief}

    def submit(self, p, data, idem_key, raw=None):
        if not idem_key or len(idem_key) > 150:
            reject("IDEMPOTENCY_KEY_REQUIRED", "Supply an Idempotency-Key of 1 to 150 characters.", 422)
        body = data.model_dump(mode="json")
        raw = (
            raw
            if raw is not None
            else (
                data.content.encode() if isinstance(data.content, str) else canonical(data.content).encode()
            )
        )
        if len(raw) > self.settings.max_bytes:
            reject("UPLOAD_TOO_LARGE", "The pilot intake limit is 5 MB.", 413)
        raw_hash = hashlib.sha256(raw).hexdigest()
        request_hash = digest({"request": body, "raw_hash": raw_hash})
        with self.db.write() as c:
            authorize(c, p, "submitter")
            previous = c.execute(
                "SELECT * FROM idempotency WHERE tenant_id=? AND actor_id=? AND operation='submit' AND idem_key=?",
                (p.tenant_id, p.id, idem_key),
            ).fetchone()
            if previous:
                if previous["request_hash"] != request_hash:
                    reject("IDEMPOTENCY_CONFLICT", "This key was already used for different content.")
                return json.loads(previous["response"])
            briefrow = get(c, "briefs", p.tenant_id, data.brief_id)
            brief = json.loads(briefrow["payload"])
            if data.derived_from_version_id:
                get(c, "versions", p.tenant_id, data.derived_from_version_id)
                if set(brief["exclusions"]) & {"M4", "B2", "B3"}:
                    reject(
                        "EXCLUSION_HIDES_DERIVATION",
                        "Source-to-target meaning, terminology and market checks must remain applicable to derivatives.",
                        422,
                    )
            if data.origin in {"translation", "adaptation"} and not data.derived_from_version_id:
                reject(
                    "DERIVATION_REQUIRED",
                    "Adaptations and translations must reference their source version.",
                    422,
                )
            if data.asset_id:
                asset = get(c, "assets", p.tenant_id, data.asset_id)
                if data.expected_version_id != asset["latest_version_id"]:
                    reject(
                        "VERSION_CONFLICT", "Supply the current expected_version_id before saving an edit."
                    )
            else:
                if data.expected_version_id:
                    reject("INVALID_EXPECTED_VERSION", "A new asset has no prior version.", 422)
                aid = uid()
                c.execute(
                    "INSERT INTO assets(id,tenant_id,title,created_at) VALUES(?,?,?,?)",
                    (aid, p.tenant_id, data.title, now()),
                )
                asset = get(c, "assets", p.tenant_id, aid)
            x = extract(raw, data.format)
            if len(plan_examinations(x, brief, data.derived_from_version_id)) > 3000:
                reject(
                    "INVENTORY_LIMIT", "This pilot accepts up to 3,000 planned examinations per version.", 413
                )
            # Unsupported content cannot be hidden by a criterion exclusion.
            if (x["gaps"] or any(m != "text" for m in brief["declared_modalities"])) and set(
                brief["exclusions"]
            ) & {"M4", "U3", "U4"}:
                reject(
                    "EXCLUSION_HIDES_MODALITY",
                    "M4, U3 and U4 cannot be excluded when format or modality examinations remain.",
                    422,
                )
            vid = uid()
            ordinal = c.execute(
                "SELECT COUNT(*)+1 FROM versions WHERE asset_id=?", (asset["id"],)
            ).fetchone()[0]
            payload = {
                "title": data.title,
                "format": normalize_format(data.format),
                "origin": data.origin,
                "derived_from_version_id": data.derived_from_version_id,
                "extraction": x,
                "previous_version_id": asset["latest_version_id"],
            }
            c.execute(
                "INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    vid,
                    p.tenant_id,
                    asset["id"],
                    ordinal,
                    data.brief_id,
                    canonical(payload),
                    raw,
                    raw_hash,
                    p.id,
                    now(),
                ),
            )
            c.execute("UPDATE assets SET latest_version_id=? WHERE id=?", (vid, asset["id"]))
            version = get(c, "versions", p.tenant_id, vid)
            result = schedule(c, p.tenant_id, asset, version, self.settings, p.id)
            c.execute(
                "INSERT INTO idempotency VALUES(?,?,?,?,?,?)",
                (p.tenant_id, p.id, "submit", idem_key, request_hash, canonical(result)),
            )
            audit(
                c,
                p.tenant_id,
                p.id,
                "content.version_saved",
                vid,
                {"asset_id": asset["id"], "hash": raw_hash, "ordinal": ordinal, "origin": data.origin},
            )
            return result

    def scope(self, p, run_id, data):
        with self.db.write() as c:
            run = get(c, "runs", p.tenant_id, run_id)
            require_current(c, run, self.settings)
            context = run_context(c, run)
            owner_only(c, p, context["brief"])
            if run["state"] != "awaiting_scope" or run["plan_hash"] != data.plan_hash:
                reject("SCOPE_CONFLICT", "Approve the exact unexecuted examination plan.")
            did = add_decision(c, p, run_id, "scope", data.model_dump())
            c.execute("UPDATE runs SET state='queued' WHERE id=?", (run_id,))
            return {"decision_id": did, "run_id": run_id, "state": "queued"}

    def add_evidence(self, p, run_id, data):
        payload = data.model_dump()
        with self.db.write() as c:
            authorize(c, p, "reviewer", True)
            run = get(c, "runs", p.tenant_id, run_id)
            require_current(c, run, self.settings)
            context = run_context(c, run)
            if data.kind in {"source", "content"}:
                if data.kind == "source":
                    source = next(
                        (s for s in context["sources"] if s["id"] == data.source_id and s["valid"]), None
                    )
                    if not source:
                        reject(
                            "INVALID_EVIDENCE_SOURCE",
                            "Evidence must cite a permitted source in this assessment snapshot.",
                            422,
                        )
                    text = source["payload"]["text"]
                    payload["source_hash"] = source["hash"]
                else:
                    item = next((i for i in context["extraction"]["items"] if i["id"] == data.item_id), None)
                    if not item:
                        reject("INVALID_CONTENT_LOCATOR", "Content item is not in this assessment.", 422)
                    text = item["text"]
                    payload["content_locator"] = item["locator"]
                if (
                    data.start is None
                    or data.end is None
                    or not (0 <= data.start < data.end <= len(text))
                    or text[data.start : data.end] != data.quote
                ):
                    reject(
                        "INVALID_QUOTE_LOCATOR",
                        "Quote must match exact text and Unicode offsets, end exclusive.",
                        422,
                    )
            eid = uid()
            c.execute(
                "INSERT INTO evidence VALUES(?,?,?,?,?,?,?)",
                (eid, p.tenant_id, run_id, canonical(payload), digest(payload), p.id, now()),
            )
            audit(
                c,
                p.tenant_id,
                p.id,
                "review.evidence_added",
                run_id,
                {"evidence_id": eid, "hash": digest(payload)},
            )
            return {"id": eid, "hash": digest(payload)}

    def review(self, p, run_id, data):
        payload = data.model_dump()
        with self.db.write() as c:
            authorize(c, p, "reviewer", True)
            run = get(c, "runs", p.tenant_id, run_id)
            require_current(c, run, self.settings)
            if run["state"] != "completed" or run["head_snapshot_id"] != data.expected_snapshot_id:
                reject("SNAPSHOT_CONFLICT", "Review the current completed assessment snapshot.")
            current = json.loads(get(c, "snapshots", p.tenant_id, run["head_snapshot_id"])["payload"])
            context = run_context(c, run)
            plans = {e["id"]: e for e in context["plan"]}
            findings = {f["id"]: f for f in current["findings"]}
            if not any(payload[k] for k in ["criteria", "examinations", "gates", "findings", "resolutions"]):
                reject("EMPTY_REVIEW", "Record at least one review decision.", 422)
            for collection, key in [
                ("criteria", "criterion"),
                ("examinations", "examination_id"),
                ("gates", "gate"),
                ("resolutions", "finding_id"),
            ]:
                values = [d[key] for d in payload[collection]]
                if len(values) != len(set(values)):
                    reject(
                        "DUPLICATE_DECISION", "A review cannot contain conflicting duplicate decisions.", 422
                    )
            for collection in ["criteria", "examinations", "gates", "findings", "resolutions"]:
                for decision in payload[collection]:
                    for eid in decision["evidence_ids"]:
                        ev = get(c, "evidence", p.tenant_id, eid)
                        if ev["run_id"] != run_id:
                            reject(
                                "EVIDENCE_SCOPE_MISMATCH",
                                "Review evidence must belong to this exact assessment.",
                                422,
                            )
            for cr in payload["criteria"]:
                if cr["criterion"] in context["brief"]["exclusions"]:
                    reject(
                        "EXCLUDED_CRITERION",
                        "Changing applicability requires a new approved brief and content version.",
                        422,
                    )
                if cr["criterion"] in {"E2", "E3", "M1", "M2"} and cr["rating"] >= 3:
                    evidence_kinds = [
                        json.loads(get(c, "evidence", p.tenant_id, eid)["payload"])["kind"]
                        for eid in cr["evidence_ids"]
                    ]
                    if "source" not in evidence_kinds:
                        reject(
                            "SOURCE_EVIDENCE_REQUIRED",
                            "Passing factual and traceability judgments require an exact permitted source passage alongside review evidence.",
                            422,
                        )
            for ex in payload["examinations"]:
                if ex["examination_id"] not in plans or ex["examination_id"].startswith("criterion:"):
                    reject(
                        "INVALID_EXAMINATION",
                        "Use a planned examination; criterion examinations follow their criterion rating.",
                        422,
                    )
                if plans[ex["examination_id"]]["mode"] == "specialist":
                    reject(
                        "SPECIALIST_ENDPOINT_REQUIRED",
                        "Use the authenticated specialist operation for declared specialist requirements.",
                        422,
                    )
            for gate in payload["gates"]:
                if gate["state"] == "na":
                    owner_only(c, p, context["brief"])
                    if not gate["scope"]:
                        reject(
                            "EXCLUSION_SCOPE_REQUIRED",
                            "Gate N/A requires a scoped owner-authorised exclusion.",
                            422,
                        )
            valid_items = (
                {"document"}
                | {i["id"] for i in context["extraction"]["items"]}
                | {e["item_id"] for e in context["plan"]}
            )
            for f in payload["findings"]:
                if f["item_id"] not in valid_items:
                    reject(
                        "INVALID_CONTENT_LOCATOR",
                        "Finding must identify an item in the planned inventory.",
                        422,
                    )
                if f["related_finding_id"] and (
                    f["related_finding_id"] not in findings or not f["distinct_effect"]
                ):
                    reject(
                        "DISTINCT_EFFECT_REQUIRED",
                        "A related defect needs a valid original finding and documented distinct effect.",
                        422,
                    )
                f["id"] = uid()
            for resolution in payload["resolutions"]:
                f = findings.get(resolution["finding_id"])
                if not f or f["state"] != "open":
                    reject(
                        "INVALID_FINDING_RESOLUTION",
                        "Only an open finding in this snapshot can be resolved.",
                        422,
                    )
                if f["severity"] == "critical":
                    authorize(c, p, "specialist", True)
            did = add_decision(c, p, run_id, "review", payload)
            result = assemble_snapshot(c, run)
            return {"decision_id": did, "snapshot": result}

    def specialist(self, p, run_id, data):
        with self.db.write() as c:
            authorize(c, p, "specialist", True)
            run, snapshot = self._exact_snapshot(c, p, run_id, data.snapshot_id, data.snapshot_hash)
            did = add_decision(
                c,
                p,
                run_id,
                "specialist",
                {
                    **data.model_dump(),
                    "requirements": json.loads(run["config"])["brief"]["specialist_requirements"],
                },
            )
            return {"decision_id": did, "snapshot": assemble_snapshot(c, run)}

    def _exact_snapshot(self, c, p, run_id, snapshot_id, snapshot_hash):
        run = get(c, "runs", p.tenant_id, run_id)
        require_current(c, run, self.settings)
        if run["state"] != "completed" or run["head_snapshot_id"] != snapshot_id:
            reject("SNAPSHOT_CONFLICT", "The requested snapshot is not the current completed assessment.")
        snapshot = get(c, "snapshots", p.tenant_id, snapshot_id)
        if snapshot["run_id"] != run_id or snapshot["hash"] != snapshot_hash:
            reject("SNAPSHOT_HASH_MISMATCH", "Approval or release must identify the exact snapshot hash.")
        return run, snapshot

    def approve(self, p, run_id, data):
        with self.db.write() as c:
            run, snapshot = self._exact_snapshot(c, p, run_id, data.snapshot_id, data.snapshot_hash)
            owner_only(c, p, json.loads(run["config"])["brief"])
            payload = json.loads(snapshot["payload"])
            if not payload["score"]["readiness"]:
                reject(
                    "NOT_READY_FOR_APPROVAL",
                    "Calculated readiness is incomplete; approval cannot change the result.",
                    details=payload["score"],
                )
            aid = uid()
            record = {**data.model_dump(), "owner_name": p.name, "local_demo_identity": p.local_only}
            c.execute(
                "INSERT INTO approvals VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    aid,
                    p.tenant_id,
                    run_id,
                    run["version_id"],
                    data.snapshot_id,
                    data.snapshot_hash,
                    p.id,
                    canonical(record),
                    now(),
                ),
            )
            audit(
                c,
                p.tenant_id,
                p.id,
                "release.owner_approved",
                run_id,
                {
                    "approval_id": aid,
                    "snapshot_id": data.snapshot_id,
                    "snapshot_hash": data.snapshot_hash,
                    "version_id": run["version_id"],
                },
            )
            return {
                "id": aid,
                "version_id": run["version_id"],
                "snapshot_id": data.snapshot_id,
                "owner_id": p.id,
                "owner_name": p.name,
            }

    def release(self, p, asset_id, data):
        with self.db.write() as c:
            authorize(c, p, "approver", True)
            asset = get(c, "assets", p.tenant_id, asset_id)
            if not asset["current_run_id"]:
                reject("ASSESSMENT_REQUIRED", "No assessment exists.")
            run, snapshot = self._exact_snapshot(
                c, p, asset["current_run_id"], data.snapshot_id, data.snapshot_hash
            )
            owner_only(c, p, json.loads(run["config"])["brief"])
            if data.version_id != asset["latest_version_id"] or data.version_id != run["version_id"]:
                reject("VERSION_CONFLICT", "Only the exact assessed current version can release.")
            payload = json.loads(snapshot["payload"])
            approval = get(c, "approvals", p.tenant_id, data.approval_id)
            if (
                approval["run_id"] != run["id"]
                or approval["version_id"] != data.version_id
                or approval["snapshot_id"] != data.snapshot_id
                or approval["snapshot_hash"] != data.snapshot_hash
                or approval["actor_id"] != p.id
            ):
                reject(
                    "APPROVAL_MISMATCH", "Owner approval does not apply to this exact version and snapshot."
                )
            if not payload["score"]["readiness"]:
                reject(
                    "RELEASE_BLOCKED",
                    "The calculated assessment does not permit release.",
                    details=payload["score"],
                )
            release_at = now()
            for resource in json.loads(run["config"])["sources"] + [json.loads(run["config"])["policy"]]:
                ok, reason = resource_valid(
                    resource,
                    resource["status"],
                    json.loads(run["config"])["brief"],
                    at=datetime.fromisoformat(release_at),
                )
                if not ok:
                    reject(
                        "DEPENDENCY_INVALID",
                        "Current sources and policies must be approved and applicable.",
                        details={"reason": reason},
                    )
            previous = c.execute("SELECT * FROM releases WHERE approval_id=?", (data.approval_id,)).fetchone()
            if previous:
                return {
                    "id": previous["id"],
                    "version_id": previous["version_id"],
                    "content_hash": payload["content_hash"],
                    "status": "released",
                    "published_externally": False,
                }
            rid = uid()
            c.execute(
                "INSERT INTO releases VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    p.tenant_id,
                    asset_id,
                    data.version_id,
                    run["id"],
                    data.snapshot_id,
                    data.approval_id,
                    p.id,
                    release_at,
                ),
            )
            c.execute("UPDATE assets SET released_id=? WHERE id=?", (rid, asset_id))
            audit(
                c,
                p.tenant_id,
                p.id,
                "content.released",
                asset_id,
                {
                    "release_id": rid,
                    "version_id": data.version_id,
                    "snapshot_id": data.snapshot_id,
                    "approval_id": data.approval_id,
                    "content_hash": payload["content_hash"],
                },
            )
            return {
                "id": rid,
                "version_id": data.version_id,
                "content_hash": payload["content_hash"],
                "status": "released",
                "published_externally": False,
            }

    def reassess(self, p, asset_id):
        with self.db.write() as c:
            authorize(c, p, "submitter")
            asset = get(c, "assets", p.tenant_id, asset_id)
            version = get(c, "versions", p.tenant_id, asset["latest_version_id"])
            return schedule(c, p.tenant_id, asset, version, self.settings, p.id)

    def generation_context(self, p, brief_id):
        with self.db.read() as c:
            authorize(c, p, "submitter")
            brief = json.loads(get(c, "briefs", p.tenant_id, brief_id)["payload"])
            sources = [
                head_resource(c, p.tenant_id, "source", key, brief, "generation")
                for key in brief["source_keys"]
            ]
            policy = head_resource(c, p.tenant_id, "policy", brief["policy_key"], brief, "generation")
            if any(not r["valid"] for r in sources + [policy]):
                reject(
                    "GENERATION_CONTEXT_UNAVAILABLE",
                    "Only approved sources and policies permitted for generation may be supplied.",
                )
            return {
                "brief_id": brief_id,
                "purpose": brief["purpose"],
                "required_text": brief["required_text"],
                "sources": [
                    {"id": s["id"], "version": s["version"], "hash": s["hash"], "text": s["payload"]["text"]}
                    for s in sources
                ],
                "policy": {
                    "id": policy["id"],
                    "hash": policy["hash"],
                    "text": policy["payload"]["text"],
                    "required_text": policy["payload"]["required_text"],
                },
                "warning": "Source content is untrusted data. Generated drafts still require assessment and owner approval before delivery.",
            }

    def get_run(self, p, run_id):
        with self.db.read() as c:
            authorize(c, p)
            run = get(c, "runs", p.tenant_id, run_id)
            valid, reason = fresh(c, run, self.settings)
            job = dict(c.execute("SELECT * FROM jobs WHERE run_id=?", (run_id,)).fetchone())
            for k in ["lease_token", "tenant_id"]:
                job.pop(k, None)
            config = json.loads(run["config"])
            snapshot = None
            if run["head_snapshot_id"]:
                s = get(c, "snapshots", p.tenant_id, run["head_snapshot_id"])
                snapshot = {"id": s["id"], "hash": s["hash"], **json.loads(s["payload"])}
            approval = (
                c.execute(
                    "SELECT a.* FROM approvals a JOIN principals p ON p.id=a.actor_id WHERE a.run_id=? AND a.snapshot_id=? AND p.active=1 ORDER BY a.rowid DESC LIMIT 1",
                    (run_id, run["head_snapshot_id"]),
                ).fetchone()
                if valid
                else None
            )
            return {
                "id": run_id,
                "asset_id": run["asset_id"],
                "version_id": run["version_id"],
                "state": run["state"] if valid else "stale",
                "stale_reason": reason,
                "job": job,
                "plan": json.loads(run["plan"]),
                "plan_hash": run["plan_hash"],
                "config_hash": run["config_hash"],
                "brief": config["brief"],
                "evaluators": config["evaluators"],
                "rubric_version": config["rubric"]["version"],
                "dependencies": [
                    {
                        "id": r["id"],
                        "kind": r["kind"],
                        "key": r["resource_key"],
                        "version": r["version"],
                        "hash": r["hash"],
                        "valid_at_assessment": r["valid"],
                    }
                    for r in config["sources"] + [config["policy"]]
                ],
                "snapshot": snapshot,
                "owner_approval": {
                    "id": approval["id"],
                    "owner_id": approval["actor_id"],
                    "created_at": approval["created_at"],
                }
                if approval
                else None,
                "release_eligible": bool(valid and snapshot and snapshot["score"]["readiness"] and approval),
                "final_gate": "pass" if approval else "unknown",
            }
