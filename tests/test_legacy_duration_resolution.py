"""Legacy narratives cannot mask grounded numeric answers or become form claims."""

from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright

from applicator.browser import (
    advance_application,
    browser_options,
    collect_questions,
    fill_questions,
)
from applicator.models import Question
from applicator.question_adviser import question_key
from applicator.service import Service
from applicator.store import Store

YEARS = "How many years of work experience do you have with Python (Programming Language)?"
LEGACY = "From 2023, I used Python occasionally alongside other duties."


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as instance:
        yield instance


@pytest.mark.parametrize("evidence", ["approved", "project_only", "missing"])
def test_incompatible_cached_duration_consults_only_explicit_work_evidence(
    data, profile, job, evidence
):
    question = Question(id="years", label=YEARS)
    profile.answers[question_key(question)] = LEGACY
    if evidence != "missing":
        profile.evidence[0].text = "3 years Python."
        profile.evidence[0].category = "experience" if evidence == "approved" else "project"
    store = Store(data / "duration.sqlite3")
    revision = store.save_profile(profile)
    app_id = store.add_job(job)[0]
    selector = Mock()
    service = Service(store, data, question_selector=selector)
    result = service.resolve_question(app_id, profile, revision, job, question)
    assert result == ("3" if evidence == "approved" else None)
    selector.assert_not_called()
    assert store.profile() == (profile, revision)
    assert store.application(app_id)["job"] == job.model_dump()
    assert store.daily_usage().attempts == 0


@pytest.mark.parametrize("scoped", [False, True])
def test_valid_exact_numeric_approval_remains_authoritative(data, profile, job, scoped):
    question = Question(id="years", label=YEARS)
    profile.answers[question_key(question)] = LEGACY if scoped else "3"
    job.questions = [question]
    store = Store(data / "authority.sqlite3")
    revision = store.save_profile(profile)
    app_id = store.add_job(job)[0]
    if scoped:
        store.approve_answer(app_id, question.id, "3", revision, job)
    selector = Mock()
    assert (
        Service(store, data, question_selector=selector).resolve_question(
            app_id, profile, revision, job, question
        )
        == "3"
    )
    selector.assert_not_called()


@pytest.mark.browser
def test_legacy_text_field_resolves_grounded_number_and_advances_without_sending(
    browser, data, profile, job
):
    profile.answers[question_key(Question(id="years", label=YEARS))] = LEGACY
    profile.evidence[0].category = "experience"
    profile.evidence[0].text = "3 years Python."
    store = Store(data / "live-resolution.sqlite3")
    revision = store.save_profile(profile)
    app_id = store.add_job(job)[0]
    service = Service(store, data)
    page = browser.new_page()
    try:
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=""))
        page.goto("https://www.linkedin.com/jobs/view/123/")
        page.set_content(
            f'<dialog open><p>{YEARS}*</p><input id="years" aria-label="{YEARS}" '
            'type="text" required><button onclick="if(document.querySelector(\'#years\').value '
            "=== '3') document.querySelector('dialog').innerHTML = "
            "'<h2>Review</h2><button onclick=&quot;window.sent=true&quot;>Submit application</button>'\">"
            "Review</button></dialog>"
        )
        pending = {}
        resolver = Mock(
            side_effect=lambda q: service.resolve_question(app_id, profile, revision, job, q)
        )
        assert collect_questions(
            page,
            profile,
            pending,
            resume_field_ids=None,
            resolver=resolver,
            progress=Mock(),
            memory=None,
        )
        assert pending == {}
        assert page.locator("#years").input_value() == "3"
        resolver.assert_called_once()
        advance_application(
            page,
            profile,
            resume_field_ids=None,
            resolver=resolver,
            progress=Mock(),
            memory=Mock(return_value=None),
        )
        assert page.get_by_role("button", name="Submit application").count() == 1
        assert page.evaluate("window.sent") is None
        assert store.profile() == (profile, revision)
        assert store.daily_usage().attempts == 0
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("with_resolver", [False, True])
def test_missing_numeric_fact_collects_review_without_copying_legacy_or_prefill(
    browser, profile, with_resolver
):
    question = Question(id="years", label=YEARS)
    profile.answers[question_key(question)] = LEGACY
    resolver = Mock(return_value=None) if with_resolver else None
    page = browser.new_page()
    try:
        page.set_content(
            f'<dialog open><input id="years" aria-label="{YEARS}" type="text" '
            'required value="9"><label>First name<input id="first" required></label></dialog>'
        )
        pending = {}
        assert not collect_questions(
            page,
            profile,
            pending,
            resume_field_ids=None,
            resolver=resolver,
            progress=Mock(),
            memory=None,
        )
        assert list(pending) == [question_key(question)]
        assert page.locator("#years").input_value() == "9"
        assert page.locator("#first").input_value() == profile.name.split()[0]
        if resolver:
            resolver.assert_called_once()
    finally:
        page.close()


@pytest.mark.browser
def test_exact_offered_duration_range_bypasses_resolver(browser, profile):
    profile.answers[question_key(Question(id="years", label=YEARS))] = "1–3 years"
    resolver = Mock()
    page = browser.new_page()
    try:
        page.set_content(
            f'<dialog open><label>{YEARS}<select id="years" required>'
            '<option value="">Choose</option><option>1–3 years</option>'
            "<option>4–6 years</option></select></label></dialog>"
        )
        fill_questions(page, profile, resolver=resolver)
        assert page.locator("#years").input_value() == "1–3 years"
        resolver.assert_not_called()
    finally:
        page.close()
