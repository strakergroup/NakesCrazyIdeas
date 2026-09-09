"""One scoring implementation shared by the API, worker, and tests.

Fractions preserve exact arithmetic for all release comparisons. Display rounding
is deliberately kept outside the decision path.
"""

import json
from fractions import Fraction
from pathlib import Path

RUBRIC = json.loads((Path(__file__).parent / "config/rubric-1.0.json").read_text())
CRITERIA = {
    r[0]: {
        "dimension": r[1],
        "name": r[2],
        "required": r[3] == "Yes",
        "evidence": r[4],
        "anchors": {"0": r[5], "2": r[6], "4": r[7]},
    }
    for r in RUBRIC["criteria"]
}
DIMENSIONS = [r[0] for r in RUBRIC["dimensions"]]
PROFILES = {r[0]: dict(zip(DIMENSIONS, r[1:])) for r in RUBRIC["profiles"]}
TIERS = {r[0]: r[1:5] for r in RUBRIC["risks"]}
NOTICE = "Provisional, uncalibrated rubric index; not a probability of correctness. Bounds are mathematical, not confidence intervals."


def approved_exclusion(item):
    e = item.get("exclusion") or {}
    return bool(e.get("approved_by") and e.get("scope") and e.get("reason") and e.get("evidence"))


def gate_state(gate, key):
    state = gate.get("state", "unknown")
    if state == "fail":
        return "fail"
    if state == "pass" and gate.get("evidence"):
        return "pass"
    if state == "na" and key not in {"R1", "R7"} and approved_exclusion({"exclusion": gate}):
        return "na"
    return "unknown"


