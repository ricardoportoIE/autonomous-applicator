"""Truthful decisions, reversible queue exclusion and authoritative send guards."""

import copy
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.application_management import experience_reviewable
from applicator.models import Question, Settings, State
from applicator.question_adviser import question_key
from applicator.service import Service
from applicator.store import Store


@pytest.fixture
def reviewed(data, profile, job):
    profile.answers[
        question_key(
            Question(id="years", label="How many years of work experience do you have with Python?")
        )
    ] = "3"
    job.description += "\nRequirements\nMinimum 5 years of work experience with Python"
    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id, _ = store.add_job(job)
    adapter = Mock()
    adapter.submit.return_value = "fixture:confirmed"
    service = Service(store, data, {"fixture": adapter})
    service.prepare(app_id)
    return store, service, app_id, profile, job, adapter


def accept(reviewed):
    store, service, app_id, _, job, _ = reviewed
    blockers = [
        value
        for value in service.preflight(app_id).evaluation.blockers
        if experience_reviewable(value)
    ]
    store.management.accept(app_id, store.profile()[1], job, blockers, False)
    service.refresh_readiness(app_id)


def test_scoped_experience_decision_sends_truthfully_and_preserves_documents(reviewed):
    store, service, app_id, profile, job, adapter = reviewed
    before = copy.deepcopy(store.application(app_id))
    assert before["state"] == State.REVIEW
    accept(reviewed)
    assert (
        store.application(app_id)["state"] == State.READY and service.preflight(app_id).can_submit
    )
    assert (
        store.profile()[0] == profile
        and store.application(app_id)["manifest"] == before["manifest"]
    )
    assert service.submit(app_id) == "fixture:confirmed" and adapter.submit.call_count == 1
    assert store.daily_usage().used == 1 and store.profile()[0].answers == profile.answers
    other_id, _ = store.add_job(
        job.model_copy(update={"source_id": "sibling", "url": "http://127.0.0.1:9999/other"})
    )
    service.prepare(other_id)
    assert store.application(other_id)["state"] == State.REVIEW


@pytest.mark.parametrize("change", ["profile", "job"])
def test_decision_expires_with_changed_facts_or_opportunity(reviewed, change):
    store, service, app_id, profile, job, _ = reviewed
    accept(reviewed)
    if change == "profile":
        store.save_profile(profile.model_copy(update={"summary": "Updated confirmed summary"}))
    else:
        store.update_job(
            app_id, job.model_copy(update={"description": job.description + "\nChanged condition"})
        )
    service.prepare(app_id)
    assert store.application(app_id)["state"] == State.REVIEW
    assert any(
        experience_reviewable(value) for value in service.preflight(app_id).evaluation.blockers
    )


@pytest.mark.parametrize(
    "blocker",
    [
        "Explicit sponsorship incompatibility.",
        "Required question needs an approved answer: unknown.",
        "Candidate profile needs confirmation.",
        "Required professional experience needs review: unknown",
        "invented",
    ],
)
def test_cannot_accept_other_unknown_or_unobserved_conditions(reviewed, blocker):
    store, _, app_id, _, job, _ = reviewed
    with pytest.raises(ValueError, match="Only current"):
        store.management.accept(app_id, 1, job, [blocker], False)
    with store.connect() as db:
        assert not db.execute("SELECT * FROM application_review_decisions").fetchall()


def test_question_and_automation_gates_survive_experience_acceptance(reviewed):
    store, service, app_id, _, job, adapter = reviewed
    job.questions = [Question(id="unknown", label="What is your notice period?")]
    store.update_job(app_id, job)
    service.prepare(app_id)
    accept(reviewed)
    assert store.application(app_id)["state"] == State.REVIEW
    with pytest.raises(ValueError, match="policy"):
        service.submit(app_id)
    store.approve_answer(app_id, "unknown", "One month", 1, job)
    service.refresh_readiness(app_id)
    assert store.application(app_id)["state"] == State.READY
    store.set_settings(store.settings().model_copy(update={"automation_enabled": False}))
    with pytest.raises(ValueError, match="paused"):
        service.submit(app_id)
    adapter.submit.assert_not_called()
    assert store.daily_usage().attempts == 0


