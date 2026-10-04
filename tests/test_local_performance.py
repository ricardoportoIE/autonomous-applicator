"""Performance measurement contracts are stable; hardware timings are informational."""

import json

import pytest

from scripts.benchmark_local import benchmark, main, summarise


def test_percentiles_use_nearest_rank_and_seconds_are_converted():
    result = summarise([0.010, 0.003, 0.005, 0.002, 0.001])
    assert result == {"samples": 5, "median_ms": 3.0, "p95_ms": 10.0}


@pytest.mark.parametrize("size,repeats", [(0, 5), (5001, 5), (1, 4), (1, 101)])
def test_benchmark_rejects_unbounded_workloads(size, repeats):
    with pytest.raises(ValueError, match="repetitions"):
        benchmark(size, repeats)


@pytest.mark.parametrize("size", [1, 20])
def test_read_workloads_preserve_counts_order_and_zero_external_attempts(size):
    result = benchmark(size, 5)
    assert result["opportunities"] == size
    assert result["list_peak_traced_bytes"] > 0
    assert set(result["metrics"]) == {
        "/health",
        "/settings",
        "/applications",
        "/worker/status",
        "policy",
    }
    for metric in result["metrics"].values():
        assert metric["samples"] == 5
        assert metric["p95_ms"] >= metric["median_ms"] > 0
    assert result["metrics"]["/applications"]["response_bytes"] > size * 400


def test_benchmark_cli_writes_only_fictional_measurements(tmp_path, monkeypatch):
    output = tmp_path / "reports" / "measurement.json"
    monkeypatch.setattr(
        "sys.argv", ["benchmark", "--sizes", "1", "--repeats", "5", "--output", str(output)]
    )
    main()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["workloads"][0]["opportunities"] == 1
    assert "token" not in output.read_text(encoding="utf-8").lower()
    assert not list(tmp_path.rglob("*.sqlite3"))


def test_benchmark_cli_rejects_excessive_workload_count(monkeypatch):
    monkeypatch.setattr("sys.argv", ["benchmark", "--sizes", "1", "2", "3", "4", "5", "6"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
