import re
from fractions import Fraction
from typing import Literal, Protocol

from pydantic import Field

from .extraction import pointer_get
from .providers import ProviderError, validate_comparisons, validate_extraction
from .rubric import CRITERIA
from .schemas import StrictModel


class CheckResult(StrictModel):
    examination_id: str
    requirement: str
    item_id: str
    content_locator: dict
    outcome: Literal["pass", "fail", "unknown"]
    evidence: list[dict] = Field(default_factory=list)
    method: str
    method_version: str
    reason: str
    suggested_correction: str | None = None


class Checker(Protocol):
    def check(self, examination: dict, context: dict) -> CheckResult: ...


def plan_examinations(extraction, brief, derivation=None):
    plan = []

    def add(eid, criterion, item_id="document", mode="manual", critical=False, **extra):
        plan.append(
            {
                "id": eid,
                "criterion": criterion,
                "item_id": item_id,
                "mode": mode,
                "critical": critical,
                "modality": "text",
                **extra,
            }
        )

    # All 24 criterion judgments have their own examinations and explicit evidence requirements.
    for key, criterion in CRITERIA.items():
        if key not in brief["exclusions"]:
            add(
                "criterion:" + key,
                key,
                critical=criterion["required"],
                requirement=brief.get("review_plan", {}).get(key, criterion["evidence"]),
            )
    add(
        "inventory-audit",
        "R1",
        mode="manual",
        critical=True,
        requirement="Audit original content, all extracted items and missed claims; confirm inventory completeness.",
    )
    if derivation:
        for criterion, requirement in {
            "M4": "Compare the complete source and target versions for meaning, qualifications and representations.",
            "B2": "Compare source-to-target terminology for this declared language pair.",
            "B3": "Verify target locale and market approval without changing authorised meaning.",
        }.items():
            add(
                "derivation:" + criterion,
                criterion,
                item_id="derivation",
                critical=True,
                requirement=requirement,
                source_version_id=derivation,
            )
    for index, requirement in enumerate(brief.get("specialist_requirements", [])):
        add(f"specialist:{index}", "G3", mode="specialist", critical=True, requirement=requirement)
    for item in extraction["items"]:
        add(
            "claims:" + item["id"],
            "M2",
            item["id"],
            "model",
            True,
            requirement="Compare candidate factual claims with applicable evidence, preserving scope and qualifications.",
        )
    for group, criterion in [
        ("required_fields", "C2"),
        ("required_sections", "C2"),
        ("required_text", "C2"),
        ("structured_values", "M1"),
    ]:
        for idx, value in enumerate(brief.get(group, [])):
            add(
                f"{group}:{idx}",
                criterion,
                mode="deterministic",
                critical=True,
                check=group,
                value=value,
                requirement=f"Brief {group}: {value}",
            )
    add(
        "source-status",
        "E1",
        mode="deterministic",
        critical=True,
        check="source_status",
        requirement="Every declared source is approved, current and applicable.",
    )
    add(
        "policy-text",
        "G1",
        mode="deterministic",
        critical=True,
        check="policy_text",
        requirement="Applicable policy and mandatory wording.",
    )
    add(
        "terminology",
        "B2",
        mode="deterministic",
        check="terminology",
        requirement="Required approved terms and forbidden terms in the policy.",
    )
    gaps = list(extraction["gaps"])
    for modality in brief["declared_modalities"]:
        if modality != "text" and not any(g["modality"] == modality for g in gaps):
            gaps.append(
                {
                    "id": "declared-" + modality,
                    "modality": modality,
                    "reason": "Declared modality needs specialist examination.",
                }
            )
    for gap in gaps:
        for criterion in ("M4", "U3", "U4"):
            add(
                f"gap:{gap['id']}:{criterion}",
                criterion,
                gap["id"],
                "manual",
                True,
                modality=gap["modality"],
                requirement=gap["reason"],
                unsupported=True,
            )
    return plan


UNITS = {
    "month": ("calendar_month", 1),
    "months": ("calendar_month", 1),
    "year": ("calendar_month", 12),
    "years": ("calendar_month", 12),
    "g": ("mass", 1),
    "kg": ("mass", 1000),
    "mg": ("mass", Fraction(1, 1000)),
    "mm": ("length", 1),
    "cm": ("length", 10),
    "m": ("length", 1000),
    "w": ("power", 1),
    "kw": ("power", 1000),
}
WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "six": "6", "twelve": "12"}


def equivalent(actual, expected, unit=None):
    """Only explicitly defined equivalences; no conversion between calendar months and days."""

    def quantity(value):
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and unit:
            value = f"{value} {unit}"
        if not isinstance(value, str):
            return None
        tokens = value.lower().strip().split()
        if len(tokens) != 2:
            return None
        n, u = tokens
        if u not in UNITS:
            return None
        try:
            return UNITS[u][0], Fraction(WORDS.get(n, n)) * UNITS[u][1]
        except (ValueError, ZeroDivisionError):
            return None

    a, b = quantity(actual), quantity(expected)
    if a and b:
        return a == b
    return type(actual) is type(expected) and actual == expected


def base_result(
    exam,
    extraction,
    outcome="unknown",
    reason="Human examination and evidence required.",
    evidence=None,
    method="automated",
    version="deterministic-1",
):
    item = next((i for i in extraction["items"] if i["id"] == exam["item_id"]), None)
    return CheckResult(
        examination_id=exam["id"],
        requirement=exam["criterion"],
        item_id=exam["item_id"],
        content_locator=item["locator"] if item else {"kind": "document", "scope": exam["item_id"]},
        outcome=outcome,
        evidence=evidence or [],
        method=method,
        method_version=version,
        reason=reason,
    )


