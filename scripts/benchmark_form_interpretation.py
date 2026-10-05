"""Opt-in real-API comparison of deterministic and HTML-assisted questionnaire answers."""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values
from openai import OpenAI

from applicator.browser import question_context
from applicator.models import Job, Profile, Question
from applicator.question_adviser import MODEL
from applicator.routine_answers import routine_answer, select_routine_sources

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "benchmarks" / "ai_form_cases.json"
MAX_CALLS = 8


def run_cases(client, dataset):
    profile = Profile.model_validate(dataset["profile"])
    job = Job.model_validate(dataset["job"])
    cases = dataset["cases"]
    if not cases or len(cases) > MAX_CALLS:
        raise ValueError("The fictional benchmark is limited to eight cases")
    results = []
    for case in cases:
        field = {"type": case["type"], "tag": case["tag"], "required": True}
        question = Question(
            id=case["id"],
            label=case["label"],
            choices=case["choices"],
            form_context=question_context(field, case["label"], case["choices"]),
        )
        baseline = routine_answer(profile, job, question)
        record = {
            "case": case["id"],
            "control_type": case["type"],
            "baseline_correct": (baseline.answer if baseline else None) == case["expected"],
        }

        def parse(_record=record, **kwargs):
            response = client.responses.parse(**kwargs)
            _record["returned_model"] = response.model
            _record["usage"] = response.usage.model_dump() if response.usage else {}
            return response

        proxy = SimpleNamespace(responses=SimpleNamespace(parse=parse))
        started = time.perf_counter()
        try:
            result = routine_answer(
                profile,
                job,
                question,
                lambda p, j, q, _proxy=proxy: select_routine_sources(_proxy, p, j, q),
            )
            record["assisted_correct"] = (result.answer if result else None) == case["expected"]
            record["outcome"] = "answered" if result else "review"
        except Exception as exc:
            # Provider diagnostics must never disclose local credentials or request bodies.
            record.update(assisted_correct=False, outcome="error", error=type(exc).__name__)
        record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        results.append(record)
        print(json.dumps(record), flush=True)
    return {
        "model": MODEL,
        "fictional_data_only": True,
        "provider_actions": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "cases": results,
        "baseline_correct": sum(item["baseline_correct"] for item in results),
        "assisted_correct": sum(item["assisted_correct"] for item in results),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Make at most eight paid API calls using fictional data"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "test-results" / "ai-form-interpretation.json"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live explicitly; the default performs no paid calls")
    configuration = dotenv_values(ROOT / ".env")
    key = os.getenv("OPENAI_API_KEY") or configuration.get("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL") or configuration.get("OPENAI_MODEL") or MODEL
    if not key or model != MODEL:
        parser.error("Configure a local API key and OPENAI_MODEL=gpt-6.1-sol")
    dataset = json.loads(CASES.read_text(encoding="utf-8"))
    with OpenAI(api_key=key, timeout=180, max_retries=0) as client:
        report = run_cases(client, dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if report["assisted_correct"] != len(report["cases"]):
        raise SystemExit("One or more benchmark conditions failed; inspect the fictional report")


if __name__ == "__main__":
    main()
