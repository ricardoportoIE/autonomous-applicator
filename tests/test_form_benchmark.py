"""The opt-in quality benchmark remains bounded and uses fictional inputs only."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from applicator.routine_answers import RoutineSelection

SPEC = importlib.util.spec_from_file_location(
    "form_benchmark",
    Path(__file__).resolve().parents[1] / "scripts" / "benchmark_form_interpretation.py",
)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


@pytest.fixture
def dataset(profile, job):
    return {
        "profile": profile.model_dump(),
        "job": job.model_dump(),
        "cases": [
            {
                "id": "given_name",
                "label": "Your given name",
                "type": "text",
                "tag": "input",
                "choices": [],
                "expected": "Alex",
            }
        ],
    }


@pytest.mark.parametrize("mode", ["success", "review", "error", "wrong_model"])
def test_benchmark_grades_answers_and_sanitises_provider_errors(dataset, mode, capsys):
    client = Mock()
    selection = RoutineSelection(
        canonical_label="First name", evidence_ids=[], needs_review=mode == "review"
    )
    client.responses.parse.return_value = SimpleNamespace(
        model="other-model" if mode == "wrong_model" else "gpt-6.1-sol",
        output_parsed=selection,
        usage=None,
    )
    if mode == "error":
        client.responses.parse.side_effect = RuntimeError("PRIVATE-REQUEST-BODY")
    report = benchmark.run_cases(client, dataset)
    assert report["fictional_data_only"] and report["provider_actions"] == 0
    assert report["baseline_correct"] == 0
    assert report["assisted_correct"] == (1 if mode == "success" else 0)
    assert "PRIVATE" not in capsys.readouterr().out
    client.responses.parse.assert_called_once()


@pytest.mark.parametrize("count", [0, 9])
def test_benchmark_rejects_empty_or_unbounded_call_inventory(dataset, count):
    dataset["cases"] *= count
    client = Mock()
    with pytest.raises(ValueError, match="limited to eight"):
        benchmark.run_cases(client, dataset)
    client.responses.parse.assert_not_called()


@pytest.mark.parametrize("mode", ["not_opted_in", "missing_key", "wrong_model"])
def test_cli_cannot_call_api_without_explicit_live_configuration(monkeypatch, mode):
    monkeypatch.setattr("sys.argv", ["benchmark"] + ([] if mode == "not_opted_in" else ["--live"]))
    monkeypatch.setattr(
        benchmark,
        "dotenv_values",
        lambda _: (
            {"OPENAI_MODEL": "another-model", "OPENAI_API_KEY": "fictional-key"}
            if mode == "wrong_model"
            else {}
        ),
    )
    client = Mock()
    monkeypatch.setattr(benchmark, "OpenAI", client)
    with pytest.raises(SystemExit):
        benchmark.main()
    client.assert_not_called()


@pytest.mark.parametrize("passed", [True, False])
def test_cli_preserves_report_and_reports_failed_conditions(tmp_path, monkeypatch, passed):
    output = tmp_path / "results" / "benchmark.json"
    monkeypatch.setattr("sys.argv", ["benchmark", "--live", "--output", str(output)])
    monkeypatch.setattr(benchmark, "dotenv_values", lambda _: {"OPENAI_API_KEY": "fictional-key"})
    client = MagicMock()
    monkeypatch.setattr(benchmark, "OpenAI", client)
    report = {"assisted_correct": int(passed), "cases": [{}]}
    monkeypatch.setattr(benchmark, "run_cases", lambda *_: report)
    if passed:
        benchmark.main()
    else:
        with pytest.raises(SystemExit, match="conditions failed"):
            benchmark.main()
    assert json.loads(output.read_text()) == report
    client.assert_called_once_with(api_key="fictional-key", timeout=180, max_retries=0)
