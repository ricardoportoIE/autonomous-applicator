"""Orchestration that keeps irreversible actions behind deterministic gates."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .browser import LinkedInBrowser, ReviewRequired, linkedin_job_id
from .documents import fingerprint, generate, validate_generation, validate_manifest
from .models import Advice, Job, Preflight, Profile, State, SubmissionCheck
from .operations import Operation, Operations
from .policy import answer_questions, evaluate, select_evidence
from .store import Store


class Adapter(Protocol):
    def submit(self, job: Job, answers: dict[str, str], folder: Path) -> str: ...


class PreparationError(ValueError):
    def __init__(self, detail: str, status_code: int = 502):
        super().__init__(detail)
        self.status_code = status_code


def validate_target(job: Job) -> None:
    if job.source == "linkedin" and linkedin_job_id(job.url) != job.source_id:
        raise ValueError("LinkedIn job identifier does not match the reviewed opportunity")


class Service:
    def __init__(
        self,
        store: Store,
        data: Path,
        adapters: dict[str, Adapter] | None = None,
        *,
        selector: Callable[[Profile, Job, dict[str, Any]], Advice] | None = None,
    ):
        self.store, self.data = store, data
        self.adapters = adapters or {}
        self.selector = selector
        self.operations = Operations(store)

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
            try:
                validate_generation(
                    row["manifest"], profile, job, require_ai=settings.ai_document_preparation
                )
            except ValueError as exc:
                check("generation", "Document preparation method", False, str(exc))
            else:
                check(
                    "generation",
                    "Document preparation method",
                    True,
                    "Verified gpt-6.1-sol selection for this candidate and opportunity."
                    if settings.ai_document_preparation
                    else "The configured preparation method is permitted.",
                )
        return Preflight(
            checked_at=datetime.now(UTC).isoformat(),
            can_submit=all(item.passed for item in checks),
            evaluation=evaluation,
            checks=checks,
        )

    def prepare(
        self,
        app_id: int,
        selected: list[str] | None = None,
        *,
        use_ai: bool | None = None,
        progress: Callable[[str, str], None] | None = None,
    ) -> None:
        if progress is None:
            with self.operations.run("prepare", app_id) as operation:
                self.prepare(app_id, selected, use_ai=use_ai, progress=operation.progress)
                operation.result(self.store.application(app_id)["state"])
            return
        report = progress
        report("evaluating", "Checking the opportunity against approved candidate facts.")
        row = self.store.application(app_id)
        if row["state"] in {State.SUBMITTED, State.SUBMITTING, State.UNCERTAIN}:
            raise ValueError("This application is already submitted or needs reconciliation")
        job = Job.model_validate(row["job"])
        profile, revision = self.store.profile()
        evaluation = evaluate(job, profile, self.store.settings())
        manifest = {}

        def hold_preparation(error: PreparationError) -> None:
            evaluation.state = State.REVIEW
            evaluation.blockers.append(str(error))
            self.store.prepare(
                app_id, revision, evaluation.model_dump_json(), State.REVIEW, {}, expected_job=job
            )
            with self.store.connect() as db:
                self.store.event(db, "preparation_review_required", str(error), app_id)

        if selected is not None and use_ai is True:
            raise ValueError(
                "Choose AI selection or explicit evidence identifiers, rather than both"
            )
        if evaluation.evidence_ids and profile.confirmed:
            folder = self.data / "documents" / str(app_id)
            chosen = selected
            metadata: dict[str, Any] = {"method": "manual" if selected is not None else "local"}
            ai_enabled = self.store.settings().ai_document_preparation if use_ai is None else use_ai
            if chosen is None and ai_enabled:
                report(
                    "selecting_evidence", "Selecting vacancy-specific evidence with GPT-6.1 Sol."
                )
                try:
                    if self.selector is None:
                        raise PreparationError(
                            "Configure the AI selection integration before preparing documents", 503
                        )
                    chosen = self.selector(profile, job, metadata).evidence_ids
                    validate_generation(
                        {
                            "generation": {
                                **metadata,
                                "profile_fingerprint": fingerprint(profile),
                                "job_fingerprint": fingerprint(job),
                            }
                        },
                        profile,
                        job,
                        require_ai=True,
                    )
                except PreparationError as exc:
                    hold_preparation(exc)
                    raise
                except ValueError as exc:
                    failure = PreparationError(
                        "AI preparation could not be verified; the application remains in review"
                    )
                    hold_preparation(failure)
                    raise failure from exc
            if chosen is None:
                chosen = select_evidence(job, profile, evaluation.evidence_ids)
            try:
                report(
                    "generating_documents",
                    "Generating and validating the vacancy-specific CV and required cover letter.",
                )
                manifest = generate(profile, job, chosen, folder, revision)
            except (ValueError, OSError) as exc:
                if metadata["method"] != "openai":
                    raise
                failure = PreparationError(
                    "AI-selected documents could not be validated; reduce or review the evidence"
                )
                hold_preparation(failure)
                raise failure from exc
            manifest["generation"] = {
                **metadata,
                "profile_fingerprint": fingerprint(profile),
                "job_fingerprint": fingerprint(job),
                "generated_at": datetime.now(UTC).isoformat(),
                "renderer_version": 2,
            }
        if not manifest and evaluation.state == State.READY:
            evaluation.state = State.REVIEW
            evaluation.blockers.append(
                "Documents require verified evidence and a confirmed profile."
            )
        report(
            "saving_documents",
            "Saving documents against the reviewed opportunity and profile revision.",
        )
        self.store.prepare(
            app_id,
            revision,
            evaluation.model_dump_json(),
            evaluation.state,
            manifest,
            expected_job=job,
        )

    def submit(self, app_id: int, *, progress: Callable[[str, str], None] | None = None) -> str:
        if progress is None:
            with self.operations.run("submit", app_id) as operation:
                receipt = self.submit(app_id, progress=operation.progress)
                operation.result("submitted")
                return receipt
        report = progress
        report(
            "checking_readiness",
            "Rechecking policy, approved answers, document hashes and AI provenance.",
        )
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
        validate_generation(
            row["manifest"],
            profile,
            job,
            require_ai=self.store.settings().ai_document_preparation,
        )
        if job.cover_letter_required and "cover_pdf" not in row["manifest"]["files"]:
            raise ValueError("Generate the required cover letter before submission")
        answers, unresolved = answer_questions(job, profile)
        if unresolved:
            raise ValueError("Required questions remain unanswered")
        report(
            "reserving_attempt",
            "Reserving one daily attempt before accessing the application form.",
        )
        attempt = self.store.reserve(app_id, revision)
        adapter = self.adapters[job.source]
        previous_progress = adapter.progress if isinstance(adapter, LinkedInBrowser) else None
        if isinstance(adapter, LinkedInBrowser):
            adapter.profile = profile
            adapter.progress = progress
        try:
            report(
                "opening_opportunity", "Opening the reviewed opportunity in the dedicated browser."
            )
            receipt = adapter.submit(job, answers, folder)
            if not receipt.strip():
                raise ValueError("Provider did not return a confirmation receipt")
            report(
                "recording_confirmation", "Recording the provider's confirmed submission receipt."
            )
            self.store.finish(app_id, attempt, receipt)
        except ReviewRequired as exc:
            self.store.hold(app_id, str(exc))
            raise
        except Exception:
            self.store.finish(app_id, attempt, None)
            raise
        finally:
            if isinstance(adapter, LinkedInBrowser):
                adapter.progress = previous_progress
        return receipt

    def tick(
        self, operation: Operation | None = None, *, stopping: Callable[[], bool] | None = None
    ) -> dict[str, str]:
        """Process a FIFO snapshot, completing each vacancy before starting the next."""
        if operation is None:
            with self.operations.run("cycle") as owned:
                return self.tick(owned, stopping=stopping)
        result: dict[str, str] = {}
        if not self.store.settings().automation_enabled:
            operation.completion_status = "paused"
            return result
        for candidate in sorted(self.store.applications(), key=lambda row: row["id"]):
            if stopping and stopping():
                operation.completion_status = "stopped"
                break
            if not self.store.settings().automation_enabled:
                operation.completion_status = "paused"
                break
            if not self.store.daily_usage().remaining:
                operation.completion_status = "limit_reached"
                break
            row = self.store.application(candidate["id"])
            _, revision = self.store.profile()
            stale = row["revision"] != revision or not row["evaluation"]
            if row["state"] not in {State.REVIEW, State.READY} or (
                row["state"] == State.REVIEW and not stale
            ):
                continue
            app_id = row["id"]
            operation.progress(
                "evaluating", "Starting the next opportunity in order of arrival.", app_id
            )
            try:
                if stale or row["state"] == State.REVIEW:
                    self.prepare(app_id, progress=operation.progress)
                if stopping and stopping():
                    operation.result(self.store.application(app_id)["state"])
                    operation.completion_status = "stopped"
                    break
                if not self.store.settings().automation_enabled:
                    operation.result(self.store.application(app_id)["state"])
                    operation.completion_status = "paused"
                    break
                row = self.store.application(app_id)
                if row["state"] != State.READY:
                    operation.result(row["state"])
                    continue
                result[str(app_id)] = self.submit(app_id, progress=operation.progress)
                operation.result("submitted")
            except Exception as exc:
                result[str(app_id)] = type(exc).__name__
                row = self.store.application(app_id)
                if row["state"] == State.READY or (
                    row["state"] == State.REVIEW
                    and (row["revision"] != self.store.profile()[1] or not row["evaluation"])
                ):
                    # Persist a current-revision hold: a later cycle must not retry this failure.
                    profile, revision = self.store.profile()
                    evaluation = evaluate(
                        Job.model_validate(row["job"]), profile, self.store.settings()
                    )
                    evaluation.state = State.REVIEW
                    evaluation.blockers.append(
                        "Processing failed; inspect the recorded stage before retrying manually."
                    )
                    self.store.prepare(
                        app_id,
                        revision,
                        evaluation.model_dump_json(),
                        State.REVIEW,
                        row["manifest"],
                        expected_job=Job.model_validate(row["job"]),
                    )
                operation.result(self.store.application(app_id)["state"], type(exc).__name__)
        return result
