# Platform integration contract

The service is standalone and has been exercised through an executable local HTTP client and worker. No company repository, external generator or publisher was connected. Integrate at the platform's immutable content persistence boundary and its final publish/export/delivery boundary.

## Authentication and roles

Use `Authorization: Bearer <credential>`. The credential identifies a tenant, named principal, human/service identity and roles. Client-provided tenant headers are ignored. Keys are provisioned by an operator and stored only as SHA-256 hashes in the database; generated keys contain high entropy. There is no SSO, JWT delegation or browser session integration in this pilot.

| Role | Authorized operations |
|---|---|
| submitter | Save/upload/import/generate/revise versions; request reassessment; retrieve approved generation context |
| source_admin | Register source versions; explicitly approve/revoke current sources |
| policy_admin | Register policy versions; explicitly approve/revoke policies |
| reviewer | Add evidence; rate criteria; examine planned units; record gates R2–R6; create and resolve permitted findings; read audit history |
| specialist | Record specialist review; resolve critical findings; also grant reviewer when needed |
| approver | As the named owner, approve briefs, scope, scoped N/A and exact final snapshots; request local release |

Resource administration and all review/approval operations require a human principal. A person may have multiple roles; separation of duties beyond these role checks is an organizational policy to configure before deployment. Tenant members can read their tenant's content and assessment records. Source text retrieval needs a resource administration/reviewer role, except specifically approved generation context. There is no per-document ACL within a tenant.

## Persistence sequence

1. A source administrator posts `/v1/resources/source`; a policy administrator posts `/v1/resources/policy`. Resources start `candidate`. Approve each exact current resource ID with `/v1/resources/{kind}/{id}/approve` and a reason/evidence. Only known tenant resource keys may appear in a brief.
2. The named owner posts `/v1/briefs`. The brief freezes purpose, acceptance criteria, profile, tier, market, language, policy key, source keys and requirements. Source/policy keys select their current governed versions at assessment time. A change to brief configuration means a new brief ID and new content version.
3. The platform posts `/v1/versions` with a stable `Idempotency-Key`, or sends multipart file bytes and JSON `metadata` to `/v1/uploads`. A single database transaction commits the immutable version, run, dependencies, planned examinations and durable job. If this transaction fails, none is committed. A successful response is HTTP 202.
4. Store the returned `asset_id`, `version_id`, `run_id`, `job_id`, `plan_hash` and caller event ID. Retries reuse the same idempotency key and exactly the same request. Reuse with different content receives 409. Idempotency is scoped to tenant, authenticated caller and operation. Do not switch principals during a retry.
5. The owner reads the original and planned inventory, then posts `/v1/runs/{run_id}/scope` with its exact `plan_hash`, `inventory_complete`, reason and evidence. The worker does not execute until this step. Revising the inventory or exclusions requires a new run/version rather than editing past results.
6. Poll `/v1/runs/{run_id}`. A completed job can still have unknown results or failed readiness. `awaiting_scope`, `queued` and `processing` require waiting or action. `failed` requires diagnosis and a new reassessment. `stale` requires following the asset's new `current_run_id` or submitting a correction. Outages leave the content a draft.
7. Review the exact original, machine results, passages and findings. Add scoped evidence and reviewer decisions. Each review response contains a new immutable snapshot ID/hash. Resolve unknown checks, all critical units, failed gates, major/critical findings and threshold failures. Record required specialist review after the final substantive review.
8. The owner posts `/v1/runs/{run_id}/approve` with current `snapshot_id`, `snapshot_hash`, reason and evidence. A successful response contains `approval_id`. The server rejects this operation until calculated readiness is complete.
9. At the release boundary, the named owner calls `/v1/assets/{asset_id}/release` with the exact `version_id`, `snapshot_id`, `snapshot_hash` and `approval_id`. The server atomically checks all current constraints and records a local release. A repeated valid request for the same approval returns its existing release. Old version/snapshot/approval tuples receive 409; wrong-tenant objects appear as 404.

Example submission (replace identifiers):

```json
{
  "brief_id": "YOUR_APPROVED_BRIEF_ID",
  "title": "Product warranty guidance",
  "format": "application/json",
  "origin": "created",
  "content": {
    "name": "Example device",
    "warranty": "two years",
    "support": "Contact support if the device fails."
  }
}
```

For edits, include `asset_id`, `expected_version_id` equal to the latest current version, and the updated content. Concurrent saves with the same expected version cannot both succeed. A translation/adaptation includes `derived_from_version_id` in the same tenant, and a new brief for its target language/market. Derivatives have additional mandatory manual source-to-target checks.

Uploads preserve original bytes. Direct string submissions preserve their UTF-8 bytes; object-valued JSON submissions use canonical JSON serialization. `content_hash` is SHA-256 of those persisted bytes. A delivered version must match these exact bytes or an explicitly assessed output representation. A downstream rendering or conversion that changes material meaning, layout or interaction needs its own declared examinations or new version.

## Status and decisions

The run response includes state, job attempts/errors, frozen plan/hash, evaluator versions, dependency metadata, current snapshot, owner approval and outer `release_eligible`. The immutable snapshot has rubric bounds/index, weighted rubric coverage, actual planned/completed counts, modality coverage, reasons, criterion results, checks, findings and evidence locators. `index_exact` contains the exact rational result; display values are not decision inputs.

`score.readiness` is calculated independently of final approval. Historic snapshots retain their historic readiness even when the run becomes stale. The run's outer `release_eligible` incorporates freshness and current approval. Neither field is a durable bearer authorization; the release endpoint is authoritative when recording release.

Machine-readable error responses contain `error.code`, a plain-language message and optional details. Invalid typed input receives 422 without echoing submitted values. Invalid/missing credentials receive 401, insufficient roles 403, unavailable/wrong-tenant objects 404, conflicts or release holds 409. Database failure can return 500/503; do not deliver on errors. Retry intake using the original idempotency key. Retry review only after fetching the current snapshot; review uses optimistic concurrency.

## Generated content and delivery

`GET /v1/generation-context/{brief_id}` supplies only source/policy versions permitted for `generation`. The executable demonstration uses a deterministic generator on this context; replace it with your platform's generator if appropriate. Keep generation and evaluation separate. Passing generated text back as a new factual authority is not supported.

If generated tokens reach a recipient before these checks and approval, that route is **monitoring**, not pre-delivery enforcement. For prevention, buffer the complete draft until the exact-version release succeeds. Streaming model calls are not implemented here.

The local release transaction does not atomically commit your external publisher's transaction. Your integration must bind publication to the returned exact version/hash, coordinate source-change events and final delivery, and implement an outbox or equivalent delivery protocol for your publishing system. A past release ID must not be cached indefinitely as permission to publish changed or stale content. Publishing coordination, withdrawal of already delivered material and content revocation in external systems remain integration work.

## Change propagation and executable clients

Source/policy updates and approval/revocation atomically schedule dependent current content for full reassessment; the response includes new run IDs. Workers detect source expiration and evaluator/rubric configuration changes. No completion webhook is implemented; poll run/asset status or tenant audit events using `after`/`next_after` cursors.

`examples/platform_client.py` submits real requests, polls, and can request release with an existing owner approval. It intentionally stops when owner scope action is needed; it never impersonates a reviewer. `assurance/demo.py` is the complete automated **fixture** lifecycle example and runs against a real loopback API. `assurance demo` orchestrates it with a separate worker.
