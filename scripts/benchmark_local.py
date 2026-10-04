"""Offline, disposable dashboard/policy timings; never load the live workspace or .env."""

import argparse
import json
import math
import platform
import secrets
import statistics
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.models import Evidence, Job, Profile, Settings, State
from applicator.policy import evaluate


def summarise(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    return {
        "samples": len(samples),
        "median_ms": round(statistics.median(ordered) * 1000, 4),
        "p95_ms": round(ordered[math.ceil(len(ordered) * 0.95) - 1] * 1000, 4),
    }


def benchmark(size: int, repeats: int) -> dict:
    if not 1 <= size <= 5000 or not 5 <= repeats <= 100:
        raise ValueError("Use 1–5,000 opportunities and 5–100 repetitions")
    with tempfile.TemporaryDirectory(prefix="applicator-offline-benchmark-") as temporary:
        token = secrets.token_urlsafe(32)
        app = create_app(Path(temporary), token)
        profile = Profile(
            name="Alex Example",
            confirmed=True,
            location="Dublin, Ireland",
            evidence=[
                Evidence(
                    id=f"project-{index}",
                    category="project",
                    title=f"Fictional API project {index}",
                    text="Built independent Python and FastAPI services with PostgreSQL and tests.",
                    tags=["Python", "FastAPI", "PostgreSQL"],
                    source="Fictional reviewed repository",
                    verified=True,
                )
                for index in range(10)
            ],
        )
        job = Job(
            source="fixture",
            source_id="offline-1",
            title="Backend Engineer",
            company="Example Employer",
            location="Dublin, Ireland",
            url="https://example.test/jobs/1",
            description="Develop Python APIs with FastAPI and PostgreSQL.",
            requirements=["Python", "FastAPI", "PostgreSQL"],
        )
        app.state.store.save_profile(profile)
        # Preload the read workload in one transaction. Import/write timings are not measured.
        with app.state.store.connect(True) as db:
            db.executemany(
                "INSERT INTO applications(source,source_id,job,state) VALUES(?,?,?,?)",
                [
                    (
                        "fixture",
                        f"offline-{index}",
                        job.model_copy(
                            update={
                                "source_id": f"offline-{index}",
                                "url": f"https://example.test/jobs/{index}",
                            }
                        ).model_dump_json(),
                        State.REVIEW,
                    )
                    for index in range(1, size + 1)
                ],
            )
        metrics = {}
        with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
            for path in ["/health", "/settings", "/applications", "/worker/status"]:
                warm = client.get("/api" + path)
                assert warm.status_code == 200
                samples = []
                for _ in range(repeats):
                    start = time.perf_counter()
                    response = client.get("/api" + path)
                    samples.append(time.perf_counter() - start)
                    assert response.status_code == 200
                    if path == "/applications":
                        rows = response.json()
                        assert len(rows) == size and rows[0]["id"] == size
                metrics[path] = {**summarise(samples), "response_bytes": len(response.content)}
            tracemalloc.start()
            try:
                response = client.get("/api/applications")
                assert response.status_code == 200
                peak = tracemalloc.get_traced_memory()[1]
            finally:
                tracemalloc.stop()
        samples = []
        for _ in range(repeats):
            start = time.perf_counter()
            result = evaluate(job, profile, Settings())
            samples.append(time.perf_counter() - start)
            assert result.score == 100
        metrics["policy"] = summarise(samples)
        with app.state.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM submission_records").fetchone()[0] == 0
        return {"opportunities": size, "list_peak_traced_bytes": peak, "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1, 100, 1000])
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("test-results/local-benchmark.json"))
    args = parser.parse_args()
    if len(args.sizes) > 5:
        parser.error("Use at most five workload sizes")
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "method": "Sequential in-process ASGI/SQLite reads; fictional data; no network, AI or sends",
        "workloads": [benchmark(size, args.repeats) for size in args.sizes],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Offline benchmark saved to {args.output}; no live workspace or credentials loaded.")


if __name__ == "__main__":
    main()
