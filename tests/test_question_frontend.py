"""Real Chromium question-draft flow using fictional local data and mocked OpenAI."""

import re
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import expect
from test_frontend import dashboard as dashboard
from test_react_frontend import check_accessibility

from applicator.models import Job, Question
from applicator.question_adviser import AnswerIdea


def configure(app, monkeypatch, *, choices=None, sensitive=False):
    import applicator.api as module

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key-not-valid")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6.1-sol")
    row = app.state.store.applications()[0]
    job = Job.model_validate(row["job"])
    job.questions = [
        Question(
            id="example",
            label="Describe your Python experience",
            choices=choices or [],
            sensitive=sensitive,
        )
    ]
    app.state.store.update_job(row["id"], job)
    response = SimpleNamespace(
        model="gpt-6.1-sol",
        output_parsed=AnswerIdea(
            draft="I built an independent Python API with automated tests.",
            evidence_ids=["python"],
            fact_keys=[],
            review_notes="Review this project example before approving.",
            needs_clarification=False,
        ),
    )
    sdk = MagicMock()
    sdk.responses.parse.return_value = response
    factory = MagicMock()
    factory.return_value.__enter__.return_value = sdk
    monkeypatch.setattr(module, "OpenAI", factory)
    return row["id"], sdk, response


def open_questions(page):
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    page.get_by_role("tab", name=re.compile("^Questions")).click()


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_generate_review_edit_and_explicitly_approve_answer(dashboard, monkeypatch, width):
    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 1000})
    app_id, sdk, response = configure(app, monkeypatch)
    open_questions(page)
    before = app.state.store.profile()
    field = page.get_by_label("Describe your Python experience", exact=True)
    field.fill("My own draft")
    release, started = threading.Event(), threading.Event()

    def generate(**_kwargs):
        started.set()
        assert release.wait(15)
        return response

    sdk.responses.parse.side_effect = generate
    try:
        page.get_by_role("button", name="Suggest with GPT-6.1 Sol").click()
        assert started.wait(5)
        expect(page.get_by_role("button", name="Generating answer idea…")).to_be_disabled()
        expect(
            page.get_by_text("Generating an idea from your approved candidate facts…")
        ).to_be_visible()
        assert app.state.store.profile() == before
    finally:
        release.set()
    region = page.get_by_role("region", name="AI answer idea for Describe your Python experience")
    expect(region).to_be_visible()
    expect(region).to_contain_text("Independent API project")
    expect(field).to_have_value("My own draft")
    assert app.state.store.profile() == before
    check_accessibility(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    region.get_by_role("button", name="Use as editable draft").click()
    expect(field).to_have_value(response.output_parsed.draft)
    assert app.state.store.profile() == before
    field.fill("I built an independent Python and FastAPI service with PostgreSQL.")
    page.get_by_role("button", name="Approve answer", exact=True).click()
    expect(page.locator("#notice")).to_have_text(
        "Answer saved for this application. Readiness rechecked."
    )
    profile, revision = app.state.store.profile()
    assert revision == before[1]
    assert (
        app.state.store.application(app_id)["approved_answers"][
            "question:describe your python experience"
        ]
        == "I built an independent Python and FastAPI service with PostgreSQL."
    )
    assert app.state.store.application(app_id)["state"] == "review"
    assert app.state.store.daily_usage().used == 0
    assert sdk.responses.parse.call_count == 1
    assert profile == before[0]
    expect(region).to_have_count(0)


@pytest.mark.browser
def test_binary_idea_is_explanation_only_until_candidate_decides(dashboard, monkeypatch):
    page, app, _ = dashboard
    app_id, sdk, response = configure(app, monkeypatch, choices=["Yes", "No"])
    profile, revision = app.state.store.profile()
    profile.answers["work_permission_details"] = (
        "Stamp 2 permits part-time work only; full-time work requires sponsorship."
    )
    app.state.store.save_profile(profile)
    job = Job.model_validate(app.state.store.application(app_id)["job"])
    job.questions[0].label = "Are you legally authorised to work in Ireland?"
    app.state.store.update_job(app_id, job)
    response.output_parsed.draft = profile.answers["work_permission_details"]
    response.output_parsed.evidence_ids = []
    response.output_parsed.fact_keys = [
        "answer:work_permission_details",
        "sponsorship_required",
        "location",
    ]
    page.reload()
    expect(page.get_by_role("button", name="Applications", exact=True)).to_be_enabled()
    open_questions(page)
    page.get_by_role("button", name="Suggest with GPT-6.1 Sol").click()
    expect(page.get_by_role("button", name="Use as editable draft")).to_be_disabled()
    expect(
        page.get_by_label("Are you legally authorised to work in Ireland?", exact=True)
    ).to_have_value("")
    expect(page.get_by_text("Employer sponsorship: required", exact=True)).to_be_visible()
    expect(page.get_by_text("Location: Dublin, Ireland", exact=True)).to_be_visible()
    expect(
        page.get_by_text(
            "work permission details: " + profile.answers["work_permission_details"], exact=True
        )
    ).to_be_visible()
    expect(
        page.get_by_text("Review the explanation and choose the exact answer yourself.")
    ).to_be_visible()
    assert app.state.store.profile() == (profile, revision + 1)
    assert sdk.responses.parse.call_count == 1


@pytest.mark.browser
def test_provider_failure_preserves_draft_and_shows_actionable_error(dashboard, monkeypatch):
    page, app, _ = dashboard
    _, sdk, _ = configure(app, monkeypatch)
    sdk.responses.parse.side_effect = RuntimeError("private-provider-diagnostic")
    open_questions(page)
    field = page.get_by_label("Describe your Python experience", exact=True)
    field.fill("My draft stays available")
    before = app.state.store.profile()
    page.get_by_role("button", name="Suggest with GPT-6.1 Sol").click()
    expect(page.locator("#notice")).to_contain_text("No answer was changed or approved.")
    expect(field).to_have_value("My draft stays available")
    expect(page.get_by_role("button", name="Suggest with GPT-6.1 Sol")).to_be_enabled()
    assert app.state.store.profile() == before
    assert sdk.responses.parse.call_count == 1


@pytest.mark.browser
def test_sensitive_question_keeps_manual_handling(dashboard, monkeypatch):
    page, app, _ = dashboard
    _, sdk, _ = configure(app, monkeypatch, sensitive=True)
    open_questions(page)
    expect(
        page.get_by_text("Describe your Python experience: requires manual handling.")
    ).to_be_visible()
    expect(page.get_by_role("button", name="Suggest with GPT-6.1 Sol")).to_have_count(0)
    sdk.responses.parse.assert_not_called()


@pytest.mark.browser
def test_question_draft_is_not_restored_after_lock(dashboard, monkeypatch):
    page, app, _ = dashboard
    configure(app, monkeypatch)
    open_questions(page)
    page.get_by_role("button", name="Suggest with GPT-6.1 Sol").click()
    expect(page.get_by_role("region", name=re.compile("^AI answer idea"))).to_be_visible()
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    expect(page.get_by_role("region", name=re.compile("^AI answer idea"))).to_have_count(0)
    assert app.state.store.profile()[0].answers == {"sponsorship": "Yes"}
