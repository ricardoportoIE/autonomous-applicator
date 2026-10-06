"""Configured model failures hold questions without preventing useful CV preparation."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from applicator.api import create_app
from applicator.models import Question, State
from applicator.routine_answers import RoutineSelection


@pytest.mark.parametrize("mode", ["success", "no_key", "wrong_model", "provider_error"])
def test_routine_selector_configuration_and_provider_failure(data, profile, job, monkeypatch, mode):
    import applicator.api as module

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key-not-valid")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    if mode == "no_key":
        monkeypatch.delenv("OPENAI_API_KEY")
    elif mode == "wrong_model":
        monkeypatch.setenv("OPENAI_MODEL", "unapproved-model")
    sdk = MagicMock()
    sdk.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol",
        output_parsed=RoutineSelection(evidence_ids=["python"], needs_review=False),
    )
    if mode == "provider_error":
        sdk.responses.parse.side_effect = RuntimeError("private provider failure")
    factory = MagicMock()
    factory.return_value.__enter__.return_value = sdk
    monkeypatch.setattr(module, "OpenAI", factory)
    app = create_app(data, "fictional-routine-api-token-01234567890123456789")
    app.state.store.save_profile(profile)
    job.questions = [Question(id="project", label="Describe your Python project experience")]
    app_id, _ = app.state.store.add_job(job)
    app.state.service.prepare(app_id)
    row = app.state.store.application(app_id)
    assert row["manifest"]["files"]["cv_pdf"]
    assert app.state.store.daily_usage().attempts == 0
    assert "private provider failure" not in str(app.state.store.events())
    if mode == "success":
        assert row["state"] == State.READY
        assert row["routine_answers"][0]["answer"] == (
            "I have experience with Python through independent projects."
        )
        factory.assert_called_once_with(timeout=180, max_retries=0)
        assert sdk.responses.parse.call_args.kwargs["model"] == "gpt-6.1-sol"
    else:
        assert row["state"] == State.REVIEW and not row["routine_answers"]
        if mode in {"no_key", "wrong_model"}:
            factory.assert_not_called()
