"""Application approvals preserve unrelated documents and resume the FIFO queue."""

import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.documents import digest
from applicator.models import Advice, Job, Question, Settings, State
from applicator.store import Store

TOKEN = "scoped-answer-fixture-token-01234567890123456789"


@pytest.fixture
def scoped(data, profile, job):
    app = create_app(data, TOKEN)
    store = app.state.store
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, routine_answers_enabled=False))
    job.questions = [
        Question(id="availability", label="Preferred start date?", choices=["Next month", "Later"])
    ]
    ids = [
        store.add_job(
            job.model_copy(update={"source_id": str(i), "url": f"http://127.0.0.1:9999/{i}"})
        )[0]
        for i in (1, 2)
    ]
    session = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    return app, session, ids, profile


def approve(session, app_id, answer="Next month", revision=1, question="availability"):
    return session.put(
        f"/api/applications/{app_id}/questions/{question}/answer",
        json={"answer": answer},
        headers={"If-Match": str(revision)},
    )


def test_approval_survives_reload_preserves_both_cvs_and_resumes_only_the_approved_job(
    scoped, data
):
    app, session, ids, profile = scoped
    store, service = app.state.store, app.state.service
    for app_id in ids:
        service.prepare(app_id)
    before = {app_id: store.application(app_id) for app_id in ids}
    hashes = {
        app_id: digest(
            data / "documents" / str(app_id) / before[app_id]["manifest"]["files"]["cv_pdf"]["name"]
        )
        for app_id in ids
    }
    assert approve(session, ids[0]).status_code == 200
    assert store.profile() == (profile, 1)
    first, other = (store.application(app_id) for app_id in ids)
    assert first["state"] == State.READY
    assert first["manifest"] == before[ids[0]]["manifest"]
    assert first["approved_answers"] == {"question:preferred start date?": "Next month"}
    assert other == before[ids[1]]
    assert Store(store.path).application(ids[0])["approved_answers"] == first["approved_answers"]
    for app_id in ids:
        assert (
            digest(
                data
                / "documents"
                / str(app_id)
                / before[app_id]["manifest"]["files"]["cv_pdf"]["name"]
            )
            == hashes[app_id]
        )
    adapter = Mock()
    adapter.submit.return_value = "fixture:confirmed"
    service.adapters["fixture"] = adapter
    assert service.queue_pending()
    service.tick()
    adapter.submit.assert_called_once()
    assert adapter.submit.call_args.args[1] == {"availability": "Next month"}
    assert store.application(ids[0])["state"] == State.SUBMITTED
    assert store.application(ids[1])["state"] == State.REVIEW
    assert not service.queue_pending()
    assert "Next month" not in json.dumps(store.events())


@pytest.mark.parametrize(
    "case",
    [
        "missing_documents",
        "changed_file",
        "cover_missing",
        "cover_present",
        "ai_required",
        "low_fit",
    ],
)
def test_approval_queues_only_required_preparation_or_retains_a_policy_skip(scoped, data, case):
    app, session, ids, _ = scoped
    store, service = app.state.store, app.state.service
    app_id = ids[0]
    job = Job.model_validate(store.application(app_id)["job"])
    if case == "low_fit":
        job.requirements = ["Rust", "Java", "Go"]
        store.update_job(app_id, job)
    if case not in {"missing_documents", "low_fit"}:
        service.prepare(app_id)
    if case == "changed_file":
        row = store.application(app_id)
        (data / "documents" / str(app_id) / row["manifest"]["files"]["cv_pdf"]["name"]).write_bytes(
            b"changed"
        )
    elif case in {"cover_missing", "cover_present"}:
        job.cover_letter_required = True
        # Simulate current provenance and CV without the mandatory cover letter.
        store.update_job(app_id, job)
        service.prepare(app_id)
        with store.connect(True) as db:
            row = store.application(app_id)
            if case == "cover_missing":
                row["manifest"]["files"].pop("cover_pdf")
            db.execute(
                "UPDATE applications SET manifest=? WHERE id=?",
                (json.dumps(row["manifest"]), app_id),
            )
    elif case == "ai_required":
        store.set_settings(store.settings().model_copy(update={"ai_document_preparation": True}))
        service.prepare(app_id, selected=["python"], use_ai=False)
    response = approve(session, app_id)
    if case == "low_fit":
        assert response.status_code == 200
        assert store.application(app_id)["state"] == State.SKIPPED
        return
    if case == "cover_present":
        assert response.status_code == 200
        assert store.application(app_id)["state"] == State.READY
        return
    assert response.status_code == 200
    row = store.application(app_id)
    assert row["state"] == State.REVIEW and row["evaluation"]["preparation_pending"]
    assert service.queue_pending()
    if case == "missing_documents":
        adapter = Mock()
        adapter.submit.return_value = "fixture:prepared-and-sent"
        service.adapters["fixture"] = adapter
        service.tick()
        assert store.application(app_id)["state"] == State.SUBMITTED


