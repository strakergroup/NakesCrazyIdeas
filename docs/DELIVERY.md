# Delivery verification

The final build passed 90 automated tests, with one deliberately skipped live-provider smoke test. Lint and formatting checks passed. Generated OpenAPI documentation includes typed intake, run, score, snapshot, approval and release responses.

The complete offline demonstration passed against a real loopback HTTP API and a separate worker process. It also passed from the installable wheel in a separate virtual environment and working directory, verifying that rubric configuration and migrations are packaged and that the service does not depend on the source task's scratch files.

No live model credentials were configured. The real provider adapter remains unverified against an external provider; mocked HTTP checks and scripted fixtures are explicitly labelled. No company platform, SSO or publishing system was connected. No external deployment or publication was performed. The rubric remains provisional and uncalibrated.

Run `uv sync --frozen --python 3.12`, `uv run pytest -q`, and `uv run assurance demo` from the extracted source folder. See README.md for a persistent local API and worker, the reviewer workflow, credentials and deliberate live configuration.
