"""Orchestration that keeps irreversible actions behind deterministic gates."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .browser import ReviewRequired, linkedin_job_id
from .documents import generate, validate_manifest
from .models import Job, Preflight, State, SubmissionCheck
from .policy import answer_questions, evaluate, select_evidence
from .store import Store


class Adapter(Protocol):
    def submit(self, job: Job, answers: dict[str, str], folder: Path) -> str: ...


def validate_target(job: Job) -> None:
    if job.source == "linkedin" and linkedin_job_id(job.url) != job.source_id:
        raise ValueError("LinkedIn job identifier does not match the reviewed opportunity")


class Service:
    def __init__(self, store: Store, data: Path, adapters: dict[str, Adapter] | None = None):
        self.store, self.data = store, data
        self.adapters = adapters or {}

    def preflight(self, app_id: int, sources: set[str] | None = None) -> Preflight:
        """Inspect current local gates without reserving, browsing or generating documents.

        This is an advisory snapshot. Submission always repeats the authoritative checks.
        Provider sign-in, changed descriptions and newly discovered questions require the
        live adapter and cannot be promised by a local inspection.
        """
        row = self.store.application(app_id)
        job = Job.model_validate(row["job"])
        settings = self.store.settings()
        usage = self.store.daily_usage()
        checks: list[SubmissionCheck] = []

        def check(code: str, label: str, passed: bool, detail: str) -> None:
            checks.append(SubmissionCheck(code=code, label=label, passed=passed, detail=detail))

        check(
            "automation",
            "Automation permission",
            settings.automation_enabled,
            "Automation is enabled." if settings.automation_enabled else "Automation is paused.",
        )
        check(
            "quota",
            "Daily attempt budget",
            usage.remaining > 0,
            f"{usage.used}/{usage.limit} attempts used on {usage.day} (Europe/London); {usage.remaining} remaining.",
        )
        check(
            "state",
            "Application status",
            row["state"] == State.READY,
            "Prepared and ready."
            if row["state"] == State.READY
            else "Prepare pending records; reconcile uncertain attempts. Submitted records cannot be retried.",
        )
        permitted = job.source in (sources if sources is not None else self.adapters.keys())
        check(
            "adapter",
            "Submission integration",
            permitted,
            "A submission integration is configured."
            if permitted
            else "No submission integration; use manual hand-off.",
        )
        scope = job.source != "linkedin" or settings.linkedin_authorised
        check(
            "scope",
            "LinkedIn authorisation",
            scope,
            "Scope configured or not required for this source."
            if scope
            else "Configure the declared LinkedIn authorisation scope first.",
        )
        try:
            validate_target(job)
        except ValueError as exc:
            check("target", "Opportunity identity", False, str(exc))
        else:
            check(
                "target",
                "Opportunity identity",
                True,
                "The LinkedIn URL matches the reviewed identifier."
                if job.source == "linkedin"
                else "No LinkedIn identity check is required for this source.",
            )
        evaluation = None
        try:
            profile, revision = self.store.profile()
        except ValueError as exc:
            check("profile", "Candidate record", False, str(exc))
        else:
            check(
                "profile",
                "Candidate record",
                profile.confirmed,
                "Candidate facts confirmed."
                if profile.confirmed
                else "Confirm the candidate facts first.",
            )
            evaluation = evaluate(job, profile, settings)
            check(
                "policy",
                "Current fit and eligibility",
                evaluation.state == State.READY,
                f"Fit {evaluation.score}/100; route: {evaluation.state}. "
                + " ".join(evaluation.blockers),
            )
            check(
                "revision",
                "Prepared profile version",
                row["revision"] == revision,
                f"Prepared revision {row['revision']}; current revision {revision}.",
            )
            _, unresolved = answer_questions(job, profile)
            check(
                "questions",
                "Required questionnaire answers",
                not unresolved,
                "All known required questions have approved answers."
                if not unresolved
                else "Approve answers for: " + ", ".join(unresolved),
            )
            try:
                validate_manifest(row["manifest"], self.data / "documents" / str(app_id), revision)
                if job.cover_letter_required and "cover_pdf" not in row["manifest"]["files"]:
                    raise ValueError("Generate the required cover letter before submission")
            except (ValueError, OSError) as exc:
                check("documents", "Document integrity", False, str(exc))
            else:
                check(
                    "documents",
                    "Document integrity",
                    True,
                    "Current document files match their recorded hashes.",
                )
        return Preflight(
            checked_at=datetime.now(UTC).isoformat(),
            can_submit=all(item.passed for item in checks),
            evaluation=evaluation,
            checks=checks,
        )

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
        validate_target(job)
        folder = self.data / "documents" / str(app_id)
        validate_manifest(row["manifest"], folder, revision)
        if job.cover_letter_required and "cover_pdf" not in row["manifest"]["files"]:
            raise ValueError("Generate the required cover letter before submission")
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
