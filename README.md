# Content Assurance Service

A working standalone Python service that assesses immutable content versions, records evidence and human review, and enforces approval before recording a local release. It implements the supplied 24-criterion rubric, six dimensions, nine profiles, three consequence tiers and seven gates.

**This is a provisional pilot.** Weights and thresholds are uncalibrated operating assumptions. The index is not a probability of correctness. Offline model fixtures demonstrate workflow and arithmetic, not model accuracy. This service is not connected to a company platform, SSO or a publishing system.

## Run the complete demonstration

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). From this directory:

```sh
uv sync --frozen --python 3.12
uv run assurance demo
```

The demonstration starts a real loopback HTTP API and a separate worker process with an isolated SQLite database. It registers and approves synthetic sources, supplies approved context to a deterministic example generator, submits the draft, approves the frozen inventory, runs checks, shows a blocked premature approval, records explicitly simulated human reviews, releases the exact version, then revokes a source and verifies the old approval can no longer release. Both processes stop afterward. No external model or publishing service is called.

The report is written to `outputs/demo-report.json`. Use `uv run assurance demo --keep` to retain the database and private local development credentials in a unique `var/fixture-demo-*` directory for inspection. The default demo deletes that temporary data after execution.

## Run a persistent local API and worker

```sh
uv sync --frozen --python 3.12
uv run assurance init --demo
uv run assurance serve
```

In a second terminal, from the same directory:

```sh
uv run assurance worker
```

The defaults use `var/assurance.sqlite3`, bind to `127.0.0.1:8000`, and disable external model processing. Open [interactive API and reviewer documentation](http://127.0.0.1:8000/docs). The **Authorize** control accepts a bearer token from the private `var/demo-credentials.json` file. These distinct, randomly generated development identities are labelled `LOCAL DEMO` and are rejected when `CAS_MODE=production`. The app installs no credentials on startup. `init --demo` refuses to overwrite an existing credential file.

For fixture-assisted local checks, set `CAS_PROVIDER=fixture` in **both** terminals before starting the API and worker. Leave it `disabled` to inspect the missing-provider behavior and complete the necessary examinations through authenticated human review.

Use environment variables from `.env.example`; the CLI does **not** automatically load a `.env` file. Ensure the API and worker use identical database and evaluator settings. Nothing is deployed by these commands.

## Review and release

The owner first approves an immutable brief with purpose, audience, source keys, policy key, language, market, profile, tier and examination requirements. Saving content returns HTTP 202 and schedules a durable job in the same transaction. The job waits for the named owner to approve the exact frozen plan through `/v1/runs/{id}/scope`. Reviewers then use `/docs` to examine original content, results and evidence, submit decisions and resolve findings. Scope and source/policy approval are distinct from final release approval.

Read [the reviewer guide](docs/reviewer-guide.md) for the full API sequence. Final approval binds an authenticated named owner to the **current content version, assessment snapshot ID and snapshot hash**. A later review creates a new snapshot. An edit, dependency change or evaluator configuration change makes the previous approval unusable. A request to `/release` rechecks current readiness, dependencies and ownership within a serialized database transaction.

Only the local service release record is created. The integration must enforce this contract at its own persistence and delivery boundaries; see [the integration contract](docs/integration.md).

## Verify the software

```sh
uv run pytest -q
uv run ruff check assurance tests examples
uv run ruff format --check assurance tests examples
uv run assurance openapi
```

The acceptance mapping and verified results are in [validation.md](docs/validation.md). The generated schema is in `docs/openapi.json` and at `/openapi.json`. A live test is skipped unless deliberately enabled. The successful external integration path remains **unverified** because no provider credentials were configured for this build.

## Configure a real provider deliberately

The included adapter uses a configurable HTTPS Chat Completions endpoint with strict JSON Schema output, schema validation, exact quote/offset validation and explicit supported/contradicted/insufficient-evidence outcomes. It does not fall back to fixture results. Provider and model selection are explicit; no model is hard-coded or claimed to be calibrated.

Set these in the API and worker environments, using your own secret-management mechanism:

```sh
export CAS_PROVIDER=chat
export CAS_PROVIDER_URL=https://api.openai.com/v1
export CAS_PROVIDER_MODEL=YOUR_STRUCTURED_OUTPUT_CAPABLE_MODEL
export CAS_ALLOW_EXTERNAL=true
# Supply CAS_PROVIDER_API_KEY securely; no real key is included.
```

A brief must also have `allow_external_processing: true`, explicitly approved by its named owner. All retrieved sources must be approved for the relevant use, language, market and profile. The source text and content items are transmitted only when these checks and the operator settings allow it. Setting a key alone does not enable transmission.

After deliberate configuration, run a small synthetic transport/schema check:

```sh
uv run assurance smoke-live
# Alternatively:
CAS_RUN_LIVE_SMOKE=1 uv run pytest -q -m live
```

See [model evaluation and limitations](docs/models.md) for request details, data handling and evaluation requirements. A successful smoke test would verify a transport path and one simple example, not factual accuracy on client content.

## Contents and operating scope

| Component | Implementation |
|---|---|
| API | FastAPI; typed request schemas; generated OpenAPI and Swagger reviewer operations |
| Storage | SQLite WAL on a single host; migration ledger; append-only records and audit hash chain |
| Jobs | Atomic content-plus-job persistence; leases and renewal; retries; fenced completions; visible failures |
| Scoring | Exact rational arithmetic shared by worker, reviews and tests; immutable rubric seed and snapshots |
| Checks | Required fields/sections/text, approved and forbidden terms, source applicability, defined unit equivalence |
| Models | Explicit HTTPS provider adapter; two-stage candidate extraction and evidence comparison; labelled offline fixtures |
| Review | Exact evidence references, manual judgments, gates, specialist review, findings, resolutions and immutable history |
| Release | Authenticated owner approval and atomic checks of exact version, snapshot and current dependencies |

The native SQLite driver is intentional: the single-host pilot uses explicit `BEGIN IMMEDIATE` transactions to serialize release with all invalidating mutations. No broker or distributed locking system is required. Multi-host production storage requires a designed and tested migration; this repository does not claim PostgreSQL support.

Read [the executable specification](docs/specification.md), [format support](docs/formats.md), [production requirements](docs/operations.md), and the copied source handbook and architecture text in `docs/`. The service loads its own `assurance/config/rubric-1.0.json`; it has no runtime dependency on the originating task's files.
