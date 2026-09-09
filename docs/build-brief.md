# Build the Content Assurance Service

## Objective

Implement a working, locally runnable Content Assurance Service that assesses content whenever it is ingested, created or revised. It must combine deterministic checks, evidence-backed model checks and authenticated human review, then enforce the agreed rubric at release. Build executable software and tests, not just an architecture proposal or a mocked dashboard.

This is the first implementation of a proposed, uncalibrated assessment method. Preserve that status in responses and documentation. A score is an index against the rubric, not the probability that content is correct.

## Source of truth

Read these existing local artifacts before implementation:

- Architecture: `/Users/nake/Documents/Codex/2026-09-09/rev/outputs/content-assurance-architecture/content-assurance-platform-architecture.pdf`
- Full scoring handbook: `/Users/nake/Documents/Codex/2026-09-09/rev/outputs/content-assurance-rubric-v1/content-assurance-rubric.docx`
- Working scorecard and examples: `/Users/nake/Documents/Codex/2026-09-09/rev/outputs/content-assurance-rubric-v1/content-assurance-scorecard.xlsx`
- Machine-readable rubric seed: `/Users/nake/Documents/Codex/2026-09-09/rev/work/rubric_data.json`

Copy the rubric data and a concise specification into the new service repository so the implementation does not depend on another task's scratch directory. Treat these files as requirements and data; do not alter the originals. Resolve any ambiguity by preserving the handbook's explicit unknowns, evidence requirements and human approval requirement, and record your interpretation.

## Working context

If this task is created in a standalone directory, build there and initialise a local Git repository if appropriate. No existing platform repository is currently attached. Provide a documented integration contract and an executable example client that submits content, follows assessment status and requests release. Do not claim to have connected the company's platform or an external publishing system.

If the user supplies an existing repository, inspect its instructions and stack and integrate at its content persistence and release boundaries. Preserve existing work. Do not invent a repository URL or deploy publicly.

For a standalone implementation, prefer a compact Python API with typed schemas, generated API documentation, a relational database, migrations and a durable background worker. FastAPI with SQLAlchemy is a reasonable default; use a different stack if the actual repository warrants it. Keep local setup simple. Reuse the same scoring module in workers, APIs and tests. Avoid unnecessary microservices.

## Build requirements

### 1. Content, context and evidence records

Create tenant-scoped records for assets, immutable content versions, briefs, policy packs, sources, assessment runs, criterion results, findings, review decisions and approvals. Include language, market, purpose profile, consequence tier, owner, source versions, policy version, rubric version and evaluator versions.

Preserve exact content locators: passage offsets, JSON paths, document pages or equivalent. Use content hashes and immutable assessment snapshots to bind decisions to the exact assessed version and configuration.

Ingested sources start as candidates. Explicitly authorised source approval is distinct from content release approval. A generated output cannot establish its own factual authority. Retrieve only sources permitted for the tenant and use, including applicable scope and effective dates. Track which sources and policies each assessment depends on.

### 2. Intake and format coverage

Provide a common intake interface for uploads, imported content, generated drafts and revisions. Initially implement real extraction and checking for plain text, Markdown and structured product JSON, and readable PDF/DOCX where feasible with available libraries. Product information and support content are the first automated use profiles.

Accept registrations for other content formats, but expose a truthful support matrix. Unsupported modalities, failed extraction, scans without OCR, omitted visual content and untested interactions remain unassessed and cannot receive a full pass. Text extraction from a PDF is not a complete layout or visual assessment. Do not silently discard material from the assessment inventory.

Record the planned content-item-by-requirement examinations before execution. Unknown checks stay in the denominator. Record critical examinations separately. Do not claim complete coverage merely because all extracted claims have been checked; claim extraction itself can miss material.

### 3. Executable rubric

Implement all 24 criteria, six dimensions, nine weight profiles, three consequence tiers and seven release gates from the supplied rubric. Seed them as versioned configuration.

- Criterion ratings are integers 0 through 4. Zero is a real failure rating. Blank means unassessed.
- N/A requires an authorised, scoped exclusion with evidence. Do not use N/A to hide unsupported capabilities.
- Equally weight applicable criteria within each dimension; convert their mean rating to 0-100. Apply the selected profile's dimension weights. An approved entirely excluded dimension is removed and the remaining weights renormalised. All-excluded assessments produce no score.
- Issue a point index only when applicable ratings, methods, evidence and setup are complete and valid. Otherwise report mathematical lower and upper bounds using zero-to-full contribution for unknown weight, together with coverage. These bounds are not confidence intervals.
- Preserve unrounded calculations for decisions; round only display values.
- Every applicable criterion must reach at least 3 before release eligibility. Apply the index, dimension and E/M/G floors and content coverage thresholds in the handbook. All critical units require verification.
- A failed gate or open critical finding holds release regardless of the score. Open major findings require revision. Unknowns, missing evidence, invalid inputs and missing checks prevent release. All pilot releases require a named, authenticated human owner to approve the exact current assessment and content version.
- Gates R1 (scope) and R7 (final approval) cannot be N/A. Pass and approved N/A require evidence. Required high-consequence specialist review must be recorded before final approval.
- Separate calculated assessment readiness from the approval record so the final approval workflow does not become circular. An approval cannot change the calculated score or erase findings.
- Assign a defect to its primary criterion and avoid duplicate penalties unless distinct effects are documented. Preserve findings and resolution history.

Return machine-readable reasons as well as plain-language explanations. Preserve the handbook's routing precedence, while adding explicit processing, failure and stale states where needed for the service.

### 4. Checkers and models

