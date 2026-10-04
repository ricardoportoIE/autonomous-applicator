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
from playwright.sync_api import Error as BrowserError
from pydantic import Field

from .adviser import advise
from .browser import LinkedInBrowser
from .discovery import greenhouse
from .documents import validate_manifest
from .models import (
    Advice,
    Contract,
    DailyUsage,
    Evidence,
    Job,
    Preflight,
    Profile,
    Question,
    Settings,
    State,
)
from .networking import Networking
from .photos import stored_photo
from .question_adviser import MODEL as QUESTION_MODEL
from .question_adviser import suggest_answer
from .routine_answers import RoutineSelection, select_routine_sources
from .service import PreparationError, Service
from .store import Store
from .workspace import server_owner


class Preparation(Contract):
    evidence_ids: list[str] | None = None
    use_ai: bool | None = None


class Receipt(Contract):
    receipt: str = Field(min_length=1, max_length=1000)


class Outcome(Contract):
    outcome: Literal["interview", "offer", "rejected", "withdrawn", "no_response"]


class Board(Contract):
    board: str


class LocationReview(Contract):
    location: str = Field(min_length=1, max_length=200)


class NotSent(Contract):
    checked: Literal[True]


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
    # Guard initial migrations too: networking recovery must not touch another
    # server's live invitation before the application's lifespan starts.
    with server_owner(data):
        store = Store(data / "applicator.sqlite3")
        network = Networking(store, data)

    def select_ai(profile: Profile, job: Job, metadata: dict[str, Any]) -> Advice:
        if not os.getenv("OPENAI_API_KEY"):
            raise PreparationError(
                "Set a fresh OPENAI_API_KEY locally to enable the AI adviser", 503
            )
        model = os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
        if model != "gpt-6.1-sol":
            raise PreparationError("Set OPENAI_MODEL=gpt-6.1-sol for document preparation", 503)
        try:
            with OpenAI(timeout=180, max_retries=0) as ai_client:
                return advise(ai_client, profile, job, model, metadata=metadata)
        except Exception as exc:
            raise PreparationError(
                "AI advice failed; no documents or applications were sent"
            ) from exc

    def select_question(profile: Profile, job: Job, question: Question) -> RoutineSelection:
        if (
            not os.getenv("OPENAI_API_KEY")
            or os.getenv("OPENAI_MODEL", QUESTION_MODEL) != QUESTION_MODEL
        ):
            raise ValueError("Configure gpt-6.1-sol for routine source selection")
        try:
            with OpenAI(timeout=180, max_retries=0) as ai_client:
                return select_routine_sources(ai_client, profile, job, question)
        except Exception as exc:
            raise ValueError(
                "Routine sources could not be verified; manual review is required"
            ) from exc

    service = Service(store, data, selector=select_ai, question_selector=select_question)
    browser_lock = threading.Lock()
    stop = threading.Event()

    def configure_adapter() -> None:
        profile, _ = store.profile()
        service.adapters["linkedin"] = LinkedInBrowser(data, profile)

    def tick() -> dict[str, str]:
        with service.operations.run("cycle") as operation, browser_lock:
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
                operation.progress(
                    "discovering_contacts", "Searching for authorised networking contacts."
                )
                contacts = LinkedInBrowser(data, profile).contacts(
                    settings.search_location,
                    network.remaining(),
                    exclude_urls={row["url"] for row in network.list()},
                )
                for contact in contacts:
                    network.add(**contact)
            if settings.automation_enabled:
                if settings.discovery_enabled and settings.linkedin_authorised:
                    profile, _ = store.profile()
                    operation.progress(
                        "discovering_jobs",
                        "Searching for new opportunities before processing the FIFO queue.",
                    )
                    jobs = LinkedInBrowser(data, profile).search(
                        settings.search_keywords, settings.search_location
                    )
                    for job in jobs:
                        store.add_job(job)
            result = service.tick(operation, stopping=stop.is_set)
            settings = store.settings()
            if settings.automation_enabled and settings.connections_enabled:
                for row in network.list():
                    if not store.settings().automation_enabled or stop.is_set():
                        break
                    if row["state"] == "queued":
                        operation.progress(
                            "networking",
                            "Processing the separate connection queue after the application queue.",
                            clear_application=True,
                        )
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
        with server_owner(data):
            store.recover()
            thread = threading.Thread(target=loop, daemon=True) if worker else None
            if thread:
                thread.start()
            try:
                yield
            finally:
                stop.set()
                if thread:
                    thread.join()

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
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; frame-ancestors 'none'; object-src 'none'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
            }
        )
        return cast(Response, response)

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(PreparationError)
    async def preparation_error(_request: Request, exc: PreparationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status_code)

    @app.exception_handler(KeyError)
    async def key_error(_request: Request, _exc: KeyError) -> JSONResponse:
        return JSONResponse(
            {"detail": "Application, evidence or connection not found"}, status_code=404
        )

    @app.exception_handler(BrowserError)
    async def browser_error(_request: Request, _exc: BrowserError) -> JSONResponse:
        return JSONResponse(
            {
                "detail": "The browser could not read or complete the LinkedIn operation. "
                "Check the dedicated browser session and the current page layout. "
                "Review any uncertain applications or invitations before retrying."
            },
            status_code=502,
        )

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

    @app.post("/api/applications/{app_id}/questions/{question_id}/suggest", dependencies=auth)
    def answer_idea(
        app_id: int, question_id: str, if_match: Annotated[int, Header(ge=1)]
    ) -> dict[str, Any]:
        profile, revision = store.profile()
        row = store.application(app_id)
        job = Job.model_validate(row["job"])
        questions = [
            *job.questions,
            *[Question.model_validate(item["question"]) for item in row["routine_answers"]],
        ]
        question = next((item for item in questions if item.id == question_id), None)
        if question is None:
            raise KeyError(question_id)
        if revision != if_match:
            raise ValueError("Candidate facts changed. Refresh before requesting an answer idea")
        if not profile.confirmed or question.sensitive:
            raise ValueError("Confirmed candidate facts and a non-sensitive question are required")
        if not os.getenv("OPENAI_API_KEY"):
            raise HTTPException(503, "Set OPENAI_API_KEY locally to generate an answer idea")
        if os.getenv("OPENAI_MODEL", QUESTION_MODEL) != QUESTION_MODEL:
            raise HTTPException(503, "Set OPENAI_MODEL=gpt-6.1-sol to generate an answer idea")
        try:
            with OpenAI(timeout=180, max_retries=0) as ai_client:
                idea = suggest_answer(ai_client, profile, job, question)
        except Exception as exc:
            raise HTTPException(
                502, "The AI answer idea could not be generated. No answer was changed or approved."
            ) from exc
        if store.profile()[1] != revision or store.application(app_id)["job"] != job.model_dump():
            raise ValueError(
                "Candidate facts or the question changed. Generate a fresh answer idea"
            )
        return {**idea.model_dump(), "model": QUESTION_MODEL, "profile_revision": revision}

    @app.post("/api/jobs", dependencies=auth)
    def add_job(job: Job) -> dict[str, Any]:
        app_id, created = store.add_job(job)
        return {"id": app_id, "created": created}

    @app.post("/api/applications/{app_id}/location-review", dependencies=auth)
    def review_location(
        app_id: int, review: LocationReview, if_match: Annotated[int, Header(ge=1)]
    ) -> dict[str, str]:
        with service.operations.run("location_review", app_id) as operation:
            store.confirm_location(app_id, if_match, review.location)
            operation.result("location_confirmed")
        return {"status": "confirmed"}

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
            try:
                jobs = LinkedInBrowser(data, profile).search(
                    settings.search_keywords, settings.search_location
                )
            except BrowserError as exc:
                raise HTTPException(
                    502,
                    "The browser could not read the LinkedIn job search. Check the dedicated "
                    "browser session and try again. No opportunities were imported or applications sent.",
                ) from exc
        return {"imported": sum(store.add_job(job)[1] for job in jobs)}

    @app.post("/api/applications/{app_id}/prepare", dependencies=auth)
    def prepare(app_id: int, preparation: Preparation) -> dict[str, Any]:
        with service.operations.run("prepare", app_id) as operation, browser_lock:
            service.prepare(
                app_id,
                preparation.evidence_ids,
                use_ai=preparation.use_ai,
                progress=operation.progress,
            )
            operation.result(store.application(app_id)["state"])
        return store.application(app_id)

    @app.post("/api/applications/{app_id}/submit", dependencies=auth)
    def submit(app_id: int) -> dict[str, str]:
        with service.operations.run("submit", app_id) as operation, browser_lock:
            configure_adapter()
            receipt = service.submit(app_id, progress=operation.progress)
            operation.result("submitted")
            return {"receipt": receipt}

    @app.post("/api/applications/{app_id}/receipt", dependencies=auth)
    def receipt(app_id: int, receipt: Receipt) -> dict[str, str]:
        store.reconcile(app_id, receipt.receipt)
        return {"status": "submitted"}

    @app.post("/api/applications/{app_id}/not-sent", dependencies=auth)
    def not_sent(
        app_id: int, confirmation: NotSent, if_match: Annotated[int, Header(ge=1)]
    ) -> dict[str, str]:
        with service.operations.run("reconcile", app_id) as operation:
            store.confirm_not_sent(app_id, if_match)
            operation.result("confirmed_not_sent")
        return {"status": "review"}

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

    @app.get("/api/connections/{connection_id}/photo", dependencies=auth)
    def connection_photo(connection_id: int) -> FileResponse:
        row = network.status(connection_id)
        path = stored_photo(data, row["url"])
        if path is None:
            raise HTTPException(404, "No local profile photo is available for this contact")
        return FileResponse(path, media_type="image/png")

    @app.post("/api/discover/contacts", dependencies=auth)
    def discover_contacts() -> dict[str, int]:
        settings = store.settings()
        if not settings.linkedin_authorised:
            raise ValueError("Configure the declared LinkedIn authorisation scope first")
        profile, _ = store.profile()
        with browser_lock:
            contacts = LinkedInBrowser(data, profile).contacts(
                settings.search_location,
                settings.daily_connection_limit,
                exclude_urls={row["url"] for row in network.list()},
            )
        for contact in contacts:
            network.add(**contact)
        return {"reviewed": len(contacts)}

    @app.post("/api/connections", dependencies=auth)
    def add_connection(connection: Connection) -> dict[str, str]:
        network.add(**connection.model_dump())
        return {"status": "queued"}

    @app.post("/api/connections/{connection_id}/send", dependencies=auth)
    def send_connection(connection_id: int) -> dict[str, str]:
        if not browser_lock.acquire(blocking=False):
            raise HTTPException(
                409, "The dedicated browser is busy. Wait for its current operation to finish."
            )
        try:
            return {"receipt": network.send(connection_id, manual=True)}
        finally:
            browser_lock.release()

    @app.get("/api/connections/{connection_id}/status", dependencies=auth)
    def connection_status(connection_id: int) -> dict[str, Any]:
        return network.status(connection_id)

    @app.post("/api/worker/tick", dependencies=auth)
    def run_tick() -> dict[str, str]:
        return tick()

    @app.get("/api/worker/status", dependencies=auth)
    def worker_status() -> dict[str, Any]:
        return service.operations.status()

    app.mount(
        "/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dashboard"
    )
    return app
