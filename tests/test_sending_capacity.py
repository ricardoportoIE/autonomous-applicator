"""Confirmed sends, unresolved capacity, scoped facts and location approvals."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.browser import ReviewRequired
from applicator.documents import fingerprint
from applicator.location_policy import country, location_needs_review
from applicator.models import Question, Settings, State
from applicator.policy import evaluate
from applicator.routine_answers import RoutineSelection
from applicator.service import Service
from applicator.store import Store


@pytest.fixture
def prepared(data, profile, job):
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, daily_limit=1))
    app_id, _ = store.add_job(job)
    adapter = Mock()
    adapter.submit.return_value = "fixture:confirmed"
    service = Service(store, data, {job.source: adapter})
    service.prepare(app_id)
    return store, service, app_id, adapter


def test_pre_submission_review_releases_capacity_without_counting_send(prepared):
    store, service, app_id, adapter = prepared
    adapter.submit.side_effect = ReviewRequired("A new personal question needs review")
    with pytest.raises(ReviewRequired):
        service.submit(app_id)
    usage = store.daily_usage()
    assert (usage.used, usage.held, usage.remaining, usage.attempts) == (0, 0, 1, 1)
    assert store.application(app_id)["state"] == State.REVIEW
    with store.connect() as db:
        assert db.execute("SELECT status FROM attempts").fetchone()[0] == "released"
    assert service.tick() == {}  # Manual review is never automatically retried.
    assert adapter.submit.call_count == 1


def test_invalid_attempt_cannot_release_another_reservation(prepared):
    store, _, app_id, _ = prepared
    attempt = store.reserve(app_id, 1)
    with pytest.raises(ValueError):
        store.hold(app_id, "Known pre-submit stop", attempt=attempt + 1)
    assert store.application(app_id)["state"] == State.SUBMITTING
    assert store.daily_usage().held == 1
    store.hold(app_id, "Known pre-submit stop", attempt=attempt)
    assert store.application(app_id)["state"] == State.REVIEW
    assert store.daily_usage().held == 0
    with pytest.raises(ValueError):
        store.hold(app_id, "Duplicate", attempt=attempt)


def test_uncertain_send_holds_capacity_but_next_vacancy_gets_documents(prepared, job):
    store, service, app_id, adapter = prepared
    adapter.submit.side_effect = RuntimeError("Receipt unavailable")
    with pytest.raises(RuntimeError):
        service.submit(app_id)
    next_id, _ = store.add_job(
        job.model_copy(update={"source_id": "next", "url": "http://127.0.0.1:9999/next"})
    )
    assert service.tick() == {}
    assert service.operations.status()["results"][0]["outcome"] == "awaiting_daily_capacity"
    assert store.application(next_id)["state"] == State.READY
    assert store.application(next_id)["manifest"]["files"]["cv_pdf"]
    assert store.daily_usage().used == 0 and store.daily_usage().held == 1
    assert adapter.submit.call_count == 1


def test_negative_reconciliation_releases_capacity_requires_manual_reprepare(prepared):
    store, service, app_id, adapter = prepared
    attempt = store.reserve(app_id, 1)
    store.finish(app_id, attempt, None)
    with pytest.raises(ValueError):
        store.confirm_not_sent(app_id, 99)
    store.confirm_not_sent(app_id, 1)
    assert store.daily_usage().remaining == 1
    assert store.application(app_id)["state"] == State.REVIEW
    assert service.tick() == {}
    adapter.submit.assert_not_called()
    assert "manually" in store.application(app_id)["evaluation"]["blockers"][0]
    with pytest.raises(ValueError):
        store.confirm_not_sent(app_id, 1)
    service.prepare(app_id)
    service.submit(app_id)
    assert (store.daily_usage().used, store.daily_usage().held) == (1, 0)
    assert store.daily_usage().attempts == 2


def test_manual_confirmed_receipt_counts_once(prepared):
    store, _, app_id, _ = prepared
    attempt = store.reserve(app_id, 1)
    store.finish(app_id, attempt, None)
    store.reconcile(app_id, "fixture:checked-provider")
    assert (store.daily_usage().used, store.daily_usage().held) == (1, 0)
    with pytest.raises(ValueError):
        store.reconcile(app_id, "fixture:duplicate")
    assert store.daily_usage().used == 1


def test_confirmation_crossing_midnight_counts_the_send_day(prepared, job, monkeypatch):
    store, _, app_id, _ = prepared
    monkeypatch.setattr("applicator.store.day_key", lambda: "2026-10-04")
    attempt = store.reserve(app_id, 1)
    store.mark_sending(app_id, attempt, 1, job)
    monkeypatch.setattr("applicator.store.day_key", lambda: "2026-10-05")
    store.finish(app_id, attempt, "fixture:confirmed")
    assert store.daily_usage().used == 0 and store.daily_usage().remaining == 1
    with store.connect() as db:
        assert db.execute("SELECT confirmed_day FROM attempts").fetchone()[0] == "2026-10-04"


@pytest.mark.parametrize("change", ["pause", "scope", "revision", "location", "capacity", "job"])
def test_last_moment_mutable_gates_stop_the_submit_click(prepared, profile, job, change):
    store, _, app_id, _ = prepared
    attempt = store.reserve(app_id, 1)
    if change == "pause":
        store.set_settings(Settings(automation_enabled=False))
    elif change == "scope":
        job.source = "linkedin"  # Scope is checked before identity validation.
    elif change == "revision":
        store.save_profile(profile)
    elif change == "location":
        profile.location = "Cork, Ireland"
        with store.connect() as db:
            db.execute(
                "UPDATE config SET value=? WHERE key='profile'", (profile.model_dump_json(),)
            )
    elif change == "capacity":
        with store.connect() as db:
            db.execute(
                "INSERT INTO attempts(application_id,day,started,status) VALUES(?,?,?,'held')",
                (app_id, "2026-10-04", "fixture"),
            )
    else:
        job.title = "Changed title"
    with pytest.raises(ValueError):
        store.mark_sending(app_id, attempt, 1, job)
    with store.connect() as db:
        assert (
            db.execute("SELECT sent_day FROM attempts WHERE id=?", (attempt,)).fetchone()[0] is None
        )


@pytest.mark.parametrize(
    "location,policy,review",
    [
        ("Dublin, County Dublin, Ireland", "same_city", False),
        ("Cork, Ireland", "same_city", True),
        ("Remote, Ireland", "same_city", False),
        ("London, United Kingdom", "same_city", True),
        ("Dublinshire, Ireland", "same_city", True),
        ("Cork, Ireland", "same_country", False),
        ("Belfast, Northern Ireland", "same_country", True),
        ("London, United Kingdom", "configured_countries", False),
    ],
)
def test_location_preferences_are_explicit(profile, job, location, policy, review):
    job.location = location
    assert (
        bool(location_needs_review(job, profile, Settings(automatic_location_policy=policy)))
        == review
    )
    assert country("Belfast, Northern Ireland") == "united kingdom"


def test_location_review_prepares_documents_and_only_accepts_this_opportunity(prepared, job):
    store, service, _, _ = prepared
    job.location = "Amsterdam, Netherlands"
    first_job = job.model_copy(
        update={"source_id": "far-one", "url": "http://127.0.0.1:9999/far-one"}
    )
    second_job = job.model_copy(
        update={"source_id": "far-two", "url": "http://127.0.0.1:9999/far-two"}
    )
    first, _ = store.add_job(first_job)
    second, _ = store.add_job(second_job)
    for app_id in (first, second):
        service.prepare(app_id)
        assert store.application(app_id)["state"] == State.REVIEW
        assert store.application(app_id)["manifest"]["files"]["cv_pdf"]
    base, revision = store.profile()
    for rev, place in [(revision + 1, job.location), (revision, "London, United Kingdom")]:
        with pytest.raises(ValueError):
            store.confirm_location(first, rev, place)
    store.confirm_location(first, revision, job.location)
    assert (
        evaluate(first_job, store.effective_profile(first, base, first_job), store.settings()).state
        == State.READY
    )
    assert (
        evaluate(
            second_job, store.effective_profile(second, base, second_job), store.settings()
        ).state
        == State.REVIEW
    )
    assert store.profile() == (base, revision)
    service.prepare(first)
    assert service.preflight(first).can_submit
    store.save_profile(base)
    assert location_needs_review(
        first_job, store.effective_profile(first, base, first_job), store.settings()
    )


def test_routine_answer_is_scoped_cached_and_keeps_document_fingerprint(prepared, profile, job):
    store, service, app_id, _ = prepared
    question = Question(id="new", label="Describe your Python project experience")
    selector = Mock(return_value=RoutineSelection(evidence_ids=["python"], needs_review=False))
    service.question_selector = selector
    original_manifest = store.application(app_id)["manifest"]
    original_fingerprint = fingerprint(profile)
    for _ in range(2):
        assert (
            service.resolve_question(app_id, profile, 1, job, question) == profile.evidence[0].text
        )
    assert selector.call_count == 1
    assert store.profile() == (profile, 1)
    assert fingerprint(store.profile()[0]) == original_fingerprint
    assert store.application(app_id)["manifest"] == original_manifest
    assert service.preflight(app_id).can_submit
    row = store.application(app_id)["routine_answers"][0]
    assert row["question"]["label"] == question.label and row["source"] == "gpt-6.1-sol"
    other, _ = store.add_job(
        job.model_copy(update={"source_id": "other", "url": "http://127.0.0.1:9999/other"})
    )
    assert store.application(other)["routine_answers"] == []
    store.set_settings(Settings(automation_enabled=True, routine_answers_enabled=False))
    assert store.effective_profile(app_id, profile, job).answers == profile.answers
    store.save_profile(profile)
    assert store.application(app_id)["routine_answers"] == []
    assert service.resolve_question(app_id, profile, 1, job, question) is None
    store.set_settings(Settings(automation_enabled=True))
    with pytest.raises(ValueError):
        service.resolve_question(app_id, profile, 1, job, question)


def test_routine_questions_answer_before_prepare_but_exceptional_questions_hold(prepared, job):
    store, service, app_id, _ = prepared
    job.questions = [
        Question(id="tech", label="Have you used Python?", choices=["Yes", "No"]),
        Question(id="personal", label="Expected salary?"),
    ]
    store.update_job(app_id, job)
    service.prepare(app_id)
    row = store.application(app_id)
    assert row["state"] == State.REVIEW and row["manifest"]["files"]["cv_pdf"]
    assert len(row["routine_answers"]) == 1 and row["routine_answers"][0]["answer"] == "Yes"
    assert "personal" in " ".join(row["evaluation"]["blockers"])


def test_new_review_endpoints_validate_explicit_checks_and_revision(data, profile, job):
    token = "test-only-capacity-token-01234567890123456789"
    app = create_app(data, token)
    store = app.state.store
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    job.location = "Cork, Ireland"
    app_id, _ = store.add_job(job)
    client = TestClient(app, headers={"Authorization": "Bearer " + token})
    assert (
        client.post(
            f"/api/applications/{app_id}/location-review",
            json={"location": job.location},
            headers={"If-Match": "2"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/applications/{app_id}/location-review",
            json={"location": job.location},
            headers={"If-Match": "1"},
        ).status_code
        == 200
    )
    app.state.service.prepare(app_id)
    attempt = store.reserve(app_id, 1)
    store.finish(app_id, attempt, None)
    endpoint = f"/api/applications/{app_id}/not-sent"
    assert (
        client.post(endpoint, json={"checked": False}, headers={"If-Match": "1"}).status_code == 422
    )
    assert (
        client.post(endpoint, json={"checked": True}, headers={"If-Match": "2"}).status_code == 409
    )
    assert (
        client.post(endpoint, json={"checked": True}, headers={"If-Match": "1"}).status_code == 200
    )
    assert store.daily_usage().held == 0
