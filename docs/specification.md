# Executable specification and interpretations

This repository implements the supplied September 2026 Content Assurance Service brief. The copied source documents are `build-brief.md`, `handbook.txt` and `architecture-source.txt`. The unmodified machine-readable rubric is `assurance/config/rubric-1.0.json`. `source-manifest.json` records the original input hashes. The scorecard was inspected for formulas and worked examples; it is not used at runtime.

## Rubric arithmetic

All 24 criterion IDs, evidence requirements and anchors, six dimensions, nine positive-weight profiles, three tiers and seven gates are seeded from version 1.0. An integer zero is a failure rating. Null is unassessed. A rating is recorded only with a recognized human/automated/hybrid method, method version and nonempty evidence references. API judgments enforce strict integers; invalid standalone scoring inputs suppress the point index and bounds.

Applicable criteria have equal weight within each dimension. Excluded criteria redistribute their dimension's weight. An entirely excluded dimension is removed and the remaining profile weights are normalized. All-excluded scope produces no index, bounds or rubric coverage. Scoped exclusions require the named owner's authorization and evidence; unsupported modalities cannot be excluded to gain a pass.

`Fraction` arithmetic retains exact comparisons. Each dimension is the mean rating multiplied by 25. The profile combines active dimensions into an index. Rubric coverage is the share of applicable criterion weight with a defensible rating. Unknown criterion weights contribute zero to the lower bound and full points to the upper bound. Bounds are mathematical, not confidence intervals. Decisions use exact values; `display_index` rounds the final point index to a whole number, with halves up.

A point index requires complete applicable ratings, methods, evidence and valid setup. Coverage and release readiness are also reported separately. A point index may describe complete criterion judgments while separately planned examinations remain unresolved; those checks still block release. Consumers must never treat a point index as release authorization.

| Tier | Index minimum | Every active dimension | E/M/G minimum | Planned unit coverage |
|---|---:|---:|---:|---:|
| Low | 80 | 60 | 75 | 90% |
| Standard | 85 | 70 | 75 | 95% |
| High | 90 | 75 | 90 | 100% |

Every applicable rating must be at least 3. All critical examinations must pass with evidence. Open critical and major findings, failed gates, incomplete evidence, invalid setup and missing checks prevent release. High consequence content requires declared specialist requirements and a recorded specialist review before final approval. Any explicitly declared specialist requirements are also enforced at Low or Standard tier, with separate critical examinations that only the specialist operation can verify.

## Routing and the final approval boundary

The pure rubric preserves the handbook order: hold for a failed gate/open critical finding; fix invalid inputs; complete incomplete assessment; complete critical examinations/pre-release gates; revise major findings; revise sub-3 criteria; revise or expand review for threshold failures; then await owner approval. Service lifecycle states add `awaiting_scope`, `queued`, `processing`, `completed`, `failed` and `stale`. Machine errors remain visible even when a job finishes with unknown outcomes.

R1 and R7 cannot be N/A. Pass and approved N/A require evidence. R1 is written only by the named owner before worker execution, against the exact plan hash. Applicability is frozen before any score is visible. R2–R6 are authenticated review operations. Gate N/A requires the named owner, a scope, a reason and recorded evidence.

**Interpretation to avoid circular approval:** snapshots calculate readiness with R1–R6 and required specialist review, excluding final R7. Their immutable `score.release_eligible` remains false while awaiting owner approval. The separate approval record supplies R7. The current run response combines the current snapshot, freshness and active owner approval into its outer `release_eligible` and `final_gate`. `/release` performs the authoritative atomic checks; it does not trust a client-provided score.

Every subsequent review creates a new snapshot, invalidating old approval. A review after a specialist decision also requires a new specialist decision. Approval cannot alter scores, hide findings or rewrite any earlier decision. A corrected content passage must be submitted as a new version.

## Frozen examination inventory

The service records examinations before execution: one whole-document judgment for each applicable criterion, an independent original-content/extraction audit, a candidate-claim comparison examination for each extracted item, every configured deterministic requirement, and explicit visual/format gaps. Paragraphs, JSON scalar records, PDF pages and DOCX paragraphs/cells supply stable items. This inventory is independent of the model's candidate-claim list, so missed claim extraction cannot shrink the denominator.

Derived versions add manual source-to-target meaning, terminology and locale/market examinations. These are provisional manual overlays; no automatic translation accuracy is claimed. The original version ID is preserved and must belong to the same tenant. A platform must submit a new derivative when its original changes; automatic fan-out from arbitrary parent content edits is outside the source/policy dependency mechanism.

Unknown examinations remain planned. Complete means the planned examination has a pass/fail outcome with evidence; verified critical means pass with evidence. An owner who cannot confirm the complete inventory leaves coverage unknown and must request a new assessment after correcting the scope. Coverage is reported by modality and criticality.

**Conservative pilot interpretation:** all generated examinations are required, and every claim-comparison item is critical. The engine implements the handbook's 90/95/100% unit floors, while this service also blocks every unresolved planned check. Consequently a service release currently requires all its required examinations to be completed, even where a tier's numerical floor alone would permit a smaller fraction. This implements the brief's explicit “missing checks prevent release” requirement without treating an unavailable capability as optional.

Readable PDF/DOCX text can be assessed, but their declared remaining content and delivery characteristics require manual examinations. Scans, extraction errors, unsupported formats and declared unsupported modalities suppress full assessment and release even if a reviewer enters high ratings.

## Evidence and reviewer authority

Automatic rubric ratings are deliberately limited to E1 source status and G4 provenance. A known source failure receives E1=0. Other check outcomes support review and produce findings; a required section's presence does not itself establish useful completeness, and a text comparison does not prove all accessibility requirements. Human ratings E2/E3/M1/M2 at 3 or 4 require an exact permitted source passage in addition to any review notes.

The API validates source IDs, snapshot membership and quoted offsets against immutable source text. Content quotes identify an item and its exact Unicode character interval. Human observations and specialist evidence are authenticated attestations stored as immutable records, not claims that software has independently verified the truth of those observations. External-record references are stored without fetching their URLs. The source/policy creator is the recorded resource custodian; approval records identify the authorizing administrator.

Findings have a primary criterion, exact item/locator, severity, suggested correction and evidence. Automatic failures do not deduct from multiple criteria. Model contradictions are major review suggestions, not automatically adjudicated critical findings. Human findings can identify a related defect only with a documented distinct effect. Each human criterion rating also has its own reason. Reviewers remain responsible for avoiding duplicate human penalties. Resolutions and dismissals preserve prior findings and verification evidence; critical resolutions require a specialist.

## Governing source changes

Source/policy text and metadata versions are immutable. Every new version begins as a candidate and replaces the current resource head. Approval and revocation increment a governance revision. Resources generated by a model cannot approve themselves as factual authority. Only current, approved resources matching tenant, market, language, profile, use and effective dates are provided as assessment or generation context.

The run snapshot records every selected source and policy version plus governance revision. Changes invalidate dependent current runs and their release pointers and atomically schedule complete reassessment. Workers periodically check expiration and evaluator/rubric changes, while reads and release independently reject stale assessments immediately. Historical releases remain audit facts; they are not standing publishing permission.

Only recorded dependencies are automatic triggers. A newly discovered relevant source outside the brief requires a revised brief and content submission. The source-conflict/extraction audit is a required human responsibility. No hidden retrieval from the web, another tenant or a generated output is performed.
