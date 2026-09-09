import json
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError

from .auth import authenticate
from .db import Database, check_audit
from .extraction import FORMATS
from .rubric import NOTICE, RUBRIC
from .schemas import (
    ApprovalResponse,
    BriefIn,
    EvidenceIn,
    Reason,
    ReleaseIn,
    ReleaseResponse,
    ResourceIn,
    ReviewIn,
    ReviewResponse,
    RunResponse,
    ScopeApproval,
    SnapshotDecision,
    SnapshotResponse,
    Submit,
    VersionAccepted,
)
from .service import DomainError, Service, authorize, fresh, get, head_resource, reject
from .settings import Settings

security = HTTPBearer(auto_error=False)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    settings.validate()
    db = Database(settings.db)
    service = Service(db, settings)

    @asynccontextmanager
    async def lifespan(app):
        db.migrate()
        yield

    app = FastAPI(
        title="Content Assurance Service",
        version="0.1.0",
        lifespan=lifespan,
        description=NOTICE
        + " Tenant comes from authenticated credentials. All pilot releases require an authenticated human owner. No external publishing integration.",
    )
    app.state.db, app.state.service, app.state.settings = db, service, settings

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            status_code=exc.status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # The default response includes submitted values, potentially private text.
        return JSONResponse(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "issues": [
                        {"loc": e["loc"], "type": e["type"], "message": e["msg"]} for e in exc.errors()
                    ],
                }
            },
            status_code=422,
        )

    def principal(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]):
        if not credentials or credentials.scheme.lower() != "bearer":
            raise HTTPException(401, "Bearer credential required", headers={"WWW-Authenticate": "Bearer"})
        with db.read() as c:
            p = authenticate(c, credentials.credentials, settings.mode)
        if not p:
            raise HTTPException(401, "Invalid credential", headers={"WWW-Authenticate": "Bearer"})
        return p

    Auth = Annotated[object, Depends(principal)]

    @app.get("/health", tags=["Operations"])
    def health():
        try:
            with db.read() as c:
                c.execute("SELECT version FROM schema_migrations").fetchone()
            return {
                "status": "ok",
                "mode": settings.mode,
                "provider": settings.provider,
                "method_status": "provisional",
            }
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.get("/v1/me", tags=["Identity"])
    def me(p: Auth):
        return {
            "id": p.id,
            "tenant_id": p.tenant_id,
            "name": p.name,
            "roles": sorted(p.roles),
            "human": p.human,
            "local_demo_identity": p.local_only,
        }

    @app.get("/v1/rubric", tags=["Configuration"])
    def rubric(p: Auth):
        return {"notice": NOTICE, "rubric": RUBRIC}

    @app.get("/v1/formats", tags=["Configuration"])
    def formats(p: Auth):
        return {
            "formats": FORMATS,
            "notice": "Text extraction is not full format assessment. Unsupported formats cannot release.",
        }

    @app.post("/v1/resources/{kind}", status_code=201, tags=["Sources and policies"])
    def resource_create(kind: str, data: ResourceIn, p: Auth):
        return service.put_resource(p, kind, data)

    @app.get("/v1/resources/{kind}/{key}", tags=["Sources and policies"])
    def resource_get(kind: str, key: str, p: Auth):
        with db.read() as c:
            if not p.roles & {"reviewer", "source_admin", "policy_admin"}:
                reject("ROLE_REQUIRED", "Review or resource administration role required.", 403)
            return head_resource(c, p.tenant_id, kind, key)

    @app.post("/v1/resources/{kind}/{resource_id}/approve", tags=["Sources and policies"])
    def resource_approve(kind: str, resource_id: str, data: Reason, p: Auth):
        return service.resource_decision(p, kind, resource_id, data, True)

    @app.post("/v1/resources/{kind}/{resource_id}/revoke", tags=["Sources and policies"])
    def resource_revoke(kind: str, resource_id: str, data: Reason, p: Auth):
        return service.resource_decision(p, kind, resource_id, data, False)

    @app.post("/v1/briefs", status_code=201, tags=["Intake"])
    def brief_create(data: BriefIn, p: Auth):
        return service.create_brief(p, data)

    @app.post("/v1/versions", status_code=202, tags=["Intake"], response_model=VersionAccepted)
    def version_create(data: Submit, p: Auth, idempotency_key: Annotated[str, Header()]):
        return service.submit(p, data, idempotency_key)

    @app.post("/v1/uploads", status_code=202, tags=["Intake"], response_model=VersionAccepted)
    async def upload(
        p: Auth,
        idempotency_key: Annotated[str, Header()],
        metadata: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
    ):
        try:
            body = json.loads(metadata)
            body["content"] = "[binary upload retained]"
            body["origin"] = "upload"
            data = Submit.model_validate(body)
        except (ValueError, TypeError, ValidationError):
            reject("INVALID_METADATA", "Metadata must be valid Submit JSON without content.", 422)
        raw = await file.read(settings.max_bytes + 1)
        # Synchronous persistence/extraction runs off the event loop.
        from starlette.concurrency import run_in_threadpool

        return await run_in_threadpool(service.submit, p, data, idempotency_key, raw)

    @app.get("/v1/versions/{version_id}", tags=["Intake"])
    def version_get(version_id: str, p: Auth):
        with db.read() as c:
            v = get(c, "versions", p.tenant_id, version_id)
            v.pop("raw")
            v["payload"] = json.loads(v["payload"])
            return v

    @app.get("/v1/versions/{version_id}/original", tags=["Intake"])
    def original(version_id: str, p: Auth):
        with db.read() as c:
            v = get(c, "versions", p.tenant_id, version_id)
            return Response(
                v["raw"],
                media_type="application/octet-stream",
                headers={
                    "Content-Disposition": 'attachment; filename="content-original"',
                    "X-Content-Type-Options": "nosniff",
                },
            )

    @app.get("/v1/assets/{asset_id}", tags=["Intake"])
    def asset_get(asset_id: str, p: Auth):
        with db.read() as c:
            a = get(c, "assets", p.tenant_id, asset_id)
            if a["current_run_id"]:
                run = get(c, "runs", p.tenant_id, a["current_run_id"])
                valid, reason = fresh(c, run, settings)
                if not valid:
                    a["released_id"] = None
                    a["stale_reason"] = reason
            return a

    @app.post("/v1/assets/{asset_id}/reassess", status_code=202, tags=["Assessment"])
    def reassess(asset_id: str, p: Auth):
        return service.reassess(p, asset_id)

    @app.get("/v1/runs/{run_id}", tags=["Assessment"], response_model=RunResponse)
    def run_get(run_id: str, p: Auth):
        return service.get_run(p, run_id)

    @app.get("/v1/review-queue", tags=["Review"])
    def review_queue(p: Auth, limit: int = 50):
        with db.read() as c:
            authorize(c, p, "reviewer", True)
            rows = c.execute(
                "SELECT r.id,r.asset_id,r.version_id,r.state,r.head_snapshot_id,a.title FROM runs r JOIN assets a ON a.current_run_id=r.id WHERE r.tenant_id=? ORDER BY r.created_at LIMIT ?",
                (p.tenant_id, max(1, min(limit, 200))),
            ).fetchall()
            return [dict(r) for r in rows]

    @app.get("/v1/runs/{run_id}/machine-results", tags=["Assessment"])
    def machine_results(run_id: str, p: Auth):
        with db.read() as c:
            authorize(c, p, "reviewer", True)
            get(c, "runs", p.tenant_id, run_id)
            row = c.execute(
                "SELECT * FROM machine_results WHERE run_id=? AND tenant_id=?", (run_id, p.tenant_id)
            ).fetchone()
            if not row:
                reject("ASSESSMENT_UNFINISHED", "Machine results are not yet available.")
            return {"hash": row["hash"], "created_at": row["created_at"], **json.loads(row["payload"])}

    @app.post("/v1/runs/{run_id}/scope", tags=["Review"])
    def scope(run_id: str, data: ScopeApproval, p: Auth):
        return service.scope(p, run_id, data)

    @app.post("/v1/runs/{run_id}/evidence", status_code=201, tags=["Review"])
    def evidence_add(run_id: str, data: EvidenceIn, p: Auth):
        return service.add_evidence(p, run_id, data)

    @app.get("/v1/runs/{run_id}/evidence", tags=["Review"])
    def evidence_get(run_id: str, p: Auth):
        with db.read() as c:
            get(c, "runs", p.tenant_id, run_id)
            records = c.execute(
                "SELECT * FROM evidence WHERE run_id=? AND tenant_id=? ORDER BY rowid", (run_id, p.tenant_id)
            ).fetchall()
            return [{**dict(r), "payload": json.loads(r["payload"])} for r in records]

    @app.get("/v1/runs/{run_id}/history", tags=["Review"])
    def history(run_id: str, p: Auth):
        with db.read() as c:
            get(c, "runs", p.tenant_id, run_id)
            return {
                "decisions": [
                    {**dict(d), "payload": json.loads(d["payload"])}
                    for d in c.execute("SELECT * FROM decisions WHERE run_id=? ORDER BY rowid", (run_id,))
                ],
                "snapshots": [
                    dict(s)
                    for s in c.execute(
                        "SELECT id,hash,created_at FROM snapshots WHERE run_id=? ORDER BY rowid", (run_id,)
                    )
                ],
            }

    @app.get("/v1/snapshots/{snapshot_id}", tags=["Assessment"], response_model=SnapshotResponse)
    def snapshot_get(snapshot_id: str, p: Auth):
        with db.read() as c:
            s = get(c, "snapshots", p.tenant_id, snapshot_id)
            return {"id": s["id"], "hash": s["hash"], **json.loads(s["payload"])}

    @app.post("/v1/runs/{run_id}/reviews", tags=["Review"], response_model=ReviewResponse)
    def review(run_id: str, data: ReviewIn, p: Auth):
        return service.review(p, run_id, data)

    @app.post("/v1/runs/{run_id}/specialist", tags=["Review"], response_model=ReviewResponse)
    def specialist(run_id: str, data: SnapshotDecision, p: Auth):
        return service.specialist(p, run_id, data)

    @app.post("/v1/runs/{run_id}/approve", tags=["Release"], response_model=ApprovalResponse)
    def approve(run_id: str, data: SnapshotDecision, p: Auth):
        return service.approve(p, run_id, data)

    @app.post("/v1/assets/{asset_id}/release", tags=["Release"], response_model=ReleaseResponse)
    def release(asset_id: str, data: ReleaseIn, p: Auth):
        return service.release(p, asset_id, data)

    @app.get("/v1/generation-context/{brief_id}", tags=["Generation"])
    def generation_context(brief_id: str, p: Auth):
        return service.generation_context(p, brief_id)

    @app.get("/v1/events", tags=["Audit"])
    def events(p: Auth, after: int = 0, limit: int = 100):
        with db.read() as c:
            authorize(c, p, "reviewer", True)
            rows = c.execute(
                "SELECT * FROM events WHERE tenant_id=? AND seq>? ORDER BY seq LIMIT ?",
                (p.tenant_id, max(0, after), max(1, min(limit, 500))),
            ).fetchall()
            return {
                "events": [{**dict(e), "payload": json.loads(e["payload"])} for e in rows],
                "chain_valid": check_audit(c, p.tenant_id),
                "next_after": rows[-1]["seq"] if rows else after,
            }

    return app


app = create_app()
