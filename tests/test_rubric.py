import pytest

from assurance.rubric import CRITERIA, PROFILES, calculate
from assurance.schemas import CriterionDecision


def complete():
    return {
        k: {"rating": 4, "method": "human", "method_version": "review-1", "evidence": ["verified-record"]}
        for k in CRITERIA
    }


def score(criteria=None, **overrides):
    args = dict(
        gates={f"R{i}": {"state": "pass", "evidence": ["gate-record"]} for i in range(1, 8)},
        planned=100,
        completed=100,
        critical_planned=10,
        critical_verified=10,
        inventory_complete=True,
    )
    args.update(overrides)
    return calculate(criteria or complete(), **args)


def exclude(item):
    item.update(
        applicable=False,
        exclusion={
            "approved_by": "owner",
            "scope": "exact assessment",
            "reason": "Requirement does not apply",
            "evidence": ["approval"],
        },
    )


def test_handbook_marketing_96_25_held():
    cr = complete()
    cr["G2"]["rating"] = 0
    gates = {f"R{i}": {"state": "pass", "evidence": ["record"]} for i in range(1, 8)}
    gates["R4"] = {"state": "fail", "evidence": ["Missing photo rights"]}
    result = score(cr, profile="Marketing and sales", gates=gates)
    assert result["index"] == 96.25
    assert result["display_index"] == 96
    assert result["route"] == "hold_for_correction"
    assert not result["release_eligible"]


def test_missing_evidence_75_100_bounds():
    cr = complete()
    for k in cr:
        if k.startswith("E"):
            cr[k]["evidence"] = []
    result = score(cr)
    assert result["index"] is None
    assert result["rubric_coverage"] == 0.75
    assert (result["lower_bound"], result["upper_bound"]) == (75, 100)


@pytest.mark.parametrize("bad", [-1, 5, 3.5, "3", True])
def test_invalid_ratings(bad):
    cr = complete()
    cr["E1"]["rating"] = bad
    result = score(cr)
    assert result["route"] == "fix_assessment_inputs"
    assert result["index"] is None and result["lower_bound"] is None
    with pytest.raises(ValueError):
        CriterionDecision(
            criterion="E1", rating=bad, evidence_ids=["a"], method_version="v1", reason="Reviewed"
        )


def test_zero_is_real_failure_not_unassessed():
    cr = complete()
    cr["E1"]["rating"] = 0
    result = score(cr)
    assert result["index"] == 93.75 and result["rubric_coverage"] == 1
    assert "CRITERION_BELOW_3:E1" in result["reasons"]


def test_partial_na_dimension_na_all_excluded_and_invalid_exclusion():
    cr = complete()
    cr["E1"]["rating"] = 0
    exclude(cr["E2"])
    assert score(cr)["dimensions"]["E"]["score"] == pytest.approx(200 / 3)
    for key in ["E1", "E3", "E4"]:
        exclude(cr[key])
    r = score(cr)
    assert r["index"] == 100 and r["dimensions"]["E"]["excluded"]
    for item in cr.values():
        exclude(item)
    r = score(cr)
    assert r["index"] is None and r["rubric_coverage"] is None and r["lower_bound"] is None
    del cr["E1"]["exclusion"]["evidence"]
    assert "EXCLUSION_NOT_APPROVED:E1" in score(cr)["reasons"]


@pytest.mark.parametrize(
    "counts",
    [
        {"planned": 0},
        {"completed": 101},
        {"completed": -1},
        {"critical_verified": 11},
        {"critical_planned": 101},
        {"planned": 10.5},
        {"completed": True},
    ],
)
def test_invalid_inventory_counts(counts):
    r = score(**counts)
    assert r["index"] is None and r["route"] == "fix_assessment_inputs"


def test_unknown_inventory_cannot_release():
    assert score(inventory_complete=False)["route"] == "complete_assessment"
    assert score(critical_verified=9)["route"] == "complete_critical_checks"


def test_routing_precedence_findings_and_gates():
    assert (
        score(findings=[{"severity": "critical", "state": "open"}], completed=None)["route"]
        == "hold_for_correction"
    )
    assert (
        score(findings=[{"severity": "major", "state": "open"}], completed=None)["route"]
        == "complete_assessment"
    )
    assert score(findings=[{"severity": "major", "state": "open"}])["route"] == "revise_major_issues"
    assert score(findings=[{"severity": "major", "state": "resolved"}])["readiness"]
    assert score()["route"] == "awaiting_owner_approval"
    assert not score()["release_eligible"]
    assert score(owner_approved=True)["release_eligible"]


@pytest.mark.parametrize("tier,floor", [("Low", 0.9), ("Standard", 0.95), ("High", 1)])
def test_tier_coverage_thresholds(tier, floor):
    assert score(tier=tier, completed=int(floor * 100), specialist=True)["readiness"]
    assert not score(tier=tier, completed=int(floor * 100) - 1, specialist=True)["readiness"]


def test_high_emg_floor_and_specialist():
    cr = complete()
    cr["E1"]["rating"] = 3
    cr["E2"]["rating"] = 3
    r = score(cr, tier="High", specialist=True)
    assert "DIMENSION_BELOW_FLOOR:E" in r["reasons"]
    assert score(tier="High")["route"] == "complete_critical_checks"


def test_every_profile_seed_and_unrounded_threshold():
    assert len(PROFILES) == 9 and len(CRITERIA) == 24
    for profile, weights in PROFILES.items():
        assert sum(weights.values()) == 100
        assert score(profile=profile)["index"] == 100
    # A display rounded to 85 must not cross the Standard threshold at 85.
    cr = complete()
    for k in cr:
        cr[k]["rating"] = 3
    for k in ["E1", "E2", "E3", "E4", "M1", "M2", "G1"]:
        cr[k]["rating"] = 4
    r = score(cr)
    assert r["index"] == 84.6875 and r["display_index"] == 85
    assert "INDEX_BELOW_FLOOR" in r["reasons"] and not r["readiness"]


def test_gate_na_evidence_and_forbidden_na():
    gates = {
        f"R{i}": {
            "state": "na",
            "approved_by": "owner",
            "scope": "test",
            "reason": "Not applicable",
            "evidence": ["review"],
        }
        for i in range(1, 8)
    }
    r = score(gates=gates)
    assert r["gates"]["R1"] == r["gates"]["R7"] == "unknown"
    assert r["gates"]["R2"] == "na"
    gates["R2"]["evidence"] = []
    assert score(gates=gates)["gates"]["R2"] == "unknown"