@pytest.mark.parametrize(
    "case",
    [
        "missing_app",
        "missing_question",
        "stale_revision",
        "changed_job",
        "sensitive",
        "wrong_choice",
        "blank",
        "oversized",
        "submitted",
        "submitting",
        "uncertain",
        "busy",
    ],
)
def test_invalid_or_concurrent_approval_does_not_change_profile_or_other_applications(scoped, case):
    app, session, ids, profile = scoped
    store = app.state.store
    app_id, revision, answer, question = ids[0], 1, "Next month", "availability"
    job = Job.model_validate(store.application(app_id)["job"])
    if case == "missing_app":
        app_id = 999
    elif case == "missing_question":
        question = "missing"
    elif case == "stale_revision":
        revision = 2
    elif case == "sensitive":
        job.questions[0].sensitive = True
        store.update_job(app_id, job)
    elif case == "wrong_choice":
        answer = "An unoffered choice"
    elif case == "blank":
        answer = "  "
    elif case == "oversized":
        answer = "x" * 3001
    elif case in {"submitted", "submitting", "uncertain"}:
        with store.connect(True) as db:
            db.execute("UPDATE applications SET state=? WHERE id=?", (case, app_id))
    before = store.application(ids[1])
    if case == "changed_job":
        store.update_job(app_id, job.model_copy(update={"description": "Changed requirements"}))
        with pytest.raises(ValueError, match="Candidate or opportunity changed"):
            store.approve_answer(app_id, question, answer, revision, job)
    elif case == "busy":
        with app.state.service.operations.run("cycle"):
            assert approve(session, app_id).status_code == 409
    else:
        response = approve(session, app_id, answer, revision, question)
        assert response.status_code == (
            404
            if case in {"missing_app", "missing_question"}
            else 422
            if case in {"blank", "oversized"}
            else 409
        )
    assert store.application(ids[1]) == before
    assert store.profile() == (profile, 1)
    assert store.application(ids[0])["approved_answers"] == {}


def test_storage_rejects_a_missing_application_without_writing_an_approval(scoped):
    app, _, ids, profile = scoped
    store = app.state.store
    before = [store.application(app_id) for app_id in ids]
    events = store.events()
    job = Job.model_validate(before[0]["job"])

    with pytest.raises(KeyError) as error:
        store.approve_answer(999, "availability", "Next month", 1, job)

    assert error.value.args == (999,)
    assert store.profile() == (profile, 1)
    assert [store.application(app_id) for app_id in ids] == before
    assert store.events() == events
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM approved_answers").fetchone()[0] == 0


def test_scoped_approval_overrides_shared_answer_and_expires_with_changed_facts(scoped):
    app, session, ids, profile = scoped
    store = app.state.store
    profile.answers["question:preferred start date?"] = "Later"
    store.save_profile(profile)
    assert approve(session, ids[0], revision=2).status_code == 200
    job = Job.model_validate(store.application(ids[0])["job"])
    assert (
        store.effective_profile(ids[0], profile, job).answers["question:preferred start date?"]
        == "Next month"
    )
    other = Job.model_validate(store.application(ids[1])["job"])
    assert (
        store.effective_profile(ids[1], profile, other).answers["question:preferred start date?"]
        == "Later"
    )
    store.save_profile(profile)
    assert store.application(ids[0])["approved_answers"] == {}
    assert (
        store.effective_profile(ids[0], profile, job).answers["question:preferred start date?"]
        == "Later"
    )


def test_pending_ready_queue_does_not_discover_again_and_daily_cap_allows_new_preparation(
    scoped, monkeypatch
):
    app, session, ids, _ = scoped
    store, service = app.state.store, app.state.service
    store.set_settings(
        store.settings().model_copy(update={"discovery_enabled": True, "linkedin_authorised": True})
    )
    search = Mock(return_value=[])
    monkeypatch.setattr("applicator.api.LinkedInBrowser.search", search)
    adapter = Mock()
    adapter.submit.return_value = "fixture:queue-first"
    service.adapters["fixture"] = adapter
    approve(session, ids[0])
    assert session.post("/api/worker/tick").status_code == 200
    search.assert_not_called()
    assert store.application(ids[0])["state"] == State.SUBMITTED
    assert session.post("/api/worker/tick").status_code == 200
    search.assert_called_once()
    # A ready queue waiting only for capacity must not suppress later discovery.
    store.set_settings(store.settings().model_copy(update={"daily_limit": 1}))
    approve(session, ids[1])
    service.prepare(ids[1])
    assert store.application(ids[1])["state"] == State.READY
    assert not service.queue_pending()
    session.post("/api/worker/tick")
    assert search.call_count == 2
    assert store.application(ids[1])["state"] == State.READY