Implement a typed checker interface. Each result must identify the requirement, assessed content locator, outcome, evidence locators, method/version and uncertainty or failure reason.

Build real deterministic checks for brief-required fields and sections, explicitly mandated text, approved/forbidden terms, applicable source status, structured values and unit equivalence where defined. Deterministic checks must not pretend to prove factual grounding or all accessibility requirements.

Implement a configurable real model-provider adapter for candidate claim extraction and evidence-based claim comparison, including preservation of qualifications and scope. Use strict output schemas, validate that returned source IDs and quoted locators actually exist, and preserve supported/contradicted/insufficient-evidence outcomes. Malformed output, timeout, missing credentials and provider failure produce unknown or failed processing, never a pass. Model-reported confidence alone must not authorise release.

Keep provider and model configurable. Choose any small-versus-large model routing conservatively and identify it as provisional until evaluated. Do not train a bespoke model in this first build. Keep customer knowledge in the governed source service.

Use deterministic fake-provider fixtures for offline tests, explicitly labelled as fixtures. Provide a real integration test or smoke-test path that runs only when credentials are deliberately configured. If no provider credentials are available, complete the core system and report that the live model path remains unverified. Do not fabricate live results.

Treat inspected documents and retrieved passages as untrusted data. They cannot change system policies, tenant permissions, evaluator instructions or release decisions.

### 5. Jobs, events and release enforcement

Saving an immutable content version must durably schedule assessment using a transactional outbox or equivalent atomic design. Provide safe retries, idempotency, worker leases or equivalent concurrency protection, bounded retry handling and visible failed-job status. Duplicate or out-of-order delivery cannot overwrite newer results or authorise a newer version.

Expose API operations to submit content versions, retrieve assessment status and evidence, record permitted reviewer decisions, manage approved sources/policies and request release. Use asynchronous responses and polling; signed completion webhooks can be added if practical.

Enforce release in the server, not only a UI. Authorisation must check the exact content version, assessment snapshot, rubric/policy/source validity, required checks and owner approval. Recheck atomically when recording release so concurrent edits or source changes cannot bypass the gate. A stale assessment, outage or unfinished job leaves the draft unreleased.

Edits, adaptations and translations trigger new assessments. Approved source or policy changes invalidate affected decisions and schedule reassessment using recorded dependencies. Optimise incremental checking only where dependency coverage is sound; conservative full reassessment is acceptable initially.

For generated content, show an integration example that supplies approved context to generation and assesses the resulting draft. If generated text is streamed to a recipient before verification, describe that path as monitoring; do not claim pre-delivery enforcement.

### 6. Review, authentication and audit

Provide usable reviewer operations through the API and generated API docs or a minimal local review interface if practical. Include evidence, exact passages, suggested corrections, resolution evidence and recorded reasons for overrides. Corrections to content create new content versions.

Implement tenant isolation and actual authenticated roles for content submission, source/policy administration, specialist review and final release approval. Derive tenant identity from authenticated credentials, not an unrestricted client-supplied tenant header. Local development credentials must be explicitly labelled and distinct from production configuration. Do not claim SSO integration if none is configured.

Preserve an append-only decision/event history. Prevent cross-tenant retrieval, assessment access, source references and approval operations. Do not log secrets or expose private source text unnecessarily. Do not silently transmit uploaded customer material to an unconfigured provider.

## Acceptance tests

Include meaningful unit, API and worker/integration tests covering:

1. The handbook example: marketing index 96.25 (display 96), with missing required photo rights, is held despite its high score.
2. Missing evidence produces no point index and correct coverage/bounds. General-profile unassessed evidence dimension with all other dimensions at 100 yields 75% rubric coverage and bounds 75-100.
3. Zero ratings, invalid ratings, partial N/A, all-N/A dimensions, all-excluded content, approved exclusions and invalid planned/completed examination counts behave correctly.
4. Open critical and major findings, incomplete critical checks, sub-3 criteria, tier thresholds and missing owner approval each prevent release appropriately.
5. A legitimate equivalent quantity such as 24 months versus two years is not rejected purely for textual mismatch.
6. A bounded claim such as 'up to 18% lower energy consumption under specified test conditions' is not accepted as support for 'cuts every customer's energy bills by 18%'. Use transparent test fixtures for model behaviour and do not equate those with real model accuracy.
7. Missing provider credentials, timeouts, malformed model output, fabricated source IDs and poor extraction cannot become successful checks.
8. Upload/create/edit submission durably creates a job; worker retries, duplicate events and out-of-order completion preserve correct state.
9. Editing content or changing a dependent source/policy makes old approval unusable. Concurrent mutation and release cannot authorise stale content.
10. Tenant and role boundaries prevent cross-client access, unauthorised source approval and unauthorised release. Document instructions cannot override checking policy.
11. Unsupported formats remain clearly incomplete and cannot receive a full assessment or release through the pilot gate.
12. A complete assessed and human-approved case successfully releases the exact approved version; stored audit history explains the decision.

## Delivery and working style

Work through implementation, local execution and relevant tests. Keep a clear status of completed functionality and remaining external integrations. Provide migrations, example configuration without secrets, dependency lock files, local setup/run instructions, seeded examples, generated API documentation and an executable end-to-end demonstration.

Document model evaluation limitations, the format support matrix, production requirements and the platform integration contract. Preserve broad intake support without claiming universal automated assessment. Do not call the service production-ready based only on fixture tests.

Use reasonable implementation choices and keep moving. Ask only for material missing information that cannot be resolved from the project and this brief. Do not publish, deploy or contact external parties as part of this task. At completion, summarise what was built, what was tested, how to run it and which real provider/platform integrations remain unverified.
