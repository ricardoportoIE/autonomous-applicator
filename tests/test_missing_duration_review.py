"""Resolved durations survive readiness without inventing another technology's years."""

from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright
from test_question_library import configure, output, question

from applicator.browser import browser_options, collect_questions
from applicator.models import Question, State
from applicator.policy import answer_questions
from applicator.question_adviser import question_key
from applicator.question_library import InstructionUpdate, rule_source
from applicator.service import Service
from applicator.store import Store

LEGACY = "From 2023, I used Python occasionally alongside other responsibilities."
JAVASCRIPT = "How many years of work experience do you have with JavaScript?"


@pytest.mark.parametrize("reopened", [False, True])
def test_exact_instruction_resolves_legacy_duration_through_preparation_and_restart(
    data, profile, job, reopened
):
    item = question(kind="text")
    profile.answers[question_key(item)] = LEGACY
    store, revision, app_id, rule = configure(data, profile, job, item)
    item = job.questions[0]
    generator = Mock(return_value=output(rule))
    service = Service(store, data, instruction_generator=generator)
    service.prepare(app_id)
    row = store.application(app_id)
    assert row["state"] == State.READY
    assert row["manifest"] and not row["evaluation"]["blockers"]
    assert service.preflight(app_id).evaluation.state == State.READY
    before = row["routine_answers"][0]
    assert before["source"] == rule_source(rule, item)
    assert generator.call_count == 1
    if reopened:
        store = Store(store.path)
        service = Service(store, data, instruction_generator=generator)
    assert service.resolve_question(app_id, profile, revision, job, item) == "3"
    assert store.application(app_id)["routine_answers"][0] == before
    assert generator.call_count == 1
    assert store.profile() == (profile, revision)
    assert store.daily_usage().attempts == 0
    store.question_library.update(
        rule["id"], InstructionUpdate(prompt=rule["prompt"], enabled=False, version=rule["version"])
    )
    assert service.resolve_question(app_id, profile, revision, job, item) is None
    assert store.application(app_id)["state"] == State.REVIEW
    assert store.application(app_id)["manifest"] == row["manifest"]
    assert store.application(app_id)["routine_answers"] == []


@pytest.mark.parametrize("blocked", ["number", "other_subject", "other_wording", "not_years"])
def test_invalid_approval_cannot_be_replaced_by_an_unrelated_instruction(
    data, profile, job, blocked
):
    item = question(kind="text")
    requested = item
    if blocked == "number":
        requested = question(max="2")
        value = "3"
    elif blocked == "other_subject":
        requested = question(JAVASCRIPT, "text")
        value = LEGACY
    elif blocked == "other_wording":
        requested = question("How many years of work experience do you have with Python?", "text")
        value = LEGACY
    else:
        requested = question("What is your availability?", "number")
        value = "After my notice period."
    profile.answers[question_key(requested)] = value
    store, revision, app_id, rule = configure(data, profile, job, item)
    generator = Mock(return_value=output(rule))
    assert (
        Service(store, data, instruction_generator=generator).resolve_question(
            app_id, profile, revision, job, requested
        )
        is None
    )
    generator.assert_not_called()
    assert store.profile() == (profile, revision)
    assert store.application(app_id)["routine_answers"] == []


@pytest.mark.parametrize("failure", ["review", "unavailable", "invalid", "no_generator"])
def test_exact_duration_instruction_failures_hold_without_numeric_fallback(
    data, profile, job, failure
):
    item = question(kind="text")
    profile.answers[question_key(item)] = LEGACY
    store, revision, app_id, rule = configure(data, profile, job, item)
    generator = Mock(return_value=output(rule))
    if failure == "review":
        generator.return_value = output(rule, needs_review=True)
    elif failure == "unavailable":
        generator.side_effect = ValueError("Provider unavailable")
    elif failure == "invalid":
        generator.return_value = output(rule, answer="three")
    service = Service(
        store, data, instruction_generator=None if failure == "no_generator" else generator
    )
    service.prepare(app_id)
    row = store.application(app_id)
    assert row["state"] == State.REVIEW and row["manifest"]
    assert row["routine_answers"] == []
    assert any(
        "Question instruction requires review" in text for text in row["evaluation"]["blockers"]
    )
    assert store.profile() == (profile, revision)
    assert store.daily_usage().attempts == 0


@pytest.mark.browser
@pytest.mark.parametrize("javascript_years", [None, "0", "2"])
def test_known_python_and_unknown_javascript_are_collected_independently(
    data, profile, job, javascript_years
):
    python = question(kind="text")
    javascript = Question(id="javascript", label=JAVASCRIPT)
    profile.answers[question_key(python)] = LEGACY
    if javascript_years is not None:
        profile.answers[question_key(javascript)] = javascript_years
    profile.evidence[0].tags.append("JavaScript")
    job.questions = [python, javascript]
    # Configure retains the Python question; add the independent missing duration.
    store, revision, app_id, rule = configure(data, profile, job, python)
    job.questions.append(javascript)
    store.update_job(app_id, job)
    generator = Mock(return_value=output(rule))
    service = Service(store, data, instruction_generator=generator)

    def generate(candidate, vacancy, observed, rules):
        if observed.label == JAVASCRIPT:
            return output(
                rule, rule_id=None, answer="", uses_instruction=False, instruction_quote=""
            )
        return output(rule)

    generator.side_effect = generate
    with (
        sync_playwright() as playwright,
        playwright.chromium.launch(headless=True, **browser_options()) as browser,
        browser.new_page() as page,
    ):
        page.set_content(
            "<dialog open>"
            f'<p>{python.label}*</p><input id="python" aria-label="{python.label}" type="text" required>'
            f'<p>{JAVASCRIPT}*</p><input id="javascript" aria-label="{JAVASCRIPT}" type="text" required>'
            '<button onclick="window.sent=true">Submit application</button></dialog>'
        )
        pending = {}
        assert collect_questions(
            page,
            profile,
            pending,
            resume_field_ids=None,
            resolver=lambda observed: service.resolve_question(
                app_id, profile, revision, job, observed
            ),
            progress=Mock(),
            memory=None,
        )
        assert page.locator("#python").input_value() == "3"
        assert page.locator("#javascript").input_value() == (javascript_years or "")
        assert list(pending) == ([] if javascript_years is not None else [question_key(javascript)])
        assert page.evaluate("window.sent") is None
    effective = store.effective_profile(app_id, profile, job)
    resolved, missing = answer_questions(job, effective)
    assert resolved[python.id] == "3"
    assert missing == ([] if javascript_years is not None else [javascript.id])
    assert store.profile() == (profile, revision)
    assert store.daily_usage().attempts == 0


def test_verified_work_duration_also_survives_legacy_readiness(data, profile, job):
    item = question(kind="text")
    profile.answers[question_key(item)] = LEGACY
    profile.evidence[0].category = "experience"
    profile.evidence[0].text = "3 years Python."
    store = Store(data / "applicator.sqlite3")
    revision = store.save_profile(profile)
    job.questions = [Question.model_validate(item.model_dump())]
    app_id = store.add_job(job)[0]
    service = Service(store, data)
    service.prepare(app_id)
    assert store.application(app_id)["state"] == State.READY
    assert service.resolve_question(app_id, profile, revision, job, item) == "3"
    assert store.profile() == (profile, revision)
