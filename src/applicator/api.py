"""Loopback API and dashboard. Every candidate operation requires a local token."""

import os
import secrets
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import Field

from .adviser import advise
from .browser import LinkedInBrowser
from .discovery import greenhouse
from .documents import validate_manifest
from .models import Contract, DailyUsage, Evidence, Job, Preflight, Profile, Settings, State
from .networking import Networking
from .service import Service
from .store import Store


class Preparation(Contract):
    evidence_ids: list[str] | None = None
    use_ai: bool = False


class Receipt(Contract):
    receipt: str = Field(min_length=1, max_length=1000)


class Outcome(Contract):
    outcome: Literal["interview", "offer", "rejected", "withdrawn", "no_response"]


class Board(Contract):
    board: str


class Connection(Contract):
    url: str = Field(max_length=2000)
    name: str = Field(min_length=1, max_length=150)
    role: str = Field(min_length=1, max_length=300)
    location: str = Field(min_length=1, max_length=150)


def local_token(data: Path) -> str:
    data.mkdir(parents=True, exist_ok=True)
    configured = os.getenv("APPLICATOR_TOKEN", "")
    if configured:
        if len(configured) < 32:
            raise ValueError("APPLICATOR_TOKEN must contain at least 32 characters")
        return configured
    path = data / "access-token"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    saved = path.read_text(encoding="utf-8").strip()
    if len(saved) < 32:
        raise ValueError("The saved local access token must contain at least 32 characters")
    return saved


