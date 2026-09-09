"""Minimal real HTTP integration client: submit, poll, and request exact release.

Run from the repository with `uv run python examples/platform_client.py --help`.
Human scope/review/approval operations happen in /docs or your own reviewer UI.
"""

import argparse
import json
import os
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--submission", type=Path, required=True, help="Submit JSON with a real approved brief_id"
    )
    parser.add_argument(
        "--idempotency-key", required=True, help="Stable caller-side event ID; reuse on network retries"
    )
    parser.add_argument(
        "--approval-id", help="Optional prior human approval; normally release is a later request"
    )
    args = parser.parse_args()
    token = os.environ.get("CAS_CLIENT_TOKEN")
    if not token:
        parser.error("Set CAS_CLIENT_TOKEN to an authorised credential")
    with httpx.Client(
        base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=15, trust_env=False
    ) as c:
        r = c.post(
            "/v1/versions",
            json=json.loads(args.submission.read_text()),
            headers={"Idempotency-Key": args.idempotency_key},
        )
        r.raise_for_status()
        submitted = r.json()
        print(json.dumps(submitted, indent=2))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            r = c.get("/v1/runs/" + submitted["run_id"])
            r.raise_for_status()
            run = r.json()
            if run["state"] == "awaiting_scope":
                print(
                    "Named owner must approve the frozen plan through the review API. Resume polling this run afterward."
                )
                return
            if run["state"] in {"completed", "failed", "stale"}:
                print(
                    json.dumps(
                        run["snapshot"]["score"] if run["snapshot"] else {"state": run["state"]}, indent=2
                    )
                )
                break
            time.sleep(1)
        else:
            raise TimeoutError("Assessment remains pending; keep the draft unreleased and resume polling.")
        if args.approval_id:
            snapshot = run["snapshot"]
            r = c.post(
                f"/v1/assets/{submitted['asset_id']}/release",
                json={
                    "version_id": submitted["version_id"],
                    "snapshot_id": snapshot["id"],
                    "snapshot_hash": snapshot["hash"],
                    "approval_id": args.approval_id,
                },
            )
            r.raise_for_status()
            print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()
