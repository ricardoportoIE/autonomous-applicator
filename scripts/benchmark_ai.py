"""Opt-in, bounded real-API comparison using fictional evidence and isolated storage."""

import argparse
import json
import math
import os
import secrets
import shutil
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dotenv import dotenv_values
from fastapi.testclient import TestClient
from openai import OpenAI
from pypdf import PdfReader

from applicator.api import create_app
from applicator.documents import selected_lines, validate_manifest
from applicator.models import Job, Profile, Settings
from applicator.policy import evaluate

TOKEN = secrets.token_urlsafe(32)
MAX_CALLS = 12
PRICING_URL = "https://developers.openai.com/api/docs/models/gpt-6.1-sol"


def selection_metrics(ids, acceptable, essential):
    chosen = set(ids)
    relevant = chosen & set(acceptable)
    precision = len(relevant) / len(chosen) if chosen else 0.0
    recall = len(chosen & set(essential)) / len(essential)
    return {
        "relevance_precision": round(precision, 4),
        "essential_recall": round(recall, 4),
        "focused_selection": bool(chosen) and chosen <= set(acceptable),
        "essential_complete": set(essential) <= chosen,
    }


def estimated_cost(usage):
    """Standard short-context Sol pricing; not an invoice or regional quotation."""
    cached = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
    writes = usage.get("input_tokens_details", {}).get("cache_write_tokens", 0)
    return round(
        (usage.get("input_tokens", 0) - cached - writes) * 2 / 1_000_000
        + cached * 0.10 / 1_000_000
        + writes * 2.50 / 1_000_000
        + usage.get("output_tokens", 0) * 10 / 1_000_000,
        6,
    )


class RecordingClient:
    def __init__(self, client):
        self.client = client
        self.responses = SimpleNamespace(parse=self.parse)
        self.records = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        # The benchmark owns and closes the shared SDK client in its outer context.
        return False

    def parse(self, **kwargs):
        started = time.perf_counter()
        response = self.client.responses.parse(**kwargs)
        self.records.append(
            {
                "api_seconds": round(time.perf_counter() - started, 4),
                "model": response.model,
                "status": response.status,
                "usage": response.usage.model_dump() if response.usage else {},
                "advice": response.output_parsed.model_dump() if response.output_parsed else None,
            }
        )
        return response


def inspect_documents(profile, job, record, data):
    manifest = record["manifest"]
    if not manifest:
        return {"documents_generated": False}
    folder = data / "documents" / str(record["id"])
    validate_manifest(manifest, folder, record["revision"])
    ids = manifest["evidence_ids"]
    cv_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(folder / manifest["files"]["cv_pdf"]["name"]).pages
    )
    expected = [text for _, text in selected_lines(profile, job, ids)]
    normalised = " ".join(cv_text.split())
    approved = {item.id for item in profile.evidence if item.verified}
    cover_text = "\n".join(
        page.extract_text() or ""
        for page in PdfReader(folder / manifest["files"]["cover_pdf"]["name"]).pages
    )
    selected_evidence = {item.id: item for item in profile.evidence if item.verified}
    return {
        "documents_generated": True,
        "cv_pages": manifest["pages"],
        "cv_characters": len(cv_text),
        "approved_ids_only": bool(ids) and set(ids) <= approved,
        "cv_matches_approved_content": all(
            " ".join(text.split()) in normalised for text in expected
        ),
        "unverified_claim_absent": "Unconfirmed Kubernetes" not in cv_text,
        "cover_uses_selected_facts": all(
            " ".join(selected_evidence[eid].text.split()) in " ".join(cover_text.split())
            for eid in ids[:3]
        ),
        "cover_characters": len(cover_text),
    }


def summarise(rows):
    result = {}
    for method in ("local", "openai"):
        subset = [row for row in rows if row["method"] == method]
        completed = [row for row in subset if row["http_status"] == 200]
        times = sorted(row["total_seconds"] for row in subset)
        result[method] = {
            "attempts": len(subset),
            "completed": len(completed),
            "median_seconds": round(statistics.median(times), 4) if times else None,
            "p95_seconds": times[math.ceil(len(times) * 0.95) - 1] if times else None,
            "mean_relevance_precision": round(
                statistics.mean(row["relevance_precision"] for row in completed), 4
            )
            if completed
            else None,
            "mean_essential_recall": round(
                statistics.mean(row["essential_recall"] for row in completed), 4
            )
            if completed
            else None,
            "focused_selections": sum(row["focused_selection"] for row in completed),
            "essential_complete": sum(row["essential_complete"] for row in completed),
            "documents_generated": sum(row.get("documents_generated", False) for row in completed),
            "estimated_usd": round(sum(row.get("estimated_usd", 0) for row in subset), 6),
        }
    return result


