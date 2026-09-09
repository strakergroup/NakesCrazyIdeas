# Reviewer guide

Start the API and worker as described in the README, then open `/docs`. Select **Authorize** and supply your own credential. Development identities created by `init --demo` are clearly labelled and must not be treated as real client sign-off. The service authenticates a credential and records a person's decision; it does not independently establish that the human observation is true.

## Before execution

Use `/v1/me` to verify your identity and roles. A named owner creates the approved brief. After content is submitted, `/v1/review-queue` lists current tenant assessments. Retrieve `/v1/runs/{id}` and `/v1/versions/{version_id}`. Download the exact original from `/v1/versions/{version_id}/original` when examining PDF, DOCX or a rendered representation.

The run has the proposed content-item-by-requirement inventory, declared modalities, critical flags, requirements and `plan_hash`. Inspect whether extraction has missed material, required sections, tables, figures or interactions. The owner records `/scope` before execution, with the exact plan hash and an honest inventory-completeness assertion. If the inventory is incomplete, do not assert completeness. Correct the brief/scope through a new version or request reassessment. An incomplete inventory keeps coverage unknown.

## Evidence and judgments

Poll the run until the worker completes or visibly fails. Retrieve `/machine-results` for the original immutable candidate claims, comparisons, check outcomes, source quotations and provider error. A model suggestion is not final human adjudication. The current snapshot combines those original results with later authenticated review decisions.

Create evidence with `/v1/runs/{id}/evidence`:

- `kind: source` identifies a permitted `source_id`, exact `start` and `end` Unicode code-point offsets, and exact `quote`. It must be one of the approved source versions in this assessment. Add the comparison method and your note explaining how it supports the assessed claim.
- `kind: content` identifies an extracted `item_id`, exact local offsets and quote. The stored evidence also records the item's page, JSON pointer or document locator.
- `kind: review` records a human observation or test result with method, detailed note and optional `external_record`. Refer to an actual test record, rendered output or observed action where required. References are not automatically fetched or independently certified by this service.

A review submission includes the current `expected_snapshot_id`. Record criterion ratings with evidence IDs, method version and a reason. Passing E2/E3/M1/M2 judgments must cite an exact source passage. Rate the worst material unresolved condition in each criterion. Do not use a generic “looks good” note as a substitute for the criterion's required examination. All 24 criterion descriptions and anchors are available at `/v1/rubric` and in the copied handbook.

Record remaining planned examinations with `pass`, `fail` or `unknown`. Unknown means the examination cannot yet establish its result. An examination being performed is not the same as it being verified: failed examinations count as completed but cannot verify a critical unit. Criterion examinations are updated by criterion ratings and cannot be independently entered as pass.

For PDF/DOCX, explicitly inspect all format gaps using the original/actual delivery environment and retain manual evidence. Unsupported formats, scans and failed extraction cannot receive a complete pass through this pilot merely by entering high ratings. Missing-provider checks may be completed by a competent authenticated human using actual evidence; the original model outcome remains unknown in `/machine-results`.

## Findings and gates

Create findings with one primary criterion, severity, exact item, evidence, description and proposed correction. A related defect in another criterion needs a valid prior finding ID and a documented distinct effect. Keep a single underlying defect from causing duplicate penalties. Model contradictions enter as major suggestions; a specialist/human must adjudicate consequential uncertainty.

Corrections to the actual content require a new content version. If a finding was a false positive, use a reasoned dismissal with verification evidence. Resolutions/dismissals stay in the record, with reviewer and evidence. A critical finding can only be resolved or dismissed by a specialist. An override of a check does not by itself resolve the related finding; record both decisions where justified. Source approval or policy applicability cannot be created through a content review override.

Record R2–R6 with actual gate evidence. Only the named owner can grant scoped N/A, and R1/R7 cannot be N/A. Missing photo rights fail R4 regardless of the numeric index. High consequence briefs and any brief that declares specialist requirements require a specialist review of the current snapshot after the substantive review is finished. These planned specialist examinations are completed through the specialist operation, not ordinary examination overrides. Any later review requires a new specialist decision.

## Final owner decision

Read the current score's explanation and machine-readable reasons alongside exact passages, coverage and findings. When calculated `readiness` is true, the named owner submits `/approve` with the current snapshot ID/hash, reason and evidence. Approval records R7 separately and leaves the calculated snapshot untouched.

The owner then requests `/v1/assets/{id}/release` with the exact version, snapshot and approval IDs. This records a local service release after an atomic recheck. It does not publish externally. Every later edit or review, governed source/policy change, or relevant evaluator change requires current reassessment and fresh approval.

Audit history is available at `/v1/runs/{id}/history`, immutable prior snapshots at `/v1/snapshots/{id}`, and append-only tenant events at `/v1/events`. Preserve these records when resolving defects; do not rewrite an old approval to refer to a new version.