@pytest.mark.parametrize("answer", [" ", "x" * 3001])
def test_storage_validation_cannot_be_bypassed(scoped, answer):
    app, _, ids, _ = scoped
    store = app.state.store
    job = Job.model_validate(store.application(ids[0])["job"])
    with pytest.raises(ValueError, match="non-sensitive answer"):
        store.approve_answer(ids[0], "availability", answer, 1, job)
    assert store.application(ids[0])["approved_answers"] == {}


def test_manual_approval_can_override_a_newly_observed_routine_answer(scoped):
    app, session, ids, _ = scoped
    store = app.state.store
    job = Job.model_validate(store.application(ids[0])["job"])
    question = Question(id="observed", label="Describe your experience")
    store.save_routine_answer(
        ids[0], question, "Approved original evidence", "candidate", [], 1, job
    )
    assert approve(session, ids[0], "My explicit answer", question="observed").status_code == 200
    assert (
        store.application(ids[0])["approved_answers"]["question:describe your experience"]
        == "My explicit answer"
    )


def test_valid_gpt_documents_are_not_regenerated_after_manual_approval(scoped):
    app, session, ids, _ = scoped
    store, service = app.state.store, app.state.service
    store.set_settings(store.settings().model_copy(update={"ai_document_preparation": True}))

    def select(profile, job, metadata):
        metadata.update(
            method="openai",
            model="gpt-6.1-sol",
            requested_model="gpt-6.1-sol",
            response_id="resp_fixture",
        )
        return Advice(evidence_ids=["python"], explanation="Approved facts")

    service.selector = Mock(side_effect=select)
    service.prepare(ids[0])
    manifest = store.application(ids[0])["manifest"]
    assert approve(session, ids[0]).status_code == 200
    service.selector.assert_called_once()
    assert store.application(ids[0])["state"] == State.READY
    assert store.application(ids[0])["manifest"] == manifest


def test_answer_expires_when_the_opportunity_changes(scoped):
    app, session, ids, _ = scoped
    store = app.state.store
    approve(session, ids[0])
    job = Job.model_validate(store.application(ids[0])["job"])
    store.update_job(ids[0], job.model_copy(update={"description": "New facts"}))
    assert store.application(ids[0])["approved_answers"] == {}


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
def test_unknown_live_question_keeps_exact_choices_and_resumes_only_after_approval(
    scoped, data, existing, automatic
):
    from applicator.browser import LinkedInBrowser, ReviewRequired

    app, session, ids, profile = scoped
    store, service = app.state.store, app.state.service
    row = store.application(ids[0])
    job = Job.model_validate(row["job"])
    if not existing:
        job.questions = []
        store.update_job(ids[0], job)
    else:
        approve(session, ids[0])
    store.set_settings(store.settings().model_copy(update={"routine_answers_enabled": automatic}))
    service.prepare(ids[0])
    browser = LinkedInBrowser(data, profile)
    question = Question(
        id="live_start", label="Preferred start date?", choices=["Immediate", "Next month"]
    )
    # Existing approval for this label is expired when the observed choices change.
    question.choices = ["Immediate", "Tomorrow"]

    def submit(job, answers, folder):
        assert browser.question_resolver(question) is None
        raise ReviewRequired("Approve an exact answer for: Preferred start date?")

    browser.submit = submit
    service.adapters["fixture"] = browser
    with pytest.raises(ReviewRequired):
        service.submit(ids[0])
    row = store.application(ids[0])
    saved = next(item for item in row["job"]["questions"] if item["label"] == question.label)
    assert saved["choices"] == ["Immediate", "Tomorrow"]
    assert saved["id"] == ("availability" if existing else "live_start")
    assert store.daily_usage().held == 0 and store.daily_usage().used == 0
    assert approve(session, ids[0], "Tomorrow", question=saved["id"]).status_code == 200
    assert store.application(ids[0])["evaluation"]["preparation_pending"]
    assert service.queue_pending()


def test_unrelated_observed_question_cannot_replace_the_requested_review_question(scoped):
    app, _, ids, _ = scoped
    app.state.store.hold(
        ids[0],
        "Approve an exact answer for: New required answer",
        question=Question(id="other", label="Unrelated", choices=["Yes", "No"]),
    )
    job = app.state.store.application(ids[0])["job"]
    saved = next(item for item in job["questions"] if item["label"] == "New required answer")
    assert saved["choices"] == []