@pytest.mark.parametrize(
    "requirement",
    [
        "5+ years of commercial software development experience",
        "Minimum 5 years of professional experience with Python and Django",
    ],
)
def test_unconfirmed_experience_requirement_can_be_waived_without_confirming_facts(
    reviewed, requirement
):
    store, service, app_id, profile, job, adapter = reviewed
    job.description = "Build Python APIs.\nRequirements\n" + requirement
    store.update_job(app_id, job)
    service.prepare(app_id)
    before = copy.deepcopy(store.application(app_id))
    assert any(
        value.startswith("Required professional experience needs review: ")
        for value in service.preflight(app_id).evaluation.blockers
    )
    accept(reviewed)
    assert service.preflight(app_id).can_submit
    assert store.application(app_id)["evaluation"]["score"] == before["evaluation"]["score"]
    assert store.application(app_id)["manifest"] == before["manifest"]
    assert store.profile()[0] == profile
    assert not any(key.startswith("condition:experience_requirement:") for key in profile.answers)
    other, _ = store.add_job(
        job.model_copy(update={"source_id": "other-gap", "url": "http://127.0.0.1:9999/gap"})
    )
    service.prepare(other)
    assert store.application(other)["state"] == State.REVIEW
    assert service.submit(app_id) == "fixture:confirmed"
    assert adapter.submit.call_count == 1 and store.profile()[0] == profile


def test_experience_waiver_does_not_answer_missing_experience_questions(reviewed):
    store, service, app_id, profile, job, adapter = reviewed
    job.description = "Build Python APIs.\n5+ years of commercial software development experience"
    job.questions = [
        Question(
            id="unknown-duration",
            label="How many years of paid production database administration do you have?",
        )
    ]
    store.update_job(app_id, job)
    service.prepare(app_id)
    accept(reviewed)
    assert store.profile()[0] == profile
    report = service.preflight(app_id)
    assert not report.can_submit
    assert not any(experience_reviewable(value) for value in report.evaluation.blockers)
    assert any("approved answer" in value for value in report.evaluation.blockers)
    with pytest.raises(ValueError, match="policy"):
        service.submit(app_id)
    adapter.submit.assert_not_called()
    assert store.daily_usage().attempts == 0


def test_fit_acceptance_keeps_score_and_cannot_accept_below_review_band(data, profile, job):
    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    service = Service(store, data)
    job.requirements = ["Python", "AWS"]
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    assert store.application(app_id)["evaluation"]["score"] == 65
    store.management.accept(app_id, 1, job, [], True)
    service.refresh_readiness(app_id)
    assert store.application(app_id)["evaluation"]["score"] == 65
    assert store.application(app_id)["state"] == State.READY
    store.set_settings(store.settings().model_copy(update={"review_threshold": 79}))
    assert service.preflight(app_id).evaluation.state == State.SKIPPED
    store.set_settings(store.settings().model_copy(update={"review_threshold": 50}))
    job.requirements = ["AWS", "Azure"]
    store.update_job(app_id, job)
    with pytest.raises(ValueError, match="fit band"):
        store.management.accept(app_id, 1, job, [], True)
    assert service.preflight(app_id).evaluation.state == State.SKIPPED


def test_trash_excludes_worker_duplicate_import_and_all_send_paths(reviewed):
    store, service, app_id, profile, job, adapter = reviewed
    before = copy.deepcopy(store.application(app_id))
    store.management.move(app_id, 1, job, "Not suitable")
    store.management.move(app_id, 1, job, "Repeated request")
    assert store.application(app_id)["trash"]["reason"] == "Not suitable"
    assert store.applications()[0]["trashed"] and not service.queue_pending()
    assert service.tick() == {} and store.add_job(job) == (app_id, False)
    assert not service.preflight(app_id).can_submit
    for action in (
        lambda: service.prepare(app_id),
        lambda: service.submit(app_id),
        lambda: store.reserve(app_id, 1),
        lambda: store.prepare(app_id, 1, "{}", State.READY, {}),
        lambda: store.update_job(app_id, job),
        lambda: store.approve_answer(app_id, "anything", "3", 1, job),
    ):
        with pytest.raises(ValueError, match="Trash"):
            action()
    adapter.submit.assert_not_called()
    store.save_profile(profile.model_copy(update={"summary": "Changed confirmed facts"}))
    store.set_settings(store.settings().model_copy(update={"ai_document_preparation": True}))
    assert store.application(app_id)["manifest"] == before["manifest"]
    assert store.daily_usage().attempts == 0
    store.management.restore(app_id, 2, job)
    assert not store.application(app_id)["trashed"] and store.application(app_id)["revision"] == 0
    assert service.queue_pending()
    with pytest.raises(ValueError, match="not in Trash"):
        store.management.restore(app_id, 2, job)


@pytest.mark.parametrize("state", [State.SUBMITTED, State.SKIPPED])
def test_restoration_preserves_terminal_history_and_budget(reviewed, state):
    store, _, app_id, _, job, _ = reviewed
    with store.connect(True) as db:
        db.execute("UPDATE applications SET state=? WHERE id=?", (state, app_id))
    usage, original = store.daily_usage(), store.application(app_id)
    store.management.move(app_id, 1, job, "")
    store.management.restore(app_id, 1, job)
    assert store.application(app_id) == original and store.daily_usage() == usage


