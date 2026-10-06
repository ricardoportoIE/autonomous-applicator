"""FIFO completion, exclusive ownership, interruption and live diagnostics."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.browser import LinkedInBrowser, ReviewRequired
from applicator.models import Advice, Question, Settings, State
from applicator.operations import Operation, OperationBusy, Operations
from applicator.service import PreparationError

TOKEN = "queue-fixture-token-01234567890123456789"


@pytest.fixture
def queue(data, profile, job):
    app = create_app(data, TOKEN)
    store, service = app.state.store, app.state.service
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, ai_document_preparation=True))
    ids = [
        store.add_job(
            job.model_copy(
                update={"source_id": str(index), "url": f"http://127.0.0.1:9999/{index}"}
            )
        )[0]
        for index in range(1, 4)
    ]
    trace = []

    def select(_profile, vacancy, metadata):
        trace.append(("ai", vacancy.source_id))
        metadata.update(
            method="openai",
            model="gpt-6.1-sol",
            requested_model="gpt-6.1-sol",
            response_id="resp_fixture",
        )
        return Advice(evidence_ids=["python"], explanation="Approved relevant evidence.")

    def submit(vacancy, answers, folder):
        trace.append(("submit", vacancy.source_id))
        assert (
            folder
            / store.application(int(vacancy.source_id))["manifest"]["files"]["cv_pdf"]["name"]
        ).is_file()
        return f"fixture:{vacancy.source_id}:confirmed"

    service.selector = select
    adapter = Mock()
    adapter.submit.side_effect = submit
    service.adapters["fixture"] = adapter
    session = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    return app, session, ids, trace, adapter


def test_fifo_finishes_every_job_before_selecting_evidence_for_the_next(queue):
    app, session, ids, trace, _ = queue
    response = session.post("/api/worker/tick")
    assert response.status_code == 200
    assert trace == [(action, str(index)) for index in ids for action in ("ai", "submit")]
    assert all(app.state.store.application(index)["state"] == State.SUBMITTED for index in ids)
    status = session.get("/api/worker/status").json()
    assert status["run"]["status"] == "completed"
    assert status["run"]["application_id"] == ids[-1]
    assert status["run"]["stage"] == "recording_confirmation"
    assert [row["application_id"] for row in reversed(status["results"])] == ids
    assert app.state.store.daily_usage().used == 3
    assert session.post("/api/worker/tick").json() == {}
    assert len(trace) == 6
    assert len(session.get("/api/worker/status").json()["results"]) == 3


def test_mixed_ready_and_unprepared_records_keep_their_arrival_order(queue):
    app, _, ids, trace, _ = queue
    app.state.service.prepare(ids[1])
    trace.clear()
    app.state.service.tick()
    assert trace == [("ai", "1"), ("submit", "1"), ("submit", "2"), ("ai", "3"), ("submit", "3")]


def test_failed_ai_is_held_without_fallback_or_automatic_retry(queue):
    app, session, ids, trace, _ = queue
    select = app.state.service.selector

    def fail_first(profile, job, metadata):
        if job.source_id == "1":
            trace.append(("failed_ai", "1"))
            raise PreparationError("AI advice failed; no documents or applications were sent")
        return select(profile, job, metadata)

    app.state.service.selector = fail_first
    session.post("/api/worker/tick")
    status = session.get("/api/worker/status").json()
    held = next(item for item in status["results"] if item["application_id"] == ids[0])
    assert held["stage"] == "selecting_evidence" and held["error_code"] == "PreparationError"
    row = app.state.store.application(ids[0])
    assert row["state"] == State.REVIEW and row["manifest"] == {}
    assert "AI advice failed" in " ".join(row["evaluation"]["blockers"])
    assert trace == [("failed_ai", "1"), ("ai", "2"), ("submit", "2"), ("ai", "3"), ("submit", "3")]
    session.post("/api/worker/tick")
    assert len(trace) == 5


@pytest.mark.parametrize(
    "error,outcome",
    [
        (ReviewRequired("Approve an exact answer for: Expected salary?"), State.REVIEW),
        (TimeoutError("private-diagnostic"), State.UNCERTAIN),
    ],
)
def test_provider_failure_preserves_stage_and_never_retries_in_another_cycle(queue, error, outcome):
    app, session, ids, trace, adapter = queue
    original = adapter.submit.side_effect

    def fail_first(job, answers, folder):
        if job.source_id == "1":
            raise error
        return original(job, answers, folder)

    adapter.submit.side_effect = fail_first
    session.post("/api/worker/tick")
    status = session.get("/api/worker/status").json()
    failed = next(item for item in status["results"] if item["application_id"] == ids[0])
    assert failed["stage"] == "opening_opportunity"
    assert failed["outcome"] == outcome
    assert app.state.store.application(ids[0])["state"] == outcome
    assert "private-diagnostic" not in json.dumps(status)
    assert "private-diagnostic" not in json.dumps(app.state.store.events())
    session.post("/api/worker/tick")
    assert adapter.submit.call_count == 3
    assert trace[-1] == ("submit", "3")


def test_unknown_required_answer_is_held_and_the_next_job_can_complete(queue):
    app, session, ids, trace, _ = queue
    row = app.state.store.application(ids[0])
    from applicator.models import Job

    job = Job.model_validate(row["job"])
    job.questions = [Question(id="legal", label="Full-time work permission?")]
    app.state.store.update_job(ids[0], job)
    session.post("/api/worker/tick")
    assert trace == [("ai", "1"), ("ai", "2"), ("submit", "2"), ("ai", "3"), ("submit", "3")]
    assert app.state.store.application(ids[0])["state"] == State.REVIEW
    assert app.state.store.daily_usage().used == 2


def test_daily_limit_stops_sends_but_prepares_the_remaining_fifo_queue(queue):
    app, session, ids, trace, _ = queue
    settings = app.state.store.settings()
    settings.daily_limit = 1
    app.state.store.set_settings(settings)
    session.post("/api/worker/tick")
    assert trace == [("ai", "1"), ("submit", "1"), ("ai", "2"), ("ai", "3")]
    assert all(app.state.store.application(app_id)["manifest"]["files"] for app_id in ids)
    assert all(app.state.store.application(app_id)["state"] == State.READY for app_id in ids[1:])
    assert app.state.store.daily_usage().used == 1
    session.post("/api/worker/tick")
    assert trace == [("ai", "1"), ("submit", "1"), ("ai", "2"), ("ai", "3")]
    assert session.get("/api/worker/status").json()["run"]["status"] == "limit_reached"


def test_pause_during_ai_finishes_documents_without_submission_or_next_job(queue):
    app, session, ids, trace, adapter = queue
    select = app.state.service.selector

    def pause(profile, job, metadata):
        settings = app.state.store.settings()
        settings.automation_enabled = False
        app.state.store.set_settings(settings)
        return select(profile, job, metadata)

    app.state.service.selector = pause
    session.post("/api/worker/tick")
    assert trace == [("ai", "1")]
    adapter.submit.assert_not_called()
    assert app.state.store.application(ids[0])["state"] == State.READY
    assert app.state.store.application(ids[1])["manifest"] == {}
    assert app.state.store.daily_usage().used == 0
    assert session.get("/api/worker/status").json()["run"]["status"] == "paused"


def test_pause_after_confirmed_submission_stops_before_the_next_vacancy(queue):
    app, session, ids, trace, adapter = queue
    submit = adapter.submit.side_effect

    def pause(job, answers, folder):
        receipt = submit(job, answers, folder)
        settings = app.state.store.settings()
        settings.automation_enabled = False
        app.state.store.set_settings(settings)
        return receipt

    adapter.submit.side_effect = pause
    session.post("/api/worker/tick")
    assert trace == [("ai", "1"), ("submit", "1")]
    assert app.state.store.application(ids[0])["state"] == State.SUBMITTED
    assert app.state.store.application(ids[1])["manifest"] == {}
    assert session.get("/api/worker/status").json()["run"]["status"] == "paused"


def test_status_stays_readable_during_slow_ai_and_competing_requests_are_rejected(queue):
    app, session, ids, trace, _ = queue
    started, release = threading.Event(), threading.Event()
    select = app.state.service.selector

    def slow(profile, job, metadata):
        if job.source_id == "1":
            started.set()
            assert release.wait(15)
        return select(profile, job, metadata)

    app.state.service.selector = slow
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(session.post, "/api/worker/tick")
        try:
            assert started.wait(10)
            status = session.get("/api/worker/status").json()["run"]
            assert status["status"] == "running"
            assert status["application_id"] == ids[0] and status["stage"] == "selecting_evidence"
            assert session.post("/api/worker/tick").status_code == 409
            assert session.post(f"/api/applications/{ids[1]}/prepare", json={}).status_code == 409
            assert session.post(f"/api/applications/{ids[1]}/submit").status_code == 409
        finally:
            release.set()
        # This checks ownership whilst AI is blocked, not PDF-rendering throughput.
        # After release, three complete document sets still need to be generated.
        assert future.result(timeout=60).status_code == 200
    assert trace == [(action, str(index)) for index in ids for action in ("ai", "submit")]


def test_journal_correlates_every_stage_with_run_and_application(queue):
    app, _, ids, _, _ = queue
    app.state.service.tick()
    status = app.state.service.operations.status()
    for app_id in ids:
        events = app.state.store.events(app_id)
        stages = [
            json.loads(event["detail"])
            for event in reversed(events)
            if event["kind"] == "application_stage"
        ]
        assert all(stage["run_id"] == status["run"]["id"] for stage in stages)
        assert [stage["stage"] for stage in stages][-1] == "recording_confirmation"
        assert {
            "selecting_evidence",
            "generating_documents",
            "checking_readiness",
            "reserving_attempt",
        } <= {stage["stage"] for stage in stages}


def test_operation_exclusion_is_shared_between_independent_instances(queue):
    app, _, ids, _, _ = queue
    operations = Operations(app.state.store)
    with operations.run("prepare", ids[0]):
        with pytest.raises(OperationBusy):
            with Operations(app.state.store).run("submit", ids[1]):
                pytest.fail("Another owner was admitted")


def test_recovery_preserves_interrupted_stage_and_marks_reserved_submission_uncertain(queue):
    app, _, ids, _, _ = queue
    store, service = app.state.store, app.state.service
    service.prepare(ids[0])
    store.reserve(ids[0], 1)
    with store.connect(True) as db:
        db.execute(
            "INSERT INTO application_runs(id,kind,status,application_id,stage,detail,started,updated,stage_started) VALUES('interrupted','cycle','running',?,'awaiting_confirmation','Waiting for confirmation.','2026-10-03T10:00:00Z','2026-10-03T10:00:00Z','2026-10-03T10:00:00Z')",
            (ids[0],),
        )
    assert store.recover() == 1
    status = service.operations.status()["run"]
    assert status["status"] == "interrupted" and status["stage"] == "awaiting_confirmation"
    assert status["error_code"] == "ProcessInterrupted"
    assert store.application(ids[0])["state"] == State.UNCERTAIN
    assert store.recover() == 0
    with pytest.raises(ValueError, match="no longer owns"):
        Operation(store, "interrupted").progress("submitting", "Late update")
    with pytest.raises(ValueError):
        Operation(store, "interrupted").finish()


def test_empty_status_missing_identity_and_failure_details_are_sanitised(data, profile, job):
    app = create_app(data, TOKEN)
    operations = app.state.service.operations
    assert operations.status() == {"run": None, "results": []}
    with pytest.raises(KeyError):
        with operations.run("prepare", 999):
            pytest.fail("Missing application admitted")
    app.state.store.save_profile(profile)
    app_id = app.state.store.add_job(job)[0]
    with pytest.raises(RuntimeError):
        with operations.run("prepare", app_id) as operation:
            operation.progress("generating_documents", "Generating verified documents.")
            raise RuntimeError("private-provider-secret")
    status = operations.status()
    assert status["run"]["status"] == "failed"
    assert status["run"]["error_code"] == "RuntimeError"
    assert "private-provider-secret" not in json.dumps(status)
    assert "private-provider-secret" not in json.dumps(app.state.store.events())


def test_operation_stage_clock_clear_job_and_explicit_completion(queue):
    app, _, ids, _, _ = queue
    operations = app.state.service.operations
    with operations.run("cycle") as operation:
        with pytest.raises(ValueError, match="Select an application"):
            operation.result("review")
        operation.progress("evaluating", "Reviewing the candidate.", ids[0])
        started = operations.status()["run"]["stage_started"]
        operation.progress("evaluating", "Still reviewing the candidate.")
        assert operations.status()["run"]["stage_started"] == started
        operation.progress("networking", "Separate networking queue.", clear_application=True)
        assert operations.status()["run"]["job"] is None
        operation.finish("paused")
    assert operations.status()["run"]["status"] == "paused"


def test_status_requires_authentication(queue):
    app, _, _, _, _ = queue
    assert TestClient(app).get("/api/worker/status").status_code == 401


@pytest.mark.parametrize("prepared", [False, True])
def test_interrupted_preparation_is_held_and_not_automatically_repeated(queue, prepared):
    app, _, ids, trace, _ = queue
    store, service = app.state.store, app.state.service
    if prepared:
        service.prepare(ids[0])
        trace.clear()
    with service.operations.run("cycle", ids[0]) as operation:
        operation.progress("generating_documents", "Generating verified documents.")
        assert store.recover() == 0
        row = store.application(ids[0])
        assert row["state"] == State.REVIEW and not row["manifest"]
        assert row["revision"] == 1 and row["evaluation"]["blockers"]
        service.tick()
    assert trace == [("ai", "2"), ("submit", "2"), ("ai", "3"), ("submit", "3")]
    assert any(
        result["error_code"] == "ProcessInterrupted"
        for result in service.operations.status()["results"]
    )


def test_second_server_cannot_recover_an_active_workspace(queue, data):
    app, _, ids, _, _ = queue
    with TestClient(app):
        app.state.service.prepare(ids[0])
        app.state.store.reserve(ids[0], 1)
        app.state.store.set_settings(
            Settings(automation_enabled=True, connections_enabled=True, linkedin_authorised=True)
        )
        app.state.network.add(
            "https://www.linkedin.com/in/fixture-recruiter/",
            "Example Recruiter",
            "Recruiter",
            "Ireland",
        )
        app.state.network.reserve(1)
        with app.state.service.operations.run("submit", ids[0]):
            with pytest.raises(OperationBusy, match="Another server"):
                with TestClient(create_app(data, TOKEN)):
                    pytest.fail("A second server entered recovery")
            assert app.state.store.application(ids[0])["state"] == State.SUBMITTING
            assert app.state.network.status(1)["state"] == "sending"
            assert app.state.service.operations.status()["run"]["status"] == "running"
    # The operating-system lock is released on shutdown, so a restart can recover.
    with TestClient(
        create_app(data, TOKEN), headers={"Authorization": "Bearer " + TOKEN}
    ) as session:
        assert session.get("/api/worker/status").json()["run"]["status"] == "completed"
        assert app.state.store.application(ids[0])["state"] == State.UNCERTAIN


@pytest.mark.parametrize("when", ["before_queue", "during_ai", "after_submission"])
def test_shutdown_finishes_only_the_current_safe_stage_and_stops_new_work(queue, when):
    app, _, ids, trace, adapter = queue
    stopped = threading.Event()
    select = app.state.service.selector
    submit = adapter.submit.side_effect
    if when == "before_queue":
        stopped.set()
    elif when == "during_ai":

        def stop_ai(profile, job, metadata):
            stopped.set()
            return select(profile, job, metadata)

        app.state.service.selector = stop_ai
    else:

        def stop_submit(job, answers, folder):
            stopped.set()
            return submit(job, answers, folder)

        adapter.submit.side_effect = stop_submit
    app.state.service.tick(stopping=stopped.is_set)
    assert app.state.service.operations.status()["run"]["status"] == "stopped"
    assert trace == (
        []
        if when == "before_queue"
        else [("ai", "1")]
        if when == "during_ai"
        else [("ai", "1"), ("submit", "1")]
    )
    assert app.state.store.application(ids[1])["manifest"] == {}


def test_each_submission_supplies_the_current_approved_profile_to_the_browser(queue, data, profile):
    app, _, ids, _, _ = queue
    browser = LinkedInBrowser(data, profile.model_copy(deep=True))
    browser.progress = lambda _stage, _detail: None
    original_progress = browser.progress
    profile.phone = "+3535550100"
    app.state.store.save_profile(profile)
    app.state.service.prepare(ids[0])

    def submit(_job, _answers, _folder):
        assert browser.profile.phone == "+3535550100"
        browser.report("answering_questions", "Completing approved questions.")
        return "fixture:current-profile"

    browser.submit = submit
    app.state.service.adapters["fixture"] = browser
    assert app.state.service.submit(ids[0]) == "fixture:current-profile"
    assert browser.progress is original_progress