class DeterministicChecker:
    def check(self, examination, context):
        e, x = examination, context["extraction"]
        text, data = x["text"], x["data"]
        check, value = e.get("check"), e.get("value")
        evidence = [
            {"kind": "brief", "id": context["brief_id"], "requirement": e["id"]},
            {"kind": "content", "id": context["version_id"], "locator": {"kind": "document"}},
        ]
        if not x["supported"]:
            return base_result(e, x, reason="Extraction or format is incomplete.")
        passed, reason = False, ""
        if check == "required_fields":
            try:
                found = pointer_get(data, value)
                passed = found is not None and found != "" and found != [] and found != {}
            except (KeyError, ValueError, TypeError, IndexError):
                passed = False
            reason = "Required field present." if passed else "Required field missing or empty."
        elif check == "required_sections":
            headings = re.findall(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", text, re.M)
            # Plain text section labels must occupy a line; matching body text does not count.
            lines = [line.strip().rstrip(":") for line in text.splitlines()]
            passed = value.casefold() in {h.casefold() for h in headings + lines}
            reason = "Required section found." if passed else "Required section heading missing."
        elif check == "required_text":
            passed = value in text
            reason = "Exact required text found." if passed else "Exact required text missing."
        elif check == "structured_values":
            try:
                actual = pointer_get(data, value["path"])
                passed = equivalent(actual, value["expected"], value.get("unit"))
            except (KeyError, ValueError, TypeError, IndexError):
                passed = False
            reason = (
                "Structured value agrees under defined unit equivalence."
                if passed
                else "Structured value missing or unequal under defined equivalences."
            )
        elif check == "source_status":
            passed = bool(context["sources"]) and all(s["valid"] for s in context["sources"])
            evidence = [
                {
                    "kind": "source_status",
                    "source_id": s["id"],
                    "valid": s["valid"],
                    "reason": s["validity_reason"],
                }
                for s in context["sources"]
            ]
            reason = (
                "Declared sources are approved, current and applicable."
                if passed
                else "A declared source is unapproved, expired or outside its permitted use."
            )
        elif check in {"policy_text", "terminology"}:
            policy = context["policy"]
            if not policy["valid"]:
                return base_result(
                    e,
                    x,
                    "fail",
                    "Policy pack is not approved, current and applicable.",
                    [{"kind": "policy_status", "id": policy["id"]}],
                )
            p = policy["payload"]
            if check == "policy_text":
                passed = all(t in text for t in p["required_text"])
                reason = (
                    "Exact policy wording is present." if passed else "Required policy wording is missing."
                )
            else:

                def term_present(term):
                    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I))

                passed = all(term_present(t) for t in p["approved_terms"]) and not any(
                    term_present(t) for t in p["forbidden_terms"]
                )
                reason = (
                    "Configured terminology checks passed."
                    if passed
                    else "Required approved term missing or forbidden term present."
                )
            evidence.append({"kind": "policy", "id": policy["id"], "hash": policy["hash"]})
        else:
            return base_result(e, x, reason="No deterministic checker for this requirement.")
        r = base_result(e, x, "pass" if passed else "fail", reason, evidence)
        if not passed:
            r.suggested_correction = (
                "Correct the cited requirement and submit a new immutable content version."
            )
        return r


def evaluate(context, provider):
    x, plan = context["extraction"], context["plan"]
    results = {e["id"]: base_result(e, x).model_dump() for e in plan}
    checker = DeterministicChecker()
    for e in plan:
        if e["mode"] == "deterministic":
            results[e["id"]] = checker.check(e, context).model_dump()
    claims, comparisons, provider_error = [], [], None
    try:
        if not x["supported"]:
            raise ProviderError("EXTRACTION_INCOMPLETE")
        if context["external_required"] and not context["brief"].get("allow_external_processing", False):
            raise ProviderError("TENANT_EXTERNAL_PROCESSING_NOT_APPROVED")
        extracted = validate_extraction(provider.extract(x["items"]), x["items"])
        sources = [{"id": s["id"], "text": s["payload"]["text"]} for s in context["sources"] if s["valid"]]
        compared = validate_comparisons(
            provider.compare(extracted.claims, sources), extracted.claims, sources
        )
        claims = [c.model_dump() for c in extracted.claims]
        comparisons = [c.model_dump() for c in compared.comparisons]
        by_id = {c.claim_id: c for c in compared.comparisons}
        for e in plan:
            if e["mode"] != "model":
                continue
            item_claims = [c for c in extracted.claims if c.item_id == e["item_id"]]
            cs = [by_id[c.claim_id] for c in item_claims]
            uncertain = e["item_id"] in extracted.uncertain_item_ids or not cs
            outcome = (
                "unknown"
                if uncertain or any(c.outcome == "insufficient_evidence" for c in cs)
                else ("fail" if any(c.outcome == "contradicted" for c in cs) else "pass")
            )
            ev = [{"kind": "source_quote", **q.model_dump()} for c in cs for q in c.evidence]
            reason = (
                " | ".join(c.reason for c in cs)
                or "No candidate claims; a human must verify extraction completeness."
            )
            results[e["id"]] = base_result(
                e, x, outcome, reason, ev, version="claims-1:" + provider.label
            ).model_dump()
    except ProviderError as exc:
        provider_error = {"code": exc.code, "retryable": exc.retryable}
        for e in plan:
            if e["mode"] == "model":
                results[e["id"]] = base_result(
                    e, x, reason=exc.code, version="claims-1:" + provider.label
                ).model_dump()
    return {
        "checks": results,
        "claims": claims,
        "comparisons": comparisons,
        "provider_error": provider_error,
        "provider_label": provider.label,
        "fixture": "fixture" in provider.label,
    }
