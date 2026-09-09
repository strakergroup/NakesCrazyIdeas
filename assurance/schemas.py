from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]
Key = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]{1,100}$")]
Criterion = Annotated[str, StringConstraints(pattern=r"^[EMCGUB][1-4]$")]
Rating = Annotated[int, Field(strict=True, ge=0, le=4)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(StrictModel):
    markets: list[Text] = Field(min_length=1)
    languages: list[Text] = Field(min_length=1)
    profiles: list[Text] = Field(min_length=1)
    uses: list[Literal["assessment", "generation"]] = Field(min_length=1)
    effective_from: datetime
    effective_until: datetime | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.effective_from.tzinfo is None or (
            self.effective_until and self.effective_until.tzinfo is None
        ):
            raise ValueError("Effective dates require a timezone")
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValueError("Effective interval must be positive")
        return self


class ResourceIn(StrictModel):
    key: Key
    title: Text
    scope: Scope
    text: str = Field(min_length=1, max_length=200000)
    origin: Literal["external", "human", "generated"] = "external"
    required_text: list[Text] = []
    approved_terms: list[Text] = []
    forbidden_terms: list[Text] = []


class Reason(StrictModel):
    reason: Text
    evidence: Text


class StructuredRequirement(StrictModel):
    path: Text
    expected: Any
    unit: str | None = None


class Exclusion(StrictModel):
    reason: Text
    scope: Text
    evidence: Text


class BriefIn(StrictModel):
    title: Text
    purpose: Text
    audience: Text
    acceptance_criteria: list[Text] = Field(min_length=1)
    owner_id: Key
    profile: str = "General"
    tier: Literal["Low", "Standard", "High"] = "Standard"
    market: Text
    language: Text
    policy_key: Key
    source_keys: list[Key] = Field(min_length=1, max_length=30)
    required_fields: list[Text] = []
    required_sections: list[Text] = []
    required_text: list[Text] = []
    structured_values: list[StructuredRequirement] = []
    exclusions: dict[Criterion, Exclusion] = {}
    declared_modalities: list[Text] = Field(default_factory=lambda: ["text"], min_length=1)
    specialist_requirements: list[Text] = []
    review_plan: dict[Criterion, Text] = {}
    allow_external_processing: bool = False


class Submit(StrictModel):
    asset_id: Key | None = None
    expected_version_id: Key | None = None
    brief_id: Key
    title: Text
    format: Text
    content: str | dict[str, Any]
    origin: Literal["upload", "import", "created", "generated", "revision", "translation", "adaptation"] = (
        "created"
    )
    derived_from_version_id: Key | None = None


class EvidenceIn(StrictModel):
    kind: Literal["review", "source", "content"]
    note: Text
    method: Text
    source_id: Key | None = None
    item_id: str | None = None
    start: Annotated[int, Field(strict=True, ge=0)] | None = None
    end: Annotated[int, Field(strict=True, ge=0)] | None = None
    quote: str | None = None
    external_record: str | None = None


class CriterionDecision(StrictModel):
    criterion: Criterion
    rating: Rating
    evidence_ids: list[Key] = Field(min_length=1)
    method_version: Text
    reason: Text


class ExaminationDecision(StrictModel):
    examination_id: Text
    outcome: Literal["pass", "fail", "unknown"]
    evidence_ids: list[Key] = Field(min_length=1)
    reason: Text


class GateDecision(StrictModel):
    gate: Annotated[str, StringConstraints(pattern=r"^R[2-6]$")]
    state: Literal["pass", "fail", "unknown", "na"]
    evidence_ids: list[Key] = Field(min_length=1)
    reason: Text
    scope: Text | None = None


class FindingIn(StrictModel):
    primary_criterion: Criterion
    severity: Literal["critical", "major", "minor", "preference"]
    item_id: Text
    description: Text
    correction: Text
    evidence_ids: list[Key] = Field(min_length=1)
    related_finding_id: Key | None = None
    distinct_effect: Text | None = None


class FindingResolution(StrictModel):
    finding_id: Key
    disposition: Literal["resolved", "dismissed"]
    reason: Text
    evidence_ids: list[Key] = Field(min_length=1)


class ReviewIn(StrictModel):
    expected_snapshot_id: Key
    criteria: list[CriterionDecision] = []
    examinations: list[ExaminationDecision] = []
    gates: list[GateDecision] = []
    findings: list[FindingIn] = []
    resolutions: list[FindingResolution] = []


class ScopeApproval(Reason):
    plan_hash: Text
    inventory_complete: bool


class SnapshotDecision(Reason):
    snapshot_id: Key
    snapshot_hash: Text


class ReleaseIn(StrictModel):
    version_id: Key
    snapshot_id: Key
    snapshot_hash: Text
    approval_id: Key


class ScoreResponse(StrictModel):
    notice: str
    rubric_version: str
    profile: str
    tier: str
    index: float | None
    index_exact: str | None
    display_index: int | None
    lower_bound: float | None
    upper_bound: float | None
    rubric_coverage: float | None
    unit_coverage: float | None
    planned: int | None
    completed: int | None
    critical_planned: int | None
    critical_verified: int | None
    dimensions: dict[str, dict]
    gates: dict[str, str]
    readiness: bool
    release_eligible: bool
    route: str
    reasons: list[str]
    explanation: str


class VersionAccepted(StrictModel):
    asset_id: str
    version_id: str
    run_id: str
    job_id: str
    state: str
    plan_hash: str


class SnapshotResponse(StrictModel):
    id: str
    hash: str
    run_id: str
    version_id: str
    content_hash: str
    config_hash: str
    plan_hash: str
    machine_hash: str
    decision_ids: list[str]
    criteria: dict[str, dict]
    gates: dict[str, dict]
    checks: dict[str, dict]
    findings: list[dict]
    score: ScoreResponse
    coverage_by_modality: dict[str, dict]
    provider_label: str
    provider_error: dict | None
    fixture: bool
    specialist_reviewed: bool


class ReviewResponse(StrictModel):
    decision_id: str
    snapshot: SnapshotResponse


class ApprovalResponse(StrictModel):
    id: str
    version_id: str
    snapshot_id: str
    owner_id: str
    owner_name: str


class ReleaseResponse(StrictModel):
    id: str
    version_id: str
    content_hash: str
    status: Literal["released"]
    published_externally: Literal[False]


class RunResponse(StrictModel):
    id: str
    asset_id: str
    version_id: str
    state: Literal["awaiting_scope", "queued", "processing", "completed", "failed", "stale"]
    stale_reason: str | None
    job: dict
    plan: list[dict]
    plan_hash: str
    config_hash: str
    brief: dict
    evaluators: dict
    rubric_version: str
    dependencies: list[dict]
    snapshot: SnapshotResponse | None
    owner_approval: dict | None
    release_eligible: bool
    final_gate: Literal["pass", "unknown"]
