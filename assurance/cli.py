import argparse
import json
import os
import time
from pathlib import Path

from .auth import provision
from .db import Database, audit
from .settings import Settings
from .util import canonical

DEMO_ROLES = {
    "owner": ["submitter", "reviewer", "approver"],
    "reviewer": ["reviewer"],
    "specialist": ["reviewer", "specialist"],
    "admin": ["source_admin", "policy_admin"],
    "submitter": ["submitter"],
}


def init_demo(db, path):
    path = Path(path)
    if path.exists():
        raise ValueError("Demo credentials already exist; use a fresh demo directory.")
    path.parent.mkdir(parents=True, exist_ok=True)
    identities = {}
    for name, roles in DEMO_ROLES.items():
        pid, token = provision(db, "demo", "LOCAL DEMO " + name, roles, local_only=True)
        identities[name] = {"id": pid, "token": token}
    record = {
        "notice": "LOCAL DEVELOPMENT ONLY. Synthetic identities and scripted review fixtures, not real expert approval.",
        "identities": identities,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(record, f, indent=2)
    return str(path)


def main():
    parser = argparse.ArgumentParser(description="Content Assurance Service — provisional local pilot")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Apply migrations; optionally create explicit local demo credentials")
    init.add_argument("--demo", action="store_true")
    init.add_argument("--credentials", default="var/demo-credentials.json")
    serve = sub.add_parser("serve", help="Start the local API and generated reviewer documentation")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    worker = sub.add_parser("worker", help="Run the durable assessment worker")
    worker.add_argument("--once", action="store_true")
    user = sub.add_parser("user-add", help="Operator-only provisioning; prints a new bearer credential once")
    user.add_argument("--tenant", required=True)
    user.add_argument("--name", required=True)
    user.add_argument("--roles", required=True, help="Comma-separated roles")
    user.add_argument("--machine", action="store_true")
    user.add_argument("--local-only", action="store_true")
    revoke = sub.add_parser("user-revoke", help="Disable a principal credential and current release pointers")
    revoke.add_argument("principal_id")
    schema = sub.add_parser("openapi", help="Export generated API documentation")
    schema.add_argument("--output", default="docs/openapi.json")
    demo = sub.add_parser("demo", help="Run an isolated offline HTTP service + worker demonstration")
    demo.add_argument("--output", default="outputs/demo-report.json")
    demo.add_argument(
        "--keep", action="store_true", help="Keep the local demo database under var/ for inspection"
    )
    sub.add_parser(
        "smoke-live", help="Deliberately run a configured provider on synthetic public test content"
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    if args.command == "demo":
        from .demo import run_demo

        run_demo(Path(args.output), args.keep)
        return
    if args.command == "smoke-live":
        from .providers import ChatProvider, validate_comparisons, validate_extraction

        if settings.provider != "chat" or not settings.allow_external or not settings.provider_key:
            parser.error(
                "Live smoke requires CAS_PROVIDER=chat, CAS_ALLOW_EXTERNAL=true and explicit provider URL, model and key."
            )
        provider = ChatProvider(settings)
        items = [{"id": "smoke-item", "text": "The demonstration warranty lasts 24 months."}]
        sources = [{"id": "smoke-source", "text": items[0]["text"]}]
        claims = validate_extraction(provider.extract(items), items).claims
        compared = validate_comparisons(provider.compare(claims, sources), claims, sources)
        if not claims or any(c.outcome != "supported" for c in compared.comparisons):
            raise SystemExit(
                "Live smoke did not substantiate the simple synthetic example; integration is not verified."
            )
        print(
            canonical(
                {
                    "status": "live_transport_and_schema_smoke_passed",
                    "model": settings.provider_model,
                    "notice": "One synthetic smoke case does not validate model accuracy.",
                    "comparisons": compared.model_dump(),
                }
            )
        )
        return
    db = Database(settings.db)
    if args.command in {"init", "serve", "worker", "user-add", "user-revoke"}:
        db.migrate()
    if args.command == "init":
        if args.demo:
            if settings.mode != "local":
                parser.error("Demo identities can only be provisioned in local mode")
            print(
                "Local development credentials saved with private file permissions: "
                + init_demo(db, args.credentials)
            )
        else:
            print("Database migrations applied. No credentials were installed.")
    elif args.command == "user-add":
        pid, token = provision(
            db,
            args.tenant,
            args.name,
            args.roles.split(","),
            human=not args.machine,
            local_only=args.local_only,
        )
        print(
            json.dumps(
                {
                    "principal_id": pid,
                    "bearer_token": token,
                    "notice": "Store securely; the database retains only a hash.",
                },
                indent=2,
            )
        )
    elif args.command == "user-revoke":
        with db.write() as c:
            row = c.execute("SELECT * FROM principals WHERE id=?", (args.principal_id,)).fetchone()
            if not row:
                parser.error("Principal not found")
            c.execute("UPDATE principals SET active=0 WHERE id=?", (args.principal_id,))
            c.execute(
                "UPDATE assets SET released_id=NULL WHERE released_id IN (SELECT r.id FROM releases r JOIN approvals a ON a.id=r.approval_id WHERE a.actor_id=?)",
                (args.principal_id,),
            )
            audit(c, row["tenant_id"], "operator", "principal.revoked", args.principal_id, {})
        print("Credential revoked; previous decisions remain in the audit history.")
    elif args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port, log_level="warning")
    elif args.command == "worker":
        from .worker import Worker

        w = Worker(db, settings)
        if args.once:
            print(
                "One job processed."
                if w.once()
                else "No eligible jobs; drafts remain queued or await scope approval."
            )
        else:
            print(
                "Assessment worker running. Ctrl-C stops after the current process is interrupted.",
                flush=True,
            )
            try:
                while True:
                    if not w.once():
                        time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    elif args.command == "openapi":
        from .api import create_app

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(create_app(settings).openapi(), indent=2) + "\n")
        print("API schema saved: " + str(output))


if __name__ == "__main__":
    main()