@pytest.mark.parametrize("state", [State.SUBMITTING, State.UNCERTAIN])
def test_inflight_or_uncertain_state_cannot_be_hidden(reviewed, state):
    store, _, app_id, _, job, _ = reviewed
    with store.connect(True) as db:
        db.execute("UPDATE applications SET state=? WHERE id=?", (state, app_id))
    with pytest.raises(ValueError, match="Reconcile"):
        store.management.move(app_id, 1, job, "")
    assert not store.application(app_id)["trashed"]


def test_stale_snapshot_and_concurrent_processing_are_rejected(reviewed):
    store, service, app_id, _, job, _ = reviewed
    with pytest.raises(KeyError):
        store.management.move(999, 1, job, "")
    for revision, expected_job in [(2, job), (1, job.model_copy(update={"title": "Changed"}))]:
        with pytest.raises(ValueError, match="Refresh"):
            store.management.move(app_id, revision, expected_job, "")
    with service.operations.run("cycle"):
        with pytest.raises(ValueError, match="Pause"):
            store.management.move(app_id, 1, job, "")
    with pytest.raises(ValueError, match="500"):
        store.management.move(app_id, 1, job, "x" * 501)
    with pytest.raises(ValueError, match="Select"):
        store.management.accept(app_id, 1, job, [], False)
    blocker = service.preflight(app_id).evaluation.blockers[0]
    with pytest.raises(ValueError, match="Only current"):
        store.management.accept(app_id, 1, job, [blocker, blocker], False)
    store.management.move(app_id, 1, job, "")
    with pytest.raises(ValueError, match="active pending"):
        store.management.accept(app_id, 1, job, [blocker], False)


def test_api_requires_snapshot_truthful_acknowledgement_and_auth(data, profile, job):
    app = create_app(data, "management-local-token")
    store = app.state.store
    store.save_profile(profile)
    app_id, _ = store.add_job(job)
    session = TestClient(app, headers={"Authorization": "Bearer management-local-token"})
    body = {"job": job.model_dump()}
    path = f"/api/applications/{app_id}"
    assert session.post(path + "/trash", json=body).status_code == 422
    assert session.post(path + "/trash", json=body, headers={"If-Match": "2"}).status_code == 409
    assert (
        session.post(
            path + "/trash", json=body, headers={"If-Match": "1", "Authorization": ""}
        ).status_code
        == 401
    )
    assert (
        session.post(
            path + "/review-decision",
            json={**body, "accept_fit": True, "answers_remain_truthful": False},
            headers={"If-Match": "1"},
        ).status_code
        == 422
    )
    assert session.post(path + "/trash", json=body, headers={"If-Match": "1"}).status_code == 200
    assert session.get(path).json()["trashed"]
    assert session.post(path + "/restore", json=body, headers={"If-Match": "1"}).status_code == 200
    assert not session.get("/api/applications").json()[0]["trashed"]
    profile.answers[
        question_key(
            Question(id="years", label="How many years of work experience do you have with Python?")
        )
    ] = "3"
    store.save_profile(profile)
    job.description += "\nMinimum 5 years of work experience with Python"
    store.update_job(app_id, job)
    app.state.service.prepare(app_id)
    blockers = store.application(app_id)["evaluation"]["blockers"]
    result = session.post(
        path + "/review-decision",
        json={"job": job.model_dump(), "blockers": blockers, "answers_remain_truthful": True},
        headers={"If-Match": "2"},
    )
    assert result.status_code == 200 and store.application(app_id)["state"] == State.READY
    assert store.daily_usage().attempts == 0


def test_unconfirmed_profile_and_held_attempt_cannot_be_overridden(reviewed):
    store, _, app_id, profile, job, _ = reviewed
    store.save_profile(profile.model_copy(update={"confirmed": False}))
    with pytest.raises(ValueError, match="Confirm candidate"):
        store.management.accept(app_id, 2, job, [], True)
    with store.connect(True) as db:
        db.execute(
            "INSERT INTO attempts(application_id,day,started,status) VALUES(?,?,?,'held')",
            (app_id, "2026-10-07", "2026-10-07T12:00:00Z"),
        )
    with pytest.raises(ValueError, match="Reconcile"):
        store.management.move(app_id, 2, job, "")


def test_removal_can_be_used_before_configuring_candidate_facts(data, job):
    app = create_app(data, "empty-profile-token")
    app_id, _ = app.state.store.add_job(job)
    session = TestClient(
        app, headers={"Authorization": "Bearer empty-profile-token", "If-Match": "0"}
    )
    assert (
        session.post(
            f"/api/applications/{app_id}/trash", json={"job": job.model_dump()}
        ).status_code
        == 200
    )
    assert (
        session.post(
            f"/api/applications/{app_id}/restore", json={"job": job.model_dump()}
        ).status_code
        == 200
    )
