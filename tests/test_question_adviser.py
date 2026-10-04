"""Questionnaire idea grounding, privacy and explicit approval without paid calls."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.models import Question
from applicator.question_adviser import AnswerIdea, suggest_answer

TOKEN = "fictional-question-advice-token-01234567890123456789"


def idea(**changes):
    return AnswerIdea(
        **{
            "draft": "I built an independent Python API with automated tests.",
            "evidence_ids": ["python"],
            "fact_keys": [],
            "review_notes": "Check that this example answers the employer's question.",
            "needs_clarification": False,
            **changes,
        }
    )


@pytest.fixture
def question_workspace(data, profile, job, monkeypatch):
    import applicator.api as module

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key-not-valid")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    job.questions = [Question(id="python_example", label="Describe your Python experience")]
    app = create_app(data, TOKEN)
    app.state.store.save_profile(profile)
    app_id, _ = app.state.store.add_job(job)
    response = SimpleNamespace(model="gpt-6.1-sol", output_parsed=idea())
    sdk = MagicMock()
    sdk.responses.parse.return_value = response
    factory = MagicMock()
    factory.return_value.__enter__.return_value = sdk
    monkeypatch.setattr(module, "OpenAI", factory)
    session = TestClient(app, headers={"Authorization": "Bearer " + TOKEN, "If-Match": "1"})
    return app, session, app_id, factory, sdk, response


def path(app_id, question_id="python_example"):
    return f"/api/applications/{app_id}/questions/{question_id}/suggest"


def test_live_routine_question_remains_editable_with_manual_ai_ideas(question_workspace):
    from applicator.models import Job

    app, session, app_id, _, _, _ = question_workspace
    row = app.state.store.application(app_id)
    job = Job.model_validate(row["job"])
    question = Question(id="live_project", label="Outline your project experience")
    app.state.store.save_routine_answer(
        app_id, question, "Reviewed source wording.", "verified_evidence", ["python"], 1, job
    )
    before = app.state.store.application(app_id)
    assert session.post(path(app_id, question.id)).status_code == 200
    assert app.state.store.application(app_id) == before


def test_idea_uses_requested_model_verified_facts_and_does_not_mutate_records(question_workspace):
    app, session, app_id, factory, sdk, _ = question_workspace
    profile, revision = app.state.store.profile()
    profile.answers.update({"email": profile.email, "phone": profile.phone, "health": "Private"})
    profile.evidence.append(
        profile.evidence[0].model_copy(update={"id": "unchecked", "verified": False})
    )
    app.state.store.save_profile(profile)
    job = app.state.store.application(app_id)["job"]
    job["questions"].append(
        Question(
            id="health", label="Medical details", answer_key="health", sensitive=True
        ).model_dump()
    )
    from applicator.models import Job

    app.state.store.update_job(app_id, Job.model_validate(job))
    before = app.state.store.application(app_id)
    response = session.post(path(app_id), headers={"If-Match": str(revision + 1)})
    assert response.status_code == 200
    assert response.json()["model"] == "gpt-6.1-sol"
    assert response.json()["profile_revision"] == revision + 1
    assert app.state.store.application(app_id) == before
    assert app.state.store.profile() == (profile, revision + 1)
    assert app.state.store.daily_usage().used == 0
    factory.assert_called_once_with(timeout=180, max_retries=0)
    params = sdk.responses.parse.call_args.kwargs
    assert params["model"] == "gpt-6.1-sol" and params["store"] is False
    assert params["reasoning"] == {"effort": "medium"}
    assert params["text_format"] is AnswerIdea
    payload = json.loads(params["input"])
    assert payload["question"]["id"] == "python_example"
    assert [item["id"] for item in payload["verified_evidence"]] == ["python"]
    assert payload["approved_facts"]["answer:sponsorship"] == "Yes"
    assert "answer:health" not in payload["approved_facts"]
    assert profile.email not in params["input"] and profile.phone not in params["input"]


@pytest.mark.parametrize(
    "case,status",
    [
        ("no_key", 503),
        ("wrong_config_model", 503),
        ("unconfirmed", 409),
        ("sensitive", 409),
        ("missing_question", 404),
        ("missing_job", 404),
        ("stale_revision", 409),
        ("missing_revision", 422),
        ("unauthenticated", 401),
    ],
)
def test_invalid_requests_stop_before_provider(question_workspace, monkeypatch, case, status):
    app, session, app_id, factory, _, _ = question_workspace
    headers = {}
    question_id = "python_example"
    if case == "no_key":
        monkeypatch.delenv("OPENAI_API_KEY")
    elif case == "wrong_config_model":
        monkeypatch.setenv("OPENAI_MODEL", "another-model")
    elif case == "unconfirmed":
        profile, _ = app.state.store.profile()
        profile.confirmed = False
        app.state.store.save_profile(profile)
        headers["If-Match"] = "2"
    elif case == "sensitive":
        from applicator.models import Job

        job = Job.model_validate(app.state.store.application(app_id)["job"])
        job.questions[0].sensitive = True
        app.state.store.update_job(app_id, job)
    elif case == "missing_question":
        question_id = "absent"
    elif case == "missing_job":
        app_id = 999
    elif case == "stale_revision":
        headers["If-Match"] = "2"
    elif case == "missing_revision":
        session.headers.pop("If-Match")
    elif case == "unauthenticated":
        headers["Authorization"] = "invalid"
    assert session.post(path(app_id, question_id), headers=headers).status_code == status
    factory.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        "provider_error",
        "no_result",
        "wrong_model",
        "unknown_evidence",
        "unknown_fact",
        "empty_draft",
        "no_grounding",
    ],
)
def test_provider_failures_are_sanitised_and_never_approve(question_workspace, case):
    app, session, app_id, _, sdk, response = question_workspace
    before = app.state.store.profile()
    if case == "provider_error":
        sdk.responses.parse.side_effect = RuntimeError("private-secret-error")
    elif case == "no_result":
        response.output_parsed = None
    elif case == "wrong_model":
        response.model = "another-model"
    elif case == "unknown_evidence":
        response.output_parsed = idea(evidence_ids=["unverified"])
    elif case == "unknown_fact":
        response.output_parsed = idea(fact_keys=["unapproved"])
    elif case == "empty_draft":
        response.output_parsed = idea(draft="")
    else:
        response.output_parsed = idea(evidence_ids=[])
    result = session.post(path(app_id))
    assert result.status_code == 502
    assert "No answer was changed or approved" in result.json()["detail"]
    assert "private-secret" not in result.text
    assert app.state.store.profile() == before
    assert app.state.store.daily_usage().used == 0
    assert sdk.responses.parse.call_count == 1


@pytest.mark.parametrize("changed", ["profile", "job", "question"])
def test_changed_snapshot_discards_the_result(question_workspace, changed):
    from applicator.models import Job

    app, session, app_id, _, sdk, response = question_workspace

    def while_generating(**_kwargs):
        if changed == "profile":
            profile, _ = app.state.store.profile()
            profile.answers["new_fact"] = "Candidate-reviewed fact"
            app.state.store.save_profile(profile)
        else:
            job = Job.model_validate(app.state.store.application(app_id)["job"])
            if changed == "job":
                job.description += " Changed employer requirements."
            else:
                job.questions[0].label = "Changed question"
            app.state.store.update_job(app_id, job)
        return response

    sdk.responses.parse.side_effect = while_generating
    result = session.post(path(app_id))
    assert result.status_code == 409 and "Generate a fresh answer idea" in result.text
    assert "python_example" not in app.state.store.profile()[0].answers


@pytest.mark.parametrize("approved", [False, True])
def test_binary_work_permission_requires_exact_candidate_decision(profile, job, approved):
    question = Question(
        id="permission",
        label="Are you legally authorised to work in Ireland?",
        choices=["Yes", "No"],
    )
    profile.answers["work_permission_details"] = (
        "Stamp 2 allows part-time work only; full-time work requires sponsorship."
    )
    if approved:
        profile.answers["question:are you legally authorised to work in ireland?"] = "No"
    sdk = MagicMock()
    sdk.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol-2026-10-01",
        output_parsed=idea(
            draft="No", evidence_ids=[], fact_keys=["answer:work_permission_details"]
        ),
    )
    result = suggest_answer(sdk, profile, job, question)
    assert result.needs_clarification is not approved
    assert "Stamp 2" in sdk.responses.parse.call_args.kwargs["input"]
    if not approved:
        assert "Confirm the exact choice yourself" in result.review_notes


def test_missing_facts_return_clarification_without_fake_answer(profile, job):
    sdk = MagicMock()
    sdk.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol",
        output_parsed=idea(
            draft="",
            evidence_ids=[],
            needs_clarification=True,
            review_notes="Confirm your availability first.",
        ),
    )
    result = suggest_answer(sdk, profile, job, Question(id="start", label="When can you start?"))
    assert result.draft == "" and result.needs_clarification


@pytest.mark.parametrize("sensitive", [False, True])
def test_direct_adviser_rejects_unconfirmed_or_sensitive(profile, job, sensitive):
    profile.confirmed = sensitive
    sdk = MagicMock()
    with pytest.raises(ValueError):
        suggest_answer(
            sdk, profile, job, Question(id="private", label="Question", sensitive=sensitive)
        )
    sdk.responses.parse.assert_not_called()


def test_duplicate_grounding_is_deduplicated(profile, job):
    sdk = MagicMock()
    sdk.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol",
        output_parsed=idea(evidence_ids=["python", "python"], fact_keys=["location", "location"]),
    )
    result = suggest_answer(sdk, profile, job, Question(id="example", label="Describe a project"))
    assert result.evidence_ids == ["python"] and result.fact_keys == ["location"]


def test_model_cannot_replace_a_different_approved_choice(profile, job):
    question = Question(
        id="permission", label="Work permission", answer_key="permission", choices=["Yes", "No"]
    )
    profile.answers["permission"] = "No"
    sdk = MagicMock()
    sdk.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol",
        output_parsed=idea(
            draft="Yes",
            evidence_ids=[],
            fact_keys=["answer:permission"],
            review_notes="Review " * 200,
        ),
    )
    result = suggest_answer(sdk, profile, job, question)
    assert result.needs_clarification
    assert len(result.review_notes) <= 1500
    assert profile.answers["permission"] == "No"
