# Validation record

The service is implemented and locally executed. The API, worker, database transactions and pure rubric are covered by automated tests. The live-provider smoke test is deliberately skipped unless explicitly configured. This is evidence about software behavior under these tests, not evidence that the proposed rubric, a model or human review has achieved real-world accuracy.

The latest exact counts and command results are in the delivered `verification.json`. The full offline demonstration report is `demo-report.json` in the delivered outputs. The demonstration used a real local HTTP API and a separate worker process with synthetic data, fixture comparisons and scripted local human identities. It successfully blocked an incomplete assessment, recorded an exact-version local release after simulated review, then revoked a source and rejected the old approval.

## Acceptance mapping

| Brief acceptance test | Implemented verification |
|---|---|
| 1. Marketing index 96.25, display 96, missing photo rights held | `test_handbook_marketing_96_25_held` verifies exact arithmetic and failed R4 priority |
| 2. Missing evidence, no point index, general 75% coverage and 75–100 bounds | `test_missing_evidence_75_100_bounds` |
| 3. Zero/invalid ratings, partial N/A, dimension N/A, all excluded and invalid counts | Parametrized rubric/schema tests; approved exclusions; unsupported-modality exclusion rejection |
| 4. Critical/major findings, missing critical units, criterion/tier floors and owner approval | Routing tests; API approval rejection; specialist review and finding-resolution history tests |
| 5. 24 months versus two years | Exact defined-equivalence tests and product JSON worker/API examination |
| 6. Bounded energy consumption claim versus universal bill savings | Labelled deterministic provider fixture verifies contradicted outcome and scope explanation; no live accuracy inference |
| 7. Missing keys, timeout, malformed output, invented sources and poor extraction | Provider contract/validation tests; bounded worker retries; malformed documents and incomplete-item inventories |
| 8. Durable upload/create/edit jobs, retries, duplicates and ordering | Intake/idempotency tests; injected outbox failure rollback; multiple workers; lease recovery/fencing; old completion discard |
| 9. Edits and dependent source/policy changes invalidate approvals; concurrent mutation | Source/policy revision/revocation and expiry tests; review-change invalidation; threaded release/revocation serialization |
| 10. Tenant/role boundaries and untrusted document instructions | Cross-tenant content, source, evidence and approval tests; role restrictions; local credential rejection in production mode; prompt/fixture injection checks |
| 11. Unsupported content remains incomplete | Unsupported format/audio, scanned PDF, failed DOCX/JSON/text extraction, retained gaps, prohibited exclusions and blocked approval |
| 12. Complete assessed and approved case releases exact version with audit explanation | End-to-end API test and separate real-HTTP executable demo; snapshot hash binding; duplicate release and audit chain verification |

Additional tests cover required fields and exact wording, source permission/effective-date constraints, generated-source rejection, exact source quotation validation, high-tier specialist reapproval, original machine-result immutability, and derivation-specific examination plans.

## What has not been validated

No external provider was called because no explicit provider credentials were present. The real adapter has deterministic mocked-HTTP tests and an executable opt-in smoke path. The fixture outcome for the energy example does not establish that a live model will detect that error. No company platform, external generator, publisher, SSO or production infrastructure is connected. No claims of OCR, visual/accessibility conformance, calibrated thresholds, or production readiness are made.

The tests run against the included single-host SQLite implementation. They do not establish behavior for a different database, multiple hosts, adversarial parser resource attacks or a production traffic load. The API dependency emits upstream test-client deprecation notices; the test outcomes pass. Those notices do not indicate failed assessment checks.
