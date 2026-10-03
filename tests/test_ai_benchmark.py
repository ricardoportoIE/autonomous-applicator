"""Offline checks for the opt-in benchmark; ordinary tests make no paid requests."""

import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from applicator.models import Profile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_ai.py"
SPEC = importlib.util.spec_from_file_location("benchmark_ai", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def test_curated_fixture_has_only_existing_verified_reference_labels():
    dataset = json.loads((SCRIPT.parent.parent / "benchmarks/ai_evidence_cases.json").read_text())
    profile = Profile.model_validate(dataset["profile"])
    approved = {item.id for item in profile.evidence if item.verified}
    assert len(dataset["cases"]) * 2 == benchmark.MAX_CALLS
    assert len({case["id"] for case in dataset["cases"]}) == 6
    for case in dataset["cases"]:
        assert set(case["essential_ids"]) <= set(case["acceptable_ids"]) <= approved
    assert "unverified_cert" not in approved


def test_relevance_and_essential_coverage_are_distinct():
    result = benchmark.selection_metrics(["api", "api", "distractor"], ["api"], ["api"])
    assert result == {
        "relevance_precision": 0.5,
        "essential_recall": 1.0,
        "focused_selection": False,
        "essential_complete": True,
    }
    assert benchmark.selection_metrics([], ["api"], ["api"])["essential_recall"] == 0


@pytest.mark.parametrize(
    ("details", "expected"),
    [({}, 0.003), ({"cached_tokens": 1000}, 0.0011), ({"cache_write_tokens": 1000}, 0.0035)],
)
def test_cost_accounts_for_uncached_cached_and_cache_write_tokens(details, expected):
    assert (
        benchmark.estimated_cost(
            {"input_tokens": 1000, "input_tokens_details": details, "output_tokens": 100}
        )
        == expected
    )


@pytest.mark.parametrize(("outside", "repeats"), [(True, 1), (False, 3), (False, 0)])
def test_invalid_scope_or_budget_stops_before_any_client_or_output(
    tmp_path, monkeypatch, outside, repeats
):
    client = Mock()
    monkeypatch.setattr(benchmark, "OpenAI", client)
    output = tmp_path if outside else SCRIPT.parent.parent / "tmp" / "never-created-benchmark"
    with pytest.raises(ValueError):
        benchmark.run_live(repeats, output)
    client.assert_not_called()
    if not outside:
        assert not output.exists()