def create_app(data: Path, token: str, *, worker: bool = False) -> FastAPI:
    store = Store(data / "applicator.sqlite3")
    service = Service(store, data)
    network = Networking(store, data)
    browser_lock = threading.Lock()
    stop = threading.Event()

    def configure_adapter() -> None:
        profile, _ = store.profile()
        service.adapters["linkedin"] = LinkedInBrowser(data, profile)

    def tick() -> dict[str, str]:
        with browser_lock:
            configure_adapter()
            settings = store.settings()
            if (
                settings.automation_enabled
                and settings.connections_enabled
                and settings.discovery_enabled
                and settings.linkedin_authorised
                and network.remaining()
            ):
                profile, _ = store.profile()
                contacts = LinkedInBrowser(data, profile).contacts(
                    settings.search_location, min(3, network.remaining())
                )
                for contact in contacts:
                    network.add(**contact)
            if settings.automation_enabled:
                if settings.discovery_enabled and settings.linkedin_authorised:
                    profile, _ = store.profile()
                    jobs = LinkedInBrowser(data, profile).search(
                        settings.search_keywords, settings.search_location
                    )
                    for job in jobs:
                        store.add_job(job)
                _, revision = store.profile()
                for row in store.applications():
                    if row["state"] == State.REVIEW and (
                        not row["evaluation"] or row["revision"] != revision
                    ):
                        try:
                            service.prepare(row["id"])
                        except ValueError as exc:
                            with store.connect() as db:
                                store.event(
                                    db, "preparation_review_required", str(exc)[:500], row["id"]
                                )
            result = service.tick()
            settings = store.settings()
            if settings.automation_enabled and settings.connections_enabled:
                for row in network.list():
                    if row["state"] == "queued":
                        try:
                            result[f"connection:{row['id']}"] = network.send(row["id"])
                        except Exception as exc:
                            result[f"connection:{row['id']}"] = type(exc).__name__
            return result

    def loop() -> None:
        while not stop.wait(store.settings().poll_seconds):
            try:
                tick()
            except Exception as exc:
                with store.connect() as db:
                    store.event(db, "worker_cycle_failed", type(exc).__name__)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        store.recover()
        thread = threading.Thread(target=loop, daemon=True) if worker else None
        if thread:
            thread.start()
        yield
        stop.set()
        if thread:
            thread.join(timeout=1)

    app = FastAPI(
        title="Autonomous Applicator",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.store, app.state.service, app.state.network = store, service, network

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> None:
        if not authorization or not secrets.compare_digest(
            authorization.encode(), f"Bearer {token}".encode()
        ):
            raise HTTPException(401, "A valid local access token is required")

    @app.middleware("http")
    async def security(request: Request, call_next: Any) -> Response:
        host = request.headers.get("host", "").split(":")[0]
        origin = request.headers.get("origin")
        expected = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if host not in {"127.0.0.1", "localhost", "testserver"} or (origin and origin != expected):
            return JSONResponse({"detail": "Untrusted Host or Origin"}, status_code=403)
        # Enforce the actual body size, including chunked requests and dishonest headers.
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 500_000:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; object-src 'none'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            }
        )
        return cast(Response, response)

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(KeyError)
    async def key_error(_request: Request, _exc: KeyError) -> JSONResponse:
        return JSONResponse({"detail": "Application or evidence not found"}, status_code=404)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    auth = [Depends(authenticate)]

    @app.get("/api/profile", dependencies=auth)
    def get_profile() -> dict[str, Any]:
        profile, revision = store.profile()
        return {"profile": profile.model_dump(), "revision": revision}

    @app.put("/api/profile", dependencies=auth)
    def put_profile(
        profile: Profile, if_match: Annotated[int | None, Header(ge=0)] = None
    ) -> dict[str, int]:
        return {"revision": store.save_profile(profile, if_match)}

    @app.post("/api/evidence", dependencies=auth)
    def add_evidence(evidence: Evidence) -> dict[str, int]:
        return {"revision": store.edit_evidence(evidence, evidence.id, create_only=True)}

    @app.put("/api/evidence/{evidence_id}", dependencies=auth)
    def update_evidence(evidence_id: str, evidence: Evidence) -> dict[str, int]:
        if evidence.id != evidence_id:
            raise ValueError("Evidence identifier must match the requested record")
        return {"revision": store.edit_evidence(evidence, evidence_id)}

    @app.delete("/api/evidence/{evidence_id}", dependencies=auth)
    def remove_evidence(evidence_id: str) -> dict[str, int]:
        return {"revision": store.edit_evidence(None, evidence_id)}

    @app.get("/api/settings", dependencies=auth)
    def get_settings() -> Settings:
        return store.settings()

    @app.put("/api/settings", dependencies=auth)
    def put_settings(settings: Settings) -> Settings:
        store.set_settings(settings)
        return settings

    @app.get("/api/applications", dependencies=auth)
    def applications() -> list[dict[str, Any]]:
        return store.applications()

    @app.get("/api/applications/{app_id}", dependencies=auth)
    def application(app_id: int) -> dict[str, Any]:
        return store.application(app_id)

    @app.get("/api/usage", dependencies=auth)
    def usage() -> DailyUsage:
        return store.daily_usage()

    @app.get("/api/applications/{app_id}/preflight", dependencies=auth)
    def preflight(app_id: int) -> Preflight:
        return service.preflight(app_id, {"linkedin"})

    @app.get("/api/applications/{app_id}/events", dependencies=auth)
    def application_events(app_id: int) -> list[dict[str, Any]]:
        return store.events(app_id)

    @app.post("/api/jobs", dependencies=auth)
    def add_job(job: Job) -> dict[str, Any]:
        app_id, created = store.add_job(job)
        return {"id": app_id, "created": created}

    @app.put("/api/applications/{app_id}/job", dependencies=auth)
    def update_job(app_id: int, job: Job) -> dict[str, str]:
        with browser_lock:
            store.update_job(app_id, job)
        return {"status": "updated"}

    @app.post("/api/discover/greenhouse", dependencies=auth)
    def discover_greenhouse(board: Board) -> dict[str, int]:
        try:
            with httpx.Client() as client:
                jobs = greenhouse(board.board, client)
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Job discovery failed; no applications were sent") from exc
        return {"imported": sum(store.add_job(job)[1] for job in jobs)}

    @app.post("/api/discover/linkedin", dependencies=auth)
    def discover_linkedin() -> dict[str, int]:
        settings = store.settings()
        if not settings.linkedin_authorised:
            raise ValueError("Configure the declared LinkedIn authorisation scope first")
        profile, _ = store.profile()
        with browser_lock:
            jobs = LinkedInBrowser(data, profile).search(
                settings.search_keywords, settings.search_location
            )
        return {"imported": sum(store.add_job(job)[1] for job in jobs)}

    @app.post("/api/applications/{app_id}/prepare", dependencies=auth)
    def prepare(app_id: int, preparation: Preparation) -> dict[str, Any]:
        selected = preparation.evidence_ids
        if preparation.use_ai:
            if not os.getenv("OPENAI_API_KEY"):
                raise HTTPException(
                    503, "Set a fresh OPENAI_API_KEY locally to enable the AI adviser"
                )
            profile, _ = store.profile()
            job = Job.model_validate(store.application(app_id)["job"])
            try:
                advice = advise(
                    OpenAI(timeout=30, max_retries=0),
                    profile,
                    job,
                    os.getenv("OPENAI_MODEL", "gpt-6.1-sol"),
                )
            except Exception as exc:
                raise HTTPException(
                    502, "AI advice failed; no documents or applications were sent"
                ) from exc
            selected = advice.evidence_ids
        with browser_lock:
            service.prepare(app_id, selected)
        return store.application(app_id)

    @app.post("/api/applications/{app_id}/submit", dependencies=auth)
    def submit(app_id: int) -> dict[str, str]:
        with browser_lock:
            configure_adapter()
            return {"receipt": service.submit(app_id)}

    @app.post("/api/applications/{app_id}/receipt", dependencies=auth)
    def receipt(app_id: int, receipt: Receipt) -> dict[str, str]:
        store.reconcile(app_id, receipt.receipt)
        return {"status": "submitted"}

    @app.post("/api/applications/{app_id}/outcome", dependencies=auth)
    def outcome(app_id: int, outcome: Outcome) -> dict[str, str]:
        store.outcome(app_id, outcome.outcome)
        return {"status": "recorded"}

    @app.get("/api/applications/{app_id}/documents/{key}", dependencies=auth)
    def document(app_id: int, key: str) -> FileResponse:
        row = store.application(app_id)
        _, revision = store.profile()
        if row["state"] in {State.SUBMITTED, State.SUBMITTING, State.UNCERTAIN}:
            revision = row["revision"]
        folder = data / "documents" / str(app_id)
        validate_manifest(row["manifest"], folder, revision)
        item = row["manifest"]["files"].get(key)
        if not item:
            raise KeyError(key)
        return FileResponse(folder / item["name"], filename=item["name"])

    @app.get("/api/events", dependencies=auth)
    def events() -> list[dict[str, Any]]:
        return store.events()

    @app.get("/api/insights", dependencies=auth)
    def insights() -> dict[str, Any]:
        rows = [row for row in store.applications() if row["state"] == State.SUBMITTED]
        outcomes = {
            key: sum(row["outcome"] == key for row in rows)
            for key in ("interview", "offer", "rejected", "no_response", "withdrawn")
        }
        message = (
            "Insufficient outcome evidence to suggest policy changes."
            if len(rows) < 20
            else "Review outcome patterns before proposing a candidate-approved change. No causal claims are made."
        )
        return {
            "submitted": len(rows),
            "outcomes": outcomes,
            "suggestion": message,
            "automatic_changes": False,
        }

    @app.get("/api/connections", dependencies=auth)
    def connections() -> list[dict[str, Any]]:
        return network.list()

    @app.post("/api/discover/contacts", dependencies=auth)
    def discover_contacts() -> dict[str, int]:
        settings = store.settings()
        if not settings.linkedin_authorised:
            raise ValueError("Configure the declared LinkedIn authorisation scope first")
        profile, _ = store.profile()
        with browser_lock:
            contacts = LinkedInBrowser(data, profile).contacts(settings.search_location)
        for contact in contacts:
            network.add(**contact)
        return {"reviewed": len(contacts)}

    @app.post("/api/connections", dependencies=auth)
    def add_connection(connection: Connection) -> dict[str, str]:
        network.add(**connection.model_dump())
        return {"status": "queued"}

    @app.post("/api/connections/{connection_id}/send", dependencies=auth)
    def send_connection(connection_id: int) -> dict[str, str]:
        with browser_lock:
            return {"receipt": network.send(connection_id)}

    @app.post("/api/worker/tick", dependencies=auth)
    def run_tick() -> dict[str, str]:
        return tick()

    app.mount(
        "/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dashboard"
    )
    return app
