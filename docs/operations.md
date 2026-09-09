# Operations and production requirements

This is locally runnable pilot software, not a production-readiness certification. `CAS_MODE=production` rejects fixture providers and development credentials; it does not supply the infrastructure and controls listed below.

For Arbitr deployment, the [stack compatibility and integration design](arbitr-stack-compatibility.md) specifies the PostgreSQL port, Redis queue/cache split, gateway identity and delivery acceptance checks. Follow the monorepo's Pipenv, Docker and Make conventions when integrating; the local commands below apply to this standalone pilot.

## Local configuration

| Variable | Default | Meaning |
|---|---|---|
| `CAS_DB` | `var/assurance.sqlite3` | SQLite database path; API and worker must share it on one host |
| `CAS_MODE` | `local` | `local` or `production`; controls development-credential/fixture acceptance |
| `CAS_PROVIDER` | `disabled` | `disabled`, `fixture` or `chat` |
| `CAS_PROVIDER_URL` | empty | Explicit HTTPS provider base URL |
| `CAS_PROVIDER_MODEL` | empty | Explicit model supporting strict structured output |
| `CAS_PROVIDER_API_KEY` | empty | Secret supplied by operator; not persisted in snapshots |
| `CAS_ALLOW_EXTERNAL` | `false` | Operator consent for provider transmission; brief opt-in also required |
| `CAS_PROVIDER_TIMEOUT` | `20` | Per-request network timeout, seconds |
| `CAS_JOB_LEASE` | `180` | Worker lease duration, seconds; renewed during checks |
| `CAS_JOB_ATTEMPTS` | `3` | Maximum attempts for transient/worker failures |

The CLI reads process environment variables. It does not auto-load `.env`. Default API binding is loopback. No background service is installed automatically. Use your process supervisor for sustained operation. `/health` checks database availability; run/job status reports queue state, attempt count and a safe last-error code. A responsive API does not prove that a worker is running.

## Identity operations

`uv run assurance init` applies migrations without creating credentials. For real local review, provision a distinct named principal for each person using `assurance user-add --tenant TENANT --name 'Person name' --roles reviewer,approver,submitter`. Only grant roles the person needs. A generator/integration credential should use `--machine --roles submitter`; machine identities cannot hold reviewer, specialist or approver roles. Resource administration endpoints also require a human identity. Assign separate source/policy administrators and qualified specialists as appropriate.

The operator command displays the new token once so it can be stored securely. Never place it in source control, URLs, reports or client-side public code. `assurance user-revoke PRINCIPAL_ID` disables that credential and clears current release pointers associated with its approvals. Historical decisions remain immutable. To change roles or rotate a key, revoke the old principal and provision a replacement; current briefs bind owner IDs, so an owner change needs a new brief/content version.

The database operator is trusted. API credentials cannot call the provisioning CLI. The service cannot prevent an operator with filesystem/database control from replacing files or dropping database triggers. Production identity should use your identity provider, MFA and independently audited human account provisioning. SSO is not implemented.

## Persistence, concurrency and retries

SQLite uses WAL, foreign keys, full synchronous durability and serialized `BEGIN IMMEDIATE` write transactions. The immutable version and its durable job are committed together, serving as a transactional outbox equivalent. Workers claim jobs with unique lease tokens, renew leases, and fence completion by the active token, current run and lease expiry. Duplicate or stale workers cannot overwrite an accepted result.

Transient failures retry with bounded exponential delays up to 30 seconds. A crash on the last attempt becomes a visible failed job after lease expiry. Nonretryable model/configuration failures produce explicit unknown examinations, while the mechanically completed results remain available. A reviewer may independently complete a missing-provider examination with actual human evidence, but the original machine outcome remains unknown. Failed job processing cannot be approved; request `/v1/assets/{id}/reassess` after diagnosing it.

Source/policy mutations, content revisions, review snapshots and release checks all use the same serialized write boundary. Source changes invalidate current dependent runs, clear release pointers and insert new jobs atomically. Expiration is checked at read/release time, and the worker schedules reassessment. A worker configured differently from the API can invalidate runs; keep evaluator settings synchronized during a controlled restart. The fingerprint includes the deployed checker/scoring code hash and installed parsing/schema/transport library versions. Do not run competing worker versions with different evaluator fingerprints.

Schema migrations reside in `assurance/migrations/`. Startup applies unapplied SQL files transactionally and verifies checksums of applied files. Do not edit an applied migration; add a new numbered migration. Immutable content, source/policy versions, evidence, decisions, machine results, snapshots, approvals, releases and events have update/delete prevention triggers. Runs permit lifecycle/head changes but freeze their version, tenant, plan and configuration. Current heads, job leases and principal activation are intentionally mutable.

Back up using SQLite's online backup API or stop writers and back up consistently; copying only the main database while a live WAL exists is not a reliable backup. Test restore and recovery. The application does not implement retention deletion because audit and evidence records are deliberately append-only; production retention and lawful deletion need an explicit design.

## Before production use

Supply TLS termination, an identity-provider integration, least-privilege operating accounts, secure key storage/rotation, per-tenant access policy review, encryption at rest, data residency and retention controls, a reviewed backup/restore plan, ingress limits, rate limits, resource-limited parser isolation, monitoring, alerting and failure recovery. Prevent untrusted uploads from consuming unbounded parser resources. The current local file-size/page/expansion limits are not a document-parser sandbox.

For scale beyond a single host, design a database migration with correct row locks, fencing and tenant isolation, then rerun the concurrency and acceptance tests against it. PostgreSQL, distributed queues, database row-level security and multi-host operation are not supplied. Append-only tables and a tenant audit hash chain aid inspection, but do not replace external tamper-resistant audit retention.

Authorize the chosen provider, data-processing terms and region; verify actual endpoint/model compatibility; evaluate performance on representative independently adjudicated client data. Implement the platform's own atomic publishing/delivery contract, webhook/polling integration and stale-content withdrawal policy. Signed completion webhooks, external publisher transactions, object storage, OCR and specialist modality engines are not implemented.

## Conservative limits to retain

Never convert an outage, expired source, missing credential, malformed model response, unsupported format or unknown examination into a pass. Do not let a changed score profile silently keep old approvals valid. Do not present a fixture score as client quality or a calibrated risk estimate. Do not remove human final approval until a separately governed, validated method explicitly authorizes such a change.