@pytest.mark.parametrize("exact_metadata", [False, True])
def test_later_question_retains_other_approvals_and_never_revives_stale_facts(
    scoped, exact_metadata
):
    app, session, ids, profile = scoped
    store = app.state.store
    assert approve(session, ids[0]).status_code == 200
    question = Question(
        id="later", label="Preferred interview format?", choices=["Online", "Office"]
    )
    store.hold(
        ids[0],
        "Approve an exact answer for: " + question.label,
        question=question if exact_metadata else None,
    )
    row = store.application(ids[0])
    assert row["approved_answers"] == {"question:preferred start date?": "Next month"}
    observed = next(item for item in row["job"]["questions"] if item["label"] == question.label)
    assert approve(session, ids[0], "Online", question=observed["id"]).status_code == 200
    assert len(store.application(ids[0])["approved_answers"]) == 2
    # Changed choices expire this question's answer, whilst the other stays approved.
    changed = question.model_copy(update={"choices": ["Office", "Phone"]})
    store.hold(ids[0], "Approve an exact answer for: " + question.label, question=changed)
    assert store.application(ids[0])["approved_answers"] == {
        "question:preferred start date?": "Next month"
    }
    store.save_profile(profile)
    store.hold(
        ids[0],
        "Approve an exact answer for: A new question",
        question=Question(id="new", label="A new question"),
    )
    assert store.application(ids[0])["approved_answers"] == {}


def test_new_observed_question_keeps_other_known_questions(scoped):
    app, _, ids, _ = scoped
    observed = Question(id="observed", label="New required answer", choices=["Yes", "No"])
    app.state.store.hold(
        ids[0], "Approve an exact answer for: New required answer", question=observed
    )
    questions = app.state.store.application(ids[0])["job"]["questions"]
    assert [item["id"] for item in questions] == ["availability", "observed"]
    assert questions[-1]["choices"] == ["Yes", "No"]


def test_changed_custom_answer_key_question_expires_only_its_own_approval(scoped):
    app, session, ids, _ = scoped
    store = app.state.store
    job = Job.model_validate(store.application(ids[0])["job"])
    question = Question(
        id="format",
        label="Interview format?",
        answer_key="interview_format",
        choices=["Online", "Office"],
    )
    job.questions.append(question)
    store.update_job(ids[0], job)
    assert approve(session, ids[0]).status_code == 200
    assert approve(session, ids[0], "Online", question="format").status_code == 200
    store.hold(
        ids[0],
        "Approve an exact answer for: Interview format?",
        question=question.model_copy(update={"choices": ["Office", "Phone"]}),
    )
    assert store.application(ids[0])["approved_answers"] == {
        "question:preferred start date?": "Next month"
    }
    assert len(store.application(ids[0])["job"]["questions"]) == 2


def test_unexpected_preparation_failure_keeps_approval_without_automatically_retrying(scoped):
    app, session, ids, _ = scoped
    store, service = app.state.store, app.state.service
    store.set_settings(store.settings().model_copy(update={"ai_document_preparation": True}))
    assert approve(session, ids[0]).status_code == 200
    service.selector = Mock(side_effect=RuntimeError("private-provider-secret"))
    service.tick()
    row = store.application(ids[0])
    assert row["approved_answers"]["question:preferred start date?"] == "Next month"
    assert not row["evaluation"]["preparation_pending"]
    assert not any("Required question needs" in item for item in row["evaluation"]["blockers"])
    assert "private-provider-secret" not in json.dumps(store.events())
    calls = service.selector.call_count
    service.tick()
    assert service.selector.call_count == calls


@pytest.mark.parametrize("stopped", [False, True])
def test_network_discovery_cannot_prevent_processing_existing_application_work(
    scoped, monkeypatch, stopped
):
    app, session, ids, _ = scoped
    store, service = app.state.store, app.state.service
    approve(session, ids[0])
    service.prepare(ids[0])
    store.set_settings(
        store.settings().model_copy(
            update={
                "discovery_enabled": True,
                "linkedin_authorised": True,
                "connections_enabled": True,
            }
        )
    )
    adapter = Mock()
    adapter.submit.return_value = "fixture:application-first"
    service.adapters["fixture"] = adapter
    contacts = Mock(side_effect=ValueError("Controlled discovery failure"))
    monkeypatch.setattr("applicator.api.LinkedInBrowser.contacts", contacts)
    if stopped:
        original = service.tick

        def tick(operation, *, stopping):
            result = original(operation, stopping=stopping)
            stopping.__self__.set()
            return result

        monkeypatch.setattr(service, "tick", tick)
    response = session.post("/api/worker/tick")
    assert response.status_code == (200 if stopped else 409)
    assert store.application(ids[0])["state"] == State.SUBMITTED
    assert store.daily_usage().used == 1
    assert contacts.call_count == (0 if stopped else 1)
