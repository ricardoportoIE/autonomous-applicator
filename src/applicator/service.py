"""Orchestration that keeps irreversible actions behind deterministic gates."""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from .answer_style import experience_target, format_known_answer, numeric_field
from .browser import (
    FixtureBrowser,
    LinkedInBrowser,
    QuestionnaireReview,
    ReviewRequired,
    linkedin_job_id,
)
from .documents import fingerprint, generate, validate_generation, validate_manifest
from .models import Advice, Job, Preflight, Profile, Question, State, SubmissionCheck
from .operations import Operation, Operations
from .policy import answer_compatible, answer_questions, evaluate, select_evidence
from .question_adviser import question_key
from .question_library import InstructionGenerator, instruction_compatible, label_key, rule_source
from .routine_answers import RoutineSelection, Selector, routine_answer
from .store import Store
from .submission_records import SubmissionRecords


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
        question_selector: Selector | None = None,
        instruction_generator: InstructionGenerator | None = None,
    ):
        self.store, self.data = store, data
        self.adapters = adapters or {}
        self.selector = selector
        self.question_selector = question_selector
        self.instruction_generator = instruction_generator
        self.operations = Operations(store)
        self.records = SubmissionRecords(store, data)

    def screen_discovery(
        self, jobs: list[Job], progress: Callable[[str, str], None] | None = None
    ) -> dict[str, int]:
        profile, revision = self.store.profile()
        if not profile.confirmed:
            raise ValueError("Confirm candidate facts before screening discoveries")
        settings = self.store.settings()
        assessed = []
        for job in jobs:
            evaluation = evaluate(job, profile, settings)
            if progress:
                progress(
                    "screening_discovered_job",
                    f"{job.title} at {job.company}: fit {evaluation.score}/100. Discovery minimum: 50.",
                )
            assessed.append((job, evaluation))
        return self.store.screen_discovery(assessed, revision, settings)

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
            "Daily sent-application budget",
            usage.remaining > 0,
            f"{usage.used}/{usage.limit} applications sent on {usage.day} (Europe/London); "
            f"{usage.held} pending or uncertain; {usage.remaining} sending slots remaining. Preparation may continue.",
        )
        check(
            "state",
            "Application status",
            row["state"] == State.READY,
            "Prepared and ready."
            if row["state"] == State.READY
            else "Review hold: " + " ".join(row["evaluation"]["blockers"])
            if row["state"] == State.REVIEW and row["evaluation"].get("blockers")
            else "Prepare pending records; reconcile uncertain attempts. Submitted records cannot be retried.",
        )
        if row["trashed"]:
            check(
                "trash",
                "Removed from the queue",
                False,
                "Restore this opportunity from Trash before preparing or submitting it.",
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
            effective = self.store.effective_profile(app_id, profile, job)
            evaluation = self.store.management.evaluation(app_id, effective, job, settings)
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
            _, unresolved = answer_questions(job, effective)
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
        if row["trashed"]:
            raise ValueError("Restore this application from Trash before preparing it")
        if row["state"] in {State.SUBMITTED, State.SUBMITTING, State.UNCERTAIN}:
            raise ValueError("This application is already submitted or needs reconciliation")
        job = Job.model_validate(row["job"])
        profile, revision = self.store.profile()
        for question in job.questions:
            self.store.question_library.observe(app_id, question)
        instruction_failures: list[str] = []
        if self.store.settings().routine_answers_enabled and profile.confirmed:
            for question in job.questions:
                report(
                    "answering_routine_questions",
                    "Resolving routine questions from approved facts.",
                )
                try:
                    self.resolve_question(app_id, profile, revision, job, question, progress=report)
                except ValueError as exc:
                    if self.store.question_library.candidates(question):
                        instruction_failures.append(question.label)
                    with self.store.connect() as db:
                        self.store.event(db, "routine_question_review", type(exc).__name__, app_id)
        effective = self.store.effective_profile(app_id, profile, job)
        evaluation = self.store.management.evaluation(app_id, effective, job, self.store.settings())
        if instruction_failures:
            evaluation.state = State.REVIEW
            evaluation.blockers.extend(
                "Question instruction requires review: " + label for label in instruction_failures
            )
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

    def refresh_readiness(self, app_id: int) -> None:
        """Resume an explicit review decision while retaining valid prepared materials."""
        row = self.store.application(app_id)
        profile, revision = self.store.profile()
        job = Job.model_validate(row["job"])
        settings = self.store.settings()
        evaluation = self.store.management.evaluation(
            app_id, self.store.effective_profile(app_id, profile, job), job, settings
        )
        try:
            validate_manifest(row["manifest"], self.data / "documents" / str(app_id), revision)
            validate_generation(
                row["manifest"], profile, job, require_ai=settings.ai_document_preparation
            )
            if job.cover_letter_required and "cover_pdf" not in row["manifest"]["files"]:
                raise ValueError("Required cover letter needs preparation")
        except (ValueError, OSError):
            if evaluation.state != State.SKIPPED:
                evaluation.state = State.REVIEW
                evaluation.preparation_pending = True
                evaluation.blockers.append(
                    "Documents need preparation for the current candidate and opportunity."
                )
        self.store.prepare(
            app_id,
            revision,
            evaluation.model_dump_json(),
            evaluation.state,
            row["manifest"],
            expected_job=job,
        )

    def recoverable_form_hold(self, app_id: int) -> bool:
        if not self.store.form_recovery_available(app_id):
            return False
        report = self.preflight(app_id)
        return all(
            check.passed for check in report.checks if check.code not in {"state", "automation"}
        )

    def queue_pending(self) -> bool:
        """Whether existing FIFO records can progress without another discovery pass."""
        _, revision = self.store.profile()
        capacity = self.store.daily_usage().remaining
        return any(
            (row["state"] == State.READY and capacity > 0)
            or (
                row["state"] == State.REVIEW
                and (
                    row["revision"] != revision
                    or not row["evaluation"]
                    or row["evaluation"].get("preparation_pending", False)
                    or self.recoverable_form_hold(row["id"])
                )
            )
            for row in self.store.applications()
            if not row["trashed"]
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
        if row["trashed"]:
            raise ValueError("Applications in Trash cannot be submitted")
        profile, revision = self.store.profile()
        job = Job.model_validate(row["job"])
        effective = self.store.effective_profile(app_id, profile, job)
        evaluation = self.store.management.evaluation(app_id, effective, job, self.store.settings())
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
        answers, unresolved = answer_questions(job, effective)
        if unresolved:
            raise ValueError("Required questions remain unanswered")
        report(
            "reserving_attempt",
            "Holding one sending slot until confirmation or a proven pre-submission stop.",
        )
        attempt = self.store.reserve(app_id, revision)
        try:
            self.records.begin(app_id, attempt, effective, revision, job, row["manifest"], answers)
        except Exception:
            self.store.hold(
                app_id,
                "Submission materials could not be archived; no provider action was started.",
                attempt=attempt,
            )
            raise
        adapter = self.adapters[job.source]
        submission_folder = self.records.folder(app_id, attempt) / "documents"
        previous_observer = (
            adapter.observe_fields
            if isinstance(adapter, (LinkedInBrowser, FixtureBrowser))
            else None
        )
        previous_folder = (
            adapter.confirmation_folder
            if isinstance(adapter, (LinkedInBrowser, FixtureBrowser))
            else None
        )
        previous_evidence = (
            adapter.confirmation_evidence
            if isinstance(adapter, (LinkedInBrowser, FixtureBrowser))
            else {}
        )
        if isinstance(adapter, (LinkedInBrowser, FixtureBrowser)):
            adapter.observe_fields = lambda fields: self.records.observe(app_id, attempt, fields)
            adapter.confirmation_folder = self.records.folder(app_id, attempt)
            adapter.confirmation_evidence = {}
        previous_progress = adapter.progress if isinstance(adapter, LinkedInBrowser) else None
        previous_resolver = (
            adapter.question_resolver if isinstance(adapter, LinkedInBrowser) else None
        )
        previous_question_observer = (
            adapter.question_observer if isinstance(adapter, LinkedInBrowser) else None
        )
        previous_before_submit = (
            adapter.before_submit if isinstance(adapter, LinkedInBrowser) else None
        )
        pending_question: Question | None = None
        if isinstance(adapter, LinkedInBrowser):
            adapter.profile = (
                profile.model_copy(
                    update={"answers": {**profile.answers, **row["approved_answers"]}}
                )
                if any(item["enabled"] for item in self.store.question_library.entries())
                else effective
            )
            adapter.progress = progress

            def observe_question(question: Question) -> None:
                self.store.question_library.observe(app_id, question)

            adapter.question_observer = observe_question

            def final_gate() -> None:
                validate_manifest(row["manifest"], submission_folder, revision)
                self.store.mark_sending(app_id, attempt, revision, job)

            adapter.before_submit = final_gate

            def resolve_live(question: Question) -> str | None:
                nonlocal pending_question
                # Retain the observed question even if the interpreter raises.
                pending_question = question
                report(
                    "answering_routine_questions",
                    f"Checking approved answers for: {question.label}. Offered choices: {len(question.choices)}.",
                )
                try:
                    answer = self.resolve_question(
                        app_id, profile, revision, job, question, progress=report
                    )
                except ValueError as exc:
                    with self.store.connect() as db:
                        self.store.event(
                            db,
                            "routine_question_review",
                            f"{question.id}: {type(exc).__name__}",
                            app_id,
                        )
                    raise ReviewRequired("Approve an exact answer for: " + question.label) from exc
                if answer is not None:
                    pending_question = None
                return answer

            adapter.question_resolver = resolve_live
        try:
            report(
                "opening_opportunity", "Opening the reviewed opportunity in the dedicated browser."
            )
            receipt = adapter.submit(job, answers, submission_folder)
            if not receipt.strip():
                raise ValueError("Provider did not return a confirmation receipt")
            report(
                "recording_confirmation", "Recording the provider's confirmed submission receipt."
            )
            self.store.finish(app_id, attempt, receipt)
        except ReviewRequired as exc:
            self.store.hold(
                app_id,
                str(exc),
                attempt=attempt,
                question=pending_question,
                questions=exc.questions if isinstance(exc, QuestionnaireReview) else None,
            )
            raise
        except Exception:
            self.store.finish(app_id, attempt, None)
            raise
        finally:
            if isinstance(adapter, LinkedInBrowser) and adapter.form_diagnostic:
                try:
                    with self.store.connect() as db:
                        for evidence in adapter.form_diagnostics_evidence or [
                            adapter.form_diagnostic
                        ]:
                            self.store.event(db, "form_diagnostic", json.dumps(evidence), app_id)
                except Exception as exc:
                    # Diagnostic storage must not replace the original provider outcome.
                    logging.getLogger(__name__).warning(
                        "Form diagnostic journal unavailable: %s", type(exc).__name__
                    )
            if isinstance(adapter, (LinkedInBrowser, FixtureBrowser)):
                if self.store.application(app_id)["state"] == State.SUBMITTED:
                    try:
                        self.records.confirmation(app_id, attempt, adapter.confirmation_evidence)
                    except Exception as exc:
                        with self.store.connect() as db:
                            self.store.event(
                                db, "confirmation_evidence_unavailable", type(exc).__name__, app_id
                            )
                adapter.observe_fields = previous_observer
                adapter.confirmation_folder = previous_folder
                adapter.confirmation_evidence = previous_evidence
            if isinstance(adapter, LinkedInBrowser):
                adapter.progress = previous_progress
                adapter.question_resolver = previous_resolver
                adapter.question_observer = previous_question_observer
                adapter.before_submit = previous_before_submit
        return receipt

    def resolve_question(
        self,
        app_id: int,
        profile: Profile,
        revision: int,
        job: Job,
        question: Question,
        *,
        progress: Callable[[str, str], None] | None = None,
    ) -> str | None:
        self.store.question_library.observe(app_id, question)
        if not self.store.settings().routine_answers_enabled:
            return None
        row = self.store.application(app_id)
        if self.store.profile()[1] != revision or row["job"] != job.model_dump():
            raise ValueError("Candidate or opportunity changed before resolving a routine question")
        if not profile.confirmed or question.sensitive:
            return None
        effective = self.store.effective_profile(app_id, profile, job)
        key = question_key(question)
        approved = {**profile.answers, **row["approved_answers"]}.get(key)
        if approved:
            formatted = format_known_answer(question, approved)
            if formatted and answer_compatible(question, formatted):
                return formatted
            # Retain established deterministic contact/sponsorship mappings without
            # asking the model to reinterpret an incompatible approval.
            grounded = profile.model_copy(
                update={"answers": {**profile.answers, **row["approved_answers"]}}
            )
            known = routine_answer(grounded, job, question)
            if known is not None:
                self.store.save_routine_answer(
                    app_id, question, known.answer, known.source, known.evidence_ids, revision, job
                )
                return known.answer
            # An exact owner instruction can supply a previously missing duration.
            # Do not reinterpret an explicit number rejected by current constraints,
            # a different question's instruction or an exceptional personal fact.
            if (
                formatted is not None
                or not numeric_field(question)
                or experience_target(question) is None
                or not any(
                    rule["label_key"] == label_key(question.label)
                    for rule in self.store.question_library.candidates(question)
                )
            ):
                return None
        rules = self.store.question_library.candidates(question)
        if rules and profile.confirmed and not question.sensitive:
            cached_rule = next(
                (
                    item
                    for item in row["routine_answers"]
                    if item["answer_key"] == key
                    and item["source"] in {rule_source(rule, question) for rule in rules}
                ),
                None,
            )
            if cached_rule and instruction_compatible(question, cached_rule["answer"]):
                return str(cached_rule["answer"])
            if self.instruction_generator is None:
                raise ValueError("Configure GPT-6.1 Sol to use saved question instructions")
            if progress:
                progress(
                    "answering_routine_questions",
                    f"GPT-6.1 Sol is checking saved instructions for: {question.label}.",
                )
            # Generated/default answers are not confirmed facts for another rule.
            grounded = profile.model_copy(
                update={"answers": {**profile.answers, **row["approved_answers"]}}
            )
            result = self.instruction_generator(grounded, job, question, rules)
            if [(item["id"], item["version"]) for item in rules] != [
                (item["id"], item["version"])
                for item in self.store.question_library.candidates(question)
            ]:
                raise ValueError("Question instructions changed while generating the answer")
            if result.needs_review:
                raise ValueError("The saved question instructions require manual review")
            if result.rule_id is not None:
                rule = next((item for item in rules if item["id"] == result.rule_id), None)
                if rule is None or not instruction_compatible(question, result.answer):
                    raise ValueError("The saved instruction did not produce a valid answer")
                self.store.save_routine_answer(
                    app_id,
                    question,
                    result.answer,
                    rule_source(rule, question),
                    result.evidence_ids,
                    revision,
                    job,
                )
                return result.answer
            if any(item["label_key"] == label_key(question.label) for item in rules):
                raise ValueError("The configured question instruction could not be applied")
        defaults = frozenset(
            item["answer_key"]
            for item in row["routine_answers"]
            if item["source"] == "candidate_technology_policy"
            and item["answer_key"] not in profile.answers
            and item["answer_key"] not in row["approved_answers"]
            and effective.answers.get(item["answer_key"]) == item["answer"]
        )
        cached = effective.answers.get(question_key(question))
        if cached:
            formatted = format_known_answer(question, cached)
            if formatted and answer_compatible(question, formatted):
                return formatted
        selector = self.question_selector
        if selector is not None:

            def select_question(
                candidate: Profile, vacancy: Job, item: Question
            ) -> RoutineSelection:
                if progress is not None:
                    control = (
                        item.form_context.control_type
                        if item.form_context is not None
                        else "narrative"
                    )
                    progress(
                        "answering_routine_questions",
                        f"GPT-6.1 Sol is interpreting the {control} question: {item.label}.",
                    )
                return selector(candidate, vacancy, item)

            tracked_selector: Selector | None = select_question
        else:
            tracked_selector = None
        resolution = routine_answer(
            effective, job, question, tracked_selector, technology_defaults=defaults
        )
        if resolution is None:
            return None
        self.store.save_routine_answer(
            app_id,
            question,
            resolution.answer,
            resolution.source,
            resolution.evidence_ids,
            revision,
            job,
        )
        return resolution.answer

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
            if candidate["trashed"]:
                continue
            if stopping and stopping():
                operation.completion_status = "stopped"
                break
            if not self.store.settings().automation_enabled:
                operation.completion_status = "paused"
                break
            row = self.store.application(candidate["id"])
            _, revision = self.store.profile()
            stale = (
                row["revision"] != revision
                or not row["evaluation"]
                or row["evaluation"].get("preparation_pending", False)
            )
            recoverable = row["state"] == State.REVIEW and self.recoverable_form_hold(row["id"])
            if row["state"] not in {State.REVIEW, State.READY} or (
                row["state"] == State.REVIEW and not stale and not recoverable
            ):
                continue
            app_id = row["id"]
            operation.progress(
                "evaluating", "Starting the next opportunity in order of arrival.", app_id
            )
            try:
                if recoverable:
                    if not self.store.form_recovery_available(app_id, claim=True):
                        operation.result("review")
                        continue
                    operation.progress(
                        "recovering_form",
                        "Resuming a proven pre-submission technical stop with verified existing documents.",
                    )
                    self.refresh_readiness(app_id)
                    row = self.store.application(app_id)
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
                profile, revision = self.store.profile()
                job = Job.model_validate(row["job"])
                current = self.store.management.evaluation(
                    app_id,
                    self.store.effective_profile(app_id, profile, job),
                    job,
                    self.store.settings(),
                )
                if row["state"] == State.READY and current.state != State.READY:
                    self.store.prepare(
                        app_id,
                        revision,
                        current.model_dump_json(),
                        current.state,
                        row["manifest"],
                        expected_job=job,
                    )
                    row = self.store.application(app_id)
                if row["state"] != State.READY:
                    operation.result(row["state"])
                    continue
                if not self.store.daily_usage().remaining:
                    operation.progress(
                        "waiting_for_capacity",
                        "Documents ready; waiting for daily sending capacity.",
                    )
                    operation.result("awaiting_daily_capacity")
                    operation.completion_status = "limit_reached"
                    continue
                result[str(app_id)] = self.submit(app_id, progress=operation.progress)
                operation.result("submitted")
            except Exception as exc:
                result[str(app_id)] = type(exc).__name__
                row = self.store.application(app_id)
                if row["state"] == State.READY or (
                    row["state"] == State.REVIEW
                    and (
                        row["revision"] != self.store.profile()[1]
                        or not row["evaluation"]
                        or row["evaluation"].get("preparation_pending", False)
                    )
                ):
                    # Persist a current-revision hold: a later cycle must not retry this failure.
                    profile, revision = self.store.profile()
                    held_job = Job.model_validate(row["job"])
                    evaluation = self.store.management.evaluation(
                        app_id,
                        self.store.effective_profile(app_id, profile, held_job),
                        held_job,
                        self.store.settings(),
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
