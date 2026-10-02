"""Orchestration that keeps irreversible actions behind deterministic gates."""

from pathlib import Path
from typing import Protocol

from .browser import ReviewRequired
from .documents import generate, validate_manifest
from .models import Job, State
from .policy import answer_questions, evaluate, select_evidence
from .store import Store


class Adapter(Protocol):
    def submit(self, job: Job, answers: dict[str, str], folder: Path) -> str: ...


class Service:
    def __init__(self, store: Store, data: Path, adapters: dict[str, Adapter] | None = None):
        self.store, self.data = store, data
        self.adapters = adapters or {}

    def prepare(self, app_id: int, selected: list[str] | None = None) -> None:
        row = self.store.application(app_id)
        if row["state"] in {State.SUBMITTED, State.SUBMITTING, State.UNCERTAIN}:
            raise ValueError("This application is already submitted or needs reconciliation")
        job = Job.model_validate(row["job"])
        profile, revision = self.store.profile()
        evaluation = evaluate(job, profile, self.store.settings())
        manifest = {}
        if evaluation.evidence_ids and profile.confirmed:
            folder = self.data / "documents" / str(app_id)
            chosen = (
                selected
                if selected is not None
                else select_evidence(job, profile, evaluation.evidence_ids)
            )
            manifest = generate(profile, job, chosen, folder, revision)
        if not manifest and evaluation.state == State.READY:
            evaluation.state = State.REVIEW
            evaluation.blockers.append(
                "Documents require verified evidence and a confirmed profile."
            )
        self.store.prepare(
            app_id, revision, evaluation.model_dump_json(), evaluation.state, manifest
        )

    def submit(self, app_id: int) -> str:
        row = self.store.application(app_id)
        profile, revision = self.store.profile()
        job = Job.model_validate(row["job"])
        evaluation = evaluate(job, profile, self.store.settings())
        if evaluation.state != State.READY or row["state"] != State.READY:
            raise ValueError("Application does not pass current submission policy")
        if job.source not in self.adapters:
            raise ValueError("No permitted submission adapter; use manual hand-off")
        if job.source == "linkedin" and not self.store.settings().linkedin_authorised:
            raise ValueError("LinkedIn authorisation scope must be configured")
        folder = self.data / "documents" / str(app_id)
        validate_manifest(row["manifest"], folder, revision)
        answers, unresolved = answer_questions(job, profile)
        if unresolved:
            raise ValueError("Required questions remain unanswered")
        attempt = self.store.reserve(app_id, revision)
        try:
            receipt = self.adapters[job.source].submit(job, answers, folder)
            if not receipt.strip():
                raise ValueError("Provider did not return a confirmation receipt")
        except ReviewRequired as exc:
            self.store.hold(app_id, str(exc))
            raise
        except Exception:
            self.store.finish(app_id, attempt, None)
            raise
        self.store.finish(app_id, attempt, receipt)
        return receipt

    def tick(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if self.store.settings().automation_enabled:
            for row in self.store.applications():
                if row["state"] == State.READY:
                    try:
                        result[str(row["id"])] = self.submit(row["id"])
                    except Exception as exc:
                        result[str(row["id"])] = type(exc).__name__
        return result