def calculate(
    criteria,
    profile="General",
    tier="Standard",
    *,
    gates=None,
    findings=None,
    planned=None,
    completed=None,
    critical_planned=None,
    critical_verified=None,
    inventory_complete=False,
    setup_valid=True,
    specialist=False,
    owner_approved=False,
):
    gates = gates or {}
    findings = findings or []
    invalid = []
    if profile not in PROFILES:
        invalid.append("INVALID_PROFILE")
    if tier not in TIERS:
        invalid.append("INVALID_TIER")
    if not setup_valid:
        invalid.append("INVALID_SETUP")
    if set(criteria) - set(CRITERIA):
        invalid.append("UNKNOWN_CRITERION")
    for name, value in [
        ("PLANNED", planned),
        ("COMPLETED", completed),
        ("CRITICAL_PLANNED", critical_planned),
        ("CRITICAL_VERIFIED", critical_verified),
    ]:
        if value is not None and (type(value) is not int or value < 0 or (name == "PLANNED" and value == 0)):
            invalid.append("INVALID_" + name)
    counts_valid = all(type(v) is int for v in [planned, completed, critical_planned, critical_verified])
    if counts_valid:
        if (
            completed > planned
            or critical_verified > critical_planned
            or critical_planned > planned
            or critical_verified > completed
        ):
            invalid.append("INVALID_EXAMINATION_COUNTS")
    applicable = {}
    recorded = {}
    for key in CRITERIA:
        item = criteria.get(key, {})
        if item.get("applicable", True) is False:
            if approved_exclusion(item):
                continue
            invalid.append("EXCLUSION_NOT_APPROVED:" + key)
        elif item.get("applicable", True) is not True:
            invalid.append("INVALID_APPLICABILITY:" + key)
        applicable[key] = item
        rating = item.get("rating")
        if rating is not None and (type(rating) is not int or rating not in range(5)):
            invalid.append("INVALID_RATING:" + key)
            continue
        if (
            rating is not None
            and item.get("method") in {"human", "automated", "hybrid"}
            and item.get("method_version")
            and item.get("evidence")
        ):
            recorded[key] = rating
    weights = PROFILES.get(profile, PROFILES["General"])
    active = {d: [k for k in applicable if k.startswith(d)] for d in DIMENSIONS}
    total = sum(weights[d] for d in DIMENSIONS if active[d])
    coverage = Fraction(0)
    lower = Fraction(0)
    dims = {}
    exact_dims = {}
    for d, keys in active.items():
        if not keys:
            dims[d] = {"score": None, "coverage": None, "excluded": True}
            continue
        known = [recorded[k] for k in keys if k in recorded]
        share = Fraction(weights[d], total)
        coverage += share * Fraction(len(known), len(keys))
        lower += share * Fraction(sum(known) * 25, len(keys))
        ds = Fraction(sum(known) * 25, len(keys)) if len(known) == len(keys) else None
        exact_dims[d] = ds
        dims[d] = {
            "score": float(ds) if ds is not None else None,
            "lower_bound": sum(known) * 25 / len(keys),
            "upper_bound": (sum(known) + 4 * (len(keys) - len(known))) * 25 / len(keys),
            "coverage": len(known) / len(keys),
            "excluded": False,
        }
    point = lower if total and not invalid and len(recorded) == len(applicable) else None
    unit_coverage = (
        Fraction(completed, planned)
        if counts_valid and planned > 0 and not invalid and inventory_complete
        else None
    )
    effective = {k: gate_state(gates.get(k, {}), k) for k in [f"R{i}" for i in range(1, 8)]}
    # R7 is produced from a verified approval record, never from a reviewer-entered gate.
    effective["R7"] = "pass" if owner_approved else ("fail" if effective["R7"] == "fail" else "unknown")
    reasons = []
    for k, v in effective.items():
        if v == "fail":
            reasons.append("GATE_FAILED:" + k)
    if any(f.get("state", "open") == "open" and f.get("severity") == "critical" for f in findings):
        reasons.append("OPEN_CRITICAL_FINDING")
    correction = bool(reasons)
    reasons.extend(invalid)
    if not total:
        reasons.append("ALL_EXCLUDED")
    if len(recorded) != len(applicable):
        reasons.append("INCOMPLETE_RUBRIC")
    if unit_coverage is None:
        reasons.append("UNKNOWN_UNIT_COVERAGE")
    incomplete = point is None or unit_coverage is None
    if critical_planned is None or critical_verified is None or critical_planned != critical_verified:
        reasons.append("UNVERIFIED_CRITICAL_UNITS")
    for k in [f"R{i}" for i in range(1, 7)]:
        if effective[k] == "unknown":
            reasons.append("GATE_UNKNOWN:" + k)
    if tier == "High" and not specialist:
        reasons.append("SPECIALIST_REVIEW_REQUIRED")
    checks_missing = any(r.startswith(("UNVERIFIED_", "GATE_UNKNOWN", "SPECIALIST_")) for r in reasons)
    majors = any(f.get("state", "open") == "open" and f.get("severity") == "major" for f in findings)
    if majors:
        reasons.append("OPEN_MAJOR_FINDING")
    low_criteria = [k for k, v in recorded.items() if v < 3]
    reasons.extend("CRITERION_BELOW_3:" + k for k in low_criteria)
    index_min, dim_min, emg_min, unit_min = TIERS.get(tier, TIERS["Standard"])
    thresholds = []
    if point is not None and point < index_min:
        thresholds.append("INDEX_BELOW_FLOOR")
    if unit_coverage is not None and unit_coverage < Fraction(str(unit_min)):
        thresholds.append("CONTENT_COVERAGE_BELOW_FLOOR")
    for d, ds in exact_dims.items():
        if ds is not None and ds < (max(dim_min, emg_min) if d in "EMG" else dim_min):
            thresholds.append("DIMENSION_BELOW_FLOOR:" + d)
    reasons.extend(thresholds)
    if correction:
        route, message = "hold_for_correction", "A failed gate or open critical finding holds release."
    elif invalid:
        route, message = "fix_assessment_inputs", "Correct invalid assessment inputs."
    elif incomplete:
        route, message = (
            "complete_assessment",
            "Complete the applicable ratings, evidence and examination inventory.",
        )
    elif checks_missing:
        route, message = (
            "complete_critical_checks",
            "Verify critical examinations and required pre-release gates.",
        )
    elif majors:
        route, message = "revise_major_issues", "Resolve and verify open major findings."
    elif low_criteria:
        route, message = "revise_criterion_failures", "Every applicable criterion must reach at least 3."
    elif thresholds:
        route, message = "revise_or_expand_review", "One or more unrounded pilot thresholds are unmet."
    else:
        route, message = (
            "awaiting_owner_approval",
            "Calculated readiness is complete; the exact version needs owner approval.",
        )
    ready = route == "awaiting_owner_approval"
    if ready and owner_approved:
        route, message = (
            "approved_by_named_owner",
            "The exact assessment has an authenticated owner approval.",
        )
    if not owner_approved:
        reasons.append("OWNER_APPROVAL_REQUIRED")
    return {
        "notice": NOTICE,
        "rubric_version": RUBRIC["version"],
        "profile": profile,
        "tier": tier,
        "index": float(point) if point is not None else None,
        "index_exact": str(point) if point is not None else None,
        "display_index": (point.numerator * 2 + point.denominator) // (2 * point.denominator)
        if point is not None
        else None,
        "lower_bound": float(lower) if total and not invalid else None,
        "upper_bound": float(lower + 100 * (1 - coverage)) if total and not invalid else None,
        "rubric_coverage": float(coverage) if total else None,
        "unit_coverage": float(unit_coverage) if unit_coverage is not None else None,
        "planned": planned,
        "completed": completed,
        "critical_planned": critical_planned,
        "critical_verified": critical_verified,
        "dimensions": dims,
        "gates": effective,
        "readiness": ready,
        "release_eligible": ready and owner_approved,
        "route": route,
        "reasons": reasons,
        "explanation": message,
    }
