# Model integration and evaluation

The build includes a real configurable HTTPS adapter and explicitly labelled offline fixtures. No live provider credentials were configured, and no live model results are claimed. The adapter's transport/schema contract was tested with deterministic HTTP responses; the full local demonstration used the fixture provider.

## Runtime choices

| Configuration | Behavior |
|---|---|
| `CAS_PROVIDER=disabled` | Default. No network request; candidate comparisons remain unknown with `PROVIDER_NOT_CONFIGURED`. |
| `CAS_PROVIDER=fixture` | Local mode only. Clearly labelled synthetic candidate extraction, exact-match comparisons and the scripted bounded-energy-claim contradiction. No inference/model-accuracy claim. |
| `CAS_PROVIDER=chat` | Uses the explicitly configured base URL, model and key via HTTPS Chat Completions. Requires `CAS_ALLOW_EXTERNAL=true` and owner-approved brief `allow_external_processing=true`. |

The one configured model handles both extraction and comparison. There is no undocumented small/large routing, bespoke training, vector store or cross-client learning. A future routing policy needs independent evaluation and a new evaluator version. Customer evidence remains in the tenant's governed source store.

The network adapter appends `/chat/completions` to the configured base URL. It sends `model`, system/user messages, `response_format: {type: json_schema, json_schema: {strict: true, ...}}`, and `max_completion_tokens: 12000`. Model selection is explicit and must support that contract. The implementation follows the official [Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs). Other compatible endpoints may require a separate adapter; compatibility is not inferred from the product name.

Requests disallow redirects and environment-proxy inheritance. The endpoint must be HTTPS without URL credentials, query or fragment. Neither the endpoint nor model is taken from document text or client submission. Source and content data are transmitted only after operator opt-in and named-owner approval for the brief. Keys, raw provider errors and secret-bearing exception text are not written to the audit log. Network retries are controlled by the durable worker; transient HTTP 429/5xx, timeout and network errors have bounded attempts.

## Strict candidate and evidence contracts

Stage one extracts candidate claim IDs, exact content-item IDs, local start/end offsets and quoted text. It must report every reviewed item and explicit extraction uncertainty. Unknown/duplicate item references, fabricated claim locations and missing item coverage fail validation. These are mechanical validation checks; they do not prove that extraction found every actual claim.

Stage two returns exactly one comparison for each candidate claim, using `supported`, `contradicted` or `insufficient_evidence`. Supported and contradicted outcomes require evidence. Every source ID must belong to the permitted source snapshot, every quote must match exactly, and offsets must be valid and end-exclusive. Missing/duplicate comparisons, invented sources, invented quotations, malformed JSON, unexpected properties, refusal and truncated output fail closed to unknown or failed processing. Confidence scores are not part of the schema and cannot authorize release.

Both sources and inspected content are serialized as untrusted data. System instructions explicitly prohibit following embedded requests to change policy, invent evidence, reveal secrets or approve content. The model is not given tools, credentials, release endpoints or the power to change rubric ratings. A malicious or erroneous provider can still return a semantically wrong but syntactically valid comparison; factual rubric judgments and final approval therefore remain human responsibilities.

Automatic model outcomes complete only candidate comparison examinations. They do not assign final E2/M1/M2 scores. A model contradiction creates a major review suggestion under primary criterion M2. Its original result is preserved even if a human later adjudicates it with a recorded reason and evidence. Source status and provenance are the only automatically assigned rubric ratings.

## Opt-in live smoke

Configure `CAS_PROVIDER`, `CAS_PROVIDER_URL`, `CAS_PROVIDER_MODEL`, `CAS_PROVIDER_API_KEY` and `CAS_ALLOW_EXTERNAL` deliberately, then run `uv run assurance smoke-live`. This explicitly invoked command sends only one built-in synthetic warranty example, without loading any tenant material. Alternatively, use `CAS_RUN_LIVE_SMOKE=1 uv run pytest -m live` with those same settings.

Both paths check actual transport, schema, content/source locators and a supported outcome for the simple example. A successful smoke is still not a validation of accuracy, model suitability or language/market coverage. It may incur the configured provider's normal usage charges. No smoke was executed against a live provider in this build.

## Evaluation before a client pilot

Keep the rubric's status provisional. Start with representative product information and support examples, natural errors, deliberately planted defects and legitimate equivalent reformulations. Include whole documents, not only extracted claims, and audit apparent passes for omissions. Split by independent document/source family to avoid near-duplicate leakage.

Have domain-qualified humans review independently and adjudicate disagreements. Measure criterion agreement, critical/major misses, false referrals, reviewer time and correction effort against the current workflow at the same scope. Report sample sizes and uncertainty separately by language, market, profile, tier and modality. The energy-bill example and exact quantity tests in this repository are transparent logic fixtures, not measured detection performance.

Tune weights, thresholds and model routing only on development data, then freeze the configuration and evaluate held-out representative content. Version any model, prompt, rule, scope or distribution change and rerun regressions. Reusing client material for benchmarks or model training requires separate permission; this service implements neither reuse nor training.
