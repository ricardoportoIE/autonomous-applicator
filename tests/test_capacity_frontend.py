"""The dashboard shows confirmed sends and supports exceptional review decisions."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect
from test_frontend import dashboard as dashboard
from test_react_frontend import check_accessibility

from applicator.models import Job, Question, Settings, State
from applicator.routine_answers import RoutineSelection


def open_application(page):
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).first.click()


@pytest.mark.browser
def test_routine_answer_is_visible_with_evidence_origin_without_profile_change(dashboard):
    page, app, _ = dashboard
    store = app.state.store
    row = store.applications()[0]
    job = Job.model_validate(row["job"])
    job.questions = [Question(id="professional", label="Describe your Python project experience")]
    store.update_job(row["id"], job)
    app.state.service.question_selector = lambda *_: RoutineSelection(
        evidence_ids=["python"], needs_review=False
    )
    before = store.profile()
    app.state.service.prepare(row["id"])
    page.reload()
    open_application(page)
    page.get_by_role("tab", name=re.compile("^Questions")).click()
    expect(
        page.get_by_text(
            "Answered automatically from verified evidence selected with GPT-6.1 Sol. You can review and edit this answer.",
            exact=True,
        )
    ).to_be_visible()
    expect(page.get_by_label(job.questions[0].label, exact=True)).to_have_value(
        before[0].evidence[0].text
    )
    assert store.profile() == before


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_location_decision_requires_check_and_preserves_prepared_documents(dashboard, width):
    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 900})
    row = app.state.store.applications()[0]
    job = Job.model_validate(row["job"])
    job.location = "Cork, Ireland"
    app.state.store.update_job(row["id"], job)
    app.state.service.prepare(row["id"])
    assert app.state.store.application(row["id"])["state"] == State.REVIEW
    page.reload()
    open_application(page)
    expect(page.get_by_text("Location review: Cork, Ireland", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("^Download .+CV.pdf$"))).to_be_visible()
    check_accessibility(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    output = Path("test-results/capacity-layouts")
    output.mkdir(parents=True, exist_ok=True)
    page.locator(".application-detail").screenshot(path=str(output / f"location-{width}.png"))
    page.get_by_role("button", name="Accept location for this opportunity", exact=True).click()
    assert app.state.store.application(row["id"])["evaluation"]  # Unchecked form does not submit.
    page.get_by_label("I accept this opportunity's location", exact=True).check()
    page.get_by_role("button", name="Accept location for this opportunity", exact=True).click()
    expect(page.locator("#notice")).to_have_text(
        "Location accepted for this opportunity. The queue can recheck readiness."
    )
    page.get_by_role("button", name="Prepare documents", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Documents prepared from approved evidence.")
    assert app.state.store.application(row["id"])["state"] == State.READY


@pytest.mark.browser
def test_uncertain_capacity_can_only_be_released_after_explicit_provider_check(dashboard):
    page, app, _ = dashboard
    store = app.state.store
    store.set_settings(Settings(automation_enabled=True, daily_limit=1))
    row = store.applications()[0]
    attempt = store.reserve(row["id"], row["revision"])
    store.finish(row["id"], attempt, None)
    page.reload()
    expect(page.locator("#daily-usage")).to_contain_text("0 / 1 applications sent")
    expect(page.locator("#daily-usage")).to_contain_text("1 sending slots held")
    open_application(page)
    page.get_by_role("tab", name="Activity & outcome", exact=True).click()
    button = page.get_by_role("button", name="Confirm application was not sent", exact=True)
    button.click()
    assert store.daily_usage().held == 1
    page.get_by_label(
        "I checked the provider and this application was not sent", exact=True
    ).check()
    button.click()
    expect(page.locator("#notice")).to_have_text(
        "Confirmed as not sent. Capacity released; prepare again manually before retrying."
    )
    assert store.daily_usage().remaining == 1
    assert app.state.service.tick() == {}
    assert store.application(row["id"])["state"] == State.REVIEW


@pytest.mark.browser
def test_routine_and_geographical_preferences_persist(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Agent settings", exact=True).click()
    page.get_by_label("Answer routine questions from approved facts", exact=True).uncheck()
    page.get_by_label("Automatic application locations", exact=True).select_option("same_country")
    page.get_by_label("Daily sent-application limit", exact=True).fill("5")
    page.get_by_role("button", name="Save agent settings", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Agent settings saved.")
    settings = app.state.store.settings()
    assert (
        not settings.routine_answers_enabled
        and settings.automatic_location_policy == "same_country"
    )
    assert settings.daily_limit == 5
    page.reload()
    page.get_by_role("button", name="Agent settings", exact=True).click()
    expect(page.get_by_label("Automatic application locations", exact=True)).to_have_value(
        "same_country"
    )
