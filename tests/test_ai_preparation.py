"""Default AI preparation, provenance and failure gates without paid API calls."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.documents import fingerprint, selected_lines, validate_generation
from applicator.models import Advice, Evidence, Question, Settings, State

TOKEN = "fictional-ai-preparation-token-01234567890123456789"


@pytest.fixture
def workspace(data, profile, job, monkeypatch):
    import applicator.api as module

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key-not-valid")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    response = SimpleNamespace(
        model="gpt-6.1-sol",
        id="resp_fixture",
        output_parsed=Advice(evidence_ids=["python"], explanation="Relevant approved project."),
        usage=SimpleNamespace(input_tokens=123, output_tokens=45),
    )
    sdk = MagicMock()
    sdk.responses.parse.return_value = response
    factory = MagicMock()
    factory.return_value.__enter__.return_value = sdk
    monkeypatch.setattr(module, "OpenAI", factory)
    app = create_app(data, TOKEN)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(Settings(ai_document_preparation=True))
    app_id, _ = app.state.store.add_job(job)
    session = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    return app, session, app_id, factory, sdk, response


def test_normal_prepare_uses_declared_model_and_records_actual_provider_trace(
    workspace, profile, job
):
    app, session, app_id, factory, sdk, _ = workspace
    response = session.post(f"/api/applications/{app_id}/prepare", json={})
    assert response.status_code == 200
    metadata = response.json()["manifest"]["generation"]
    assert metadata["method"] == "openai"
    assert metadata["model"] == metadata["requested_model"] == "gpt-6.1-sol"
    assert metadata["response_id"] == "resp_fixture"
    assert metadata["input_tokens"] == 123 and metadata["output_tokens"] == 45
    assert metadata["profile_fingerprint"] == fingerprint(profile)
    assert metadata["job_fingerprint"] == fingerprint(job)
    assert factory.call_args.kwargs == {"timeout": 30, "max_retries": 0}
    params = sdk.responses.parse.call_args.kwargs
    assert params["model"] == "gpt-6.1-sol" and params["store"] is False
    assert profile.email not in params["input"] and profile.phone not in params["input"]
    assert app.state.store.daily_usage().used == 0


@pytest.mark.parametrize(
    "case",
    [
        "missing_key",
        "different_configuration",
        "different_provider_model",
        "empty_receipt",
        "unknown_id",
        "no_result",
        "provider_failure",
    ],
)
def test_api_failures_hold_for_review_without_local_fallback_or_attempts(
    workspace, monkeypatch, case
):
    app, session, app_id, factory, sdk, provider = workspace
    assert (
        session.post(f"/api/applications/{app_id}/prepare", json={"use_ai": False}).status_code
        == 200
    )
    before = app.state.store.application(app_id)
    assert before["state"] == State.READY and before["manifest"]["files"]
    if case == "missing_key":
        monkeypatch.delenv("OPENAI_API_KEY")
    elif case == "different_configuration":
        monkeypatch.setenv("OPENAI_MODEL", "another-model")
    elif case == "different_provider_model":
        provider.model = "another-model"
    elif case == "empty_receipt":
        provider.id = ""
    elif case == "unknown_id":
        provider.output_parsed = Advice(evidence_ids=["invented"], explanation="Unapproved")
    elif case == "no_result":
        provider.output_parsed = None
    else:
        sdk.responses.parse.side_effect = RuntimeError("private-provider-diagnostic")
    response = session.post(f"/api/applications/{app_id}/prepare", json={})
    assert response.status_code == (
        503 if case in {"missing_key", "different_configuration"} else 502
    )
    assert "private-provider" not in response.text
    row = app.state.store.application(app_id)
    assert row["state"] == State.REVIEW and not row["manifest"]
    assert row["revision"] == 1 and row["evaluation"]["blockers"]
    assert app.state.store.daily_usage().used == 0
    if case in {"missing_key", "different_configuration"}:
        factory.assert_not_called()


def test_worker_uses_same_ai_pipeline_and_does_not_retry_failed_preparation(workspace):
    app, session, app_id, _, sdk, _ = workspace
    app.state.store.set_settings(Settings(automation_enabled=True, ai_document_preparation=True))
    sdk.responses.parse.side_effect = RuntimeError("offline")
    assert session.post("/api/worker/tick").status_code == 200
    assert session.post("/api/worker/tick").status_code == 200
    assert sdk.responses.parse.call_count == 1
    assert app.state.store.application(app_id)["state"] == State.REVIEW
    assert app.state.store.daily_usage().used == 0


def test_worker_prepares_ai_documents_without_inventing_a_required_answer(workspace, job):
    app, session, app_id, _, sdk, _ = workspace
    job.questions = [Question(id="legal", label="Full-time work permission?")]
    app.state.store.update_job(app_id, job)
    app.state.store.set_settings(Settings(automation_enabled=True, ai_document_preparation=True))
    assert session.post("/api/worker/tick").status_code == 200
    row = app.state.store.application(app_id)
    assert row["manifest"]["generation"]["model"] == "gpt-6.1-sol"
    assert row["state"] == State.REVIEW
    assert sdk.responses.parse.call_count == 1
    assert app.state.store.daily_usage().used == 0


def test_explicit_local_preparation_cannot_bypass_required_ai_before_reservation(workspace):
    app, session, app_id, _, sdk, _ = workspace
    app.state.store.set_settings(Settings(automation_enabled=True, ai_document_preparation=True))
    response = session.post(f"/api/applications/{app_id}/prepare", json={"use_ai": False})
    assert response.status_code == 200
    assert response.json()["manifest"]["generation"]["method"] == "local"
    sdk.responses.parse.assert_not_called()
    adapter = Mock()
    app.state.service.adapters["fixture"] = adapter
    assert not app.state.service.preflight(app_id).can_submit
    with pytest.raises(ValueError, match="gpt-6.1-sol"):
        app.state.service.submit(app_id)
    adapter.submit.assert_not_called()
    assert app.state.store.daily_usage().used == 0


@pytest.mark.parametrize("changed", ["profile", "job"])
def test_changed_snapshot_during_api_call_cannot_be_committed(workspace, profile, job, changed):
    app, session, app_id, _, sdk, provider = workspace

    def change_snapshot(**kwargs):
        if changed == "profile":
            profile.summary = "Revised approved summary."
            app.state.store.save_profile(profile)
        else:
            job.description += " Changed requirements."
            app.state.store.update_job(app_id, job)
        return provider

    sdk.responses.parse.side_effect = change_snapshot
    response = session.post(f"/api/applications/{app_id}/prepare", json={})
    assert response.status_code == 409
    assert "changed while preparing" in response.json()["detail"]
    assert app.state.store.application(app_id)["state"] == State.REVIEW
    assert not app.state.store.application(app_id)["manifest"]


def test_enabling_ai_invalidates_pending_local_materials_but_preserves_submitted_history(workspace):
    app, session, app_id, _, _, _ = workspace
    store = app.state.store
    store.set_settings(Settings(ai_document_preparation=False))
    session.post(f"/api/applications/{app_id}/prepare", json={})
    original = store.application(app_id)
    other_job = original["job"] | {
        "source_id": "submitted-history",
        "url": "https://example.test/history",
    }
    other = session.post("/api/jobs", json=other_job).json()["id"]
    session.post(f"/api/applications/{other}/prepare", json={})
    store.reconcile(other, "fixture-history")
    history = store.application(other)
    store.set_settings(Settings(ai_document_preparation=True))
    assert store.application(app_id)["state"] == State.REVIEW
    assert not store.application(app_id)["manifest"]
    assert store.application(other) == history


@pytest.mark.parametrize(
    "field", ["model", "response_id", "profile_fingerprint", "job_fingerprint", "method"]
)
def test_invalid_provenance_blocks_actual_submission_before_reservation(workspace, field):
    app, session, app_id, _, _, _ = workspace
    session.post(f"/api/applications/{app_id}/prepare", json={})
    row = app.state.store.application(app_id)
    row["manifest"]["generation"][field] = ""
    with app.state.store.connect() as db:
        db.execute(
            "UPDATE applications SET manifest=? WHERE id=?", (json.dumps(row["manifest"]), app_id)
        )
    app.state.store.set_settings(Settings(automation_enabled=True, ai_document_preparation=True))
    adapter = Mock()
    app.state.service.adapters["fixture"] = adapter
    assert not app.state.service.preflight(app_id).can_submit
    with pytest.raises(ValueError):
        app.state.service.submit(app_id)
    assert app.state.store.daily_usage().used == 0
    adapter.submit.assert_not_called()


def test_ai_order_is_used_for_projects_while_historical_chronology_is_retained(profile, job):
    second = profile.evidence[0].model_copy(
        update={"id": "second", "title": "Second relevant project"}
    )
    profile.evidence.extend(
        [
            second,
            Evidence(
                id="old",
                category="experience",
                title="Older role",
                text="Approved earlier work.",
                dates="2020",
                source="reviewed",
                verified=True,
            ),
            Evidence(
                id="new",
                category="experience",
                title="Recent role",
                text="Approved recent work.",
                dates="2025",
                source="reviewed",
                verified=True,
            ),
        ]
    )
    lines = selected_lines(profile, job, ["second", "python"])
    titles = [text for kind, text in lines if kind == "subheading"]
    assert titles.index(second.title) < titles.index(profile.evidence[0].title)
    assert titles.index("Recent role | 2025") < titles.index("Older role | 2020")
    validate_generation({}, profile, job, require_ai=False)


def test_conflicting_ai_and_explicit_selection_is_rejected_without_a_request(workspace):
    app, session, app_id, factory, _, _ = workspace
    response = session.post(
        f"/api/applications/{app_id}/prepare", json={"use_ai": True, "evidence_ids": ["python"]}
    )
    assert response.status_code == 409
    factory.assert_not_called()
    assert app.state.store.daily_usage().used == 0


def test_missing_service_integration_holds_without_using_a_local_fallback(workspace):
    app, session, app_id, factory, _, _ = workspace
    app.state.service.selector = None
    response = session.post(f"/api/applications/{app_id}/prepare", json={})
    assert response.status_code == 503
    assert app.state.store.application(app_id)["state"] == State.REVIEW
    assert not app.state.store.application(app_id)["manifest"]
    factory.assert_not_called()


@pytest.mark.parametrize(
    "error", [ValueError("Document layout exceeded limits"), OSError("private-file-detail")]
)
def test_failed_ai_document_rendering_clears_previous_ready_materials(
    workspace, monkeypatch, error
):
    import applicator.service as module

    app, session, app_id, _, sdk, _ = workspace
    assert (
        session.post(f"/api/applications/{app_id}/prepare", json={"use_ai": False}).status_code
        == 200
    )
    monkeypatch.setattr(module, "generate", Mock(side_effect=error))
    response = session.post(f"/api/applications/{app_id}/prepare", json={})
    assert response.status_code == 502
    assert "private-file-detail" not in response.text
    assert app.state.store.application(app_id)["state"] == State.REVIEW
    assert not app.state.store.application(app_id)["manifest"]
    assert sdk.responses.parse.call_count == 1
    assert app.state.store.daily_usage().used == 0


def test_excess_project_selection_is_rejected_before_document_rendering(workspace, profile):
    app, session, app_id, _, _, provider = workspace
    for index in range(3):
        profile.evidence.append(profile.evidence[0].model_copy(update={"id": f"project_{index}"}))
    app.state.store.save_profile(profile)
    provider.output_parsed = Advice(
        evidence_ids=[e.id for e in profile.evidence], explanation="Too many projects."
    )
    response = session.post(f"/api/applications/{app_id}/prepare", json={})
    assert response.status_code == 502
    assert not app.state.store.application(app_id)["manifest"]
    assert app.state.store.application(app_id)["state"] == State.REVIEW


def test_local_preparation_still_rejects_missing_required_candidate_contact(workspace, profile):
    app, session, app_id, factory, _, _ = workspace
    profile.email = ""
    app.state.store.save_profile(profile)
    response = session.post(f"/api/applications/{app_id}/prepare", json={"use_ai": False})
    assert response.status_code == 409
    assert not app.state.store.application(app_id)["manifest"]
    factory.assert_not_called()