def run_live(repeats, output):
    root = Path(__file__).resolve().parents[1]
    output = output.resolve()
    if not output.is_relative_to(root / "tmp"):
        raise ValueError("Benchmark output must remain in the ignored workspace tmp directory")
    dataset = json.loads((root / "benchmarks/ai_evidence_cases.json").read_text())
    if not 1 <= repeats <= 2 or len(dataset["cases"]) * repeats > MAX_CALLS:
        raise ValueError("The benchmark allows at most two repetitions and twelve paid requests")
    values = dotenv_values(root / ".env")
    if not values.get("OPENAI_API_KEY"):
        raise ValueError("Configure OPENAI_API_KEY in the private .env file first")
    model = values.get("OPENAI_MODEL") or "gpt-6.1-sol"
    if model != "gpt-6.1-sol":
        raise ValueError(
            "This comparison and its price estimate require the declared gpt-6.1-sol model"
        )
    profile = Profile.model_validate(dataset["profile"])
    output.mkdir(parents=True, exist_ok=False)
    data = output / "workspace"
    app = create_app(data, TOKEN)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(Settings(automation_enabled=False))
    report = {
        "started_utc": datetime.now(UTC).isoformat(),
        "model": model,
        "reasoning_effort": "medium",
        "repeats": repeats,
        "pricing_source": PRICING_URL,
        "rows": [],
    }
    with (
        OpenAI(
            api_key=values["OPENAI_API_KEY"],
            base_url="https://api.openai.com/v1",
            timeout=30,
            max_retries=0,
        ) as real_client,
        TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as session,
    ):
        recording = RecordingClient(real_client)
        with (
            patch("applicator.api.OpenAI", return_value=recording),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "locally-configured-benchmark-client", "OPENAI_MODEL": model},
            ),
        ):
            for repetition in range(1, repeats + 1):
                for case in dataset["cases"]:
                    job = Job(
                        source="fixture",
                        source_id=f"{case['id']}-{repetition}",
                        title=case["title"],
                        company="Example Employer",
                        location="Ireland",
                        url="https://example.test/jobs/" + case["id"],
                        description=case["description"],
                        requirements=case["requirements"],
                        sponsorship="available",
                        cover_letter_required=True,
                    )
                    app_id, _ = app.state.store.add_job(job)
                    gate = evaluate(job, profile, app.state.store.settings())
                    for method in ("local", "openai"):
                        before = len(recording.records)
                        started = time.perf_counter()
                        response = session.post(
                            f"/api/applications/{app_id}/prepare",
                            json={"use_ai": method == "openai"},
                        )
                        row = {
                            "case": case["id"],
                            "repetition": repetition,
                            "method": method,
                            "http_status": response.status_code,
                            "total_seconds": round(time.perf_counter() - started, 4),
                        }
                        if len(recording.records) > before:
                            row.update(recording.records[-1])
                            row["estimated_usd"] = estimated_cost(row["usage"])
                        if response.status_code == 200:
                            saved = response.json()
                            ids = saved["manifest"].get("evidence_ids", [])
                            row["selected_ids"] = ids
                            row.update(
                                selection_metrics(
                                    ids, case["acceptable_ids"], case["essential_ids"]
                                )
                            )
                            row.update(inspect_documents(profile, job, saved, data))
                            archive = output / "documents" / case["id"] / str(repetition) / method
                            archive.mkdir(parents=True, exist_ok=True)
                            for item in saved["manifest"]["files"].values():
                                shutil.copy2(
                                    data / "documents" / str(app_id) / item["name"],
                                    archive / item["name"],
                                )
                            row["submission_gates_unchanged"] = saved[
                                "evaluation"
                            ] == gate.model_dump(mode="json")
                        else:
                            # Application diagnostics are sanitised; never save raw provider bodies.
                            row["failure"] = response.json().get("detail", "Preparation failed")
                        report["rows"].append(row)
                        report["summary"] = summarise(report["rows"])
                        (output / "results.json").write_text(
                            json.dumps(report, indent=2), encoding="utf-8"
                        )
                        print(
                            json.dumps(
                                {
                                    key: row[key]
                                    for key in (
                                        "case",
                                        "repetition",
                                        "method",
                                        "http_status",
                                        "total_seconds",
                                    )
                                }
                            ),
                            flush=True,
                        )
                        if method == "openai" and response.status_code != 200:
                            return report
    report["submission_attempts"] = app.state.store.daily_usage().used
    report["connection_records"] = len(app.state.network.list())
    report["completed_utc"] = datetime.now(UTC).isoformat()
    (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Explicitly enable paid OpenAI requests"
    )
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("tmp/live-ai") / datetime.now(UTC).strftime("%Y%m%d-%H%M%S"),
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live explicitly to enable paid API requests")
    report = run_live(args.repeats, args.output)
    print(json.dumps(report["summary"], indent=2))
    return 0 if all(row["http_status"] == 200 for row in report["rows"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
