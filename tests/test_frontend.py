"""Real-browser UI regressions, accessibility and responsive-layout checks."""

import re
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader
from test_browser import TOKEN, server
from ui_coverage import save_coverage, start_coverage

from applicator.api import create_app
from applicator.browser import browser_options
from applicator.models import Advice, Job, Question, Settings
from applicator.operations import Operation
from applicator.service import PreparationError


@pytest.fixture
def dashboard(data, profile, job, request):
    app = create_app(data, TOKEN)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(Settings(linkedin_authorised=True))
    job.source = "manual"
    job.url = "https://example.test/jobs/backend"
    app_id, _ = app.state.store.add_job(job)
    app.state.service.prepare(app_id)
    with server(app) as origin, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
        errors = []
        coverage = start_coverage(page)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin)
        page.get_by_label("Access token", exact=True).fill(TOKEN)
        page.get_by_role("button", name="Unlock workspace").click()
        # Seven independent authenticated reads complete before unlock. Windows
        # browser startup can exceed Playwright's default five-second locator deadline.
        expect(page.locator("#notice")).to_have_text("Local workspace unlocked.", timeout=15000)
        yield page, app, origin
        save_coverage(coverage, request.node.nodeid)
        assert not errors
        browser.close()


@pytest.mark.browser
def test_ai_default_setting_and_normal_prepare_show_verified_origin(dashboard):
    page, app, _ = dashboard
    calls = []

    def select(_profile, job, metadata):
        calls.append(job.title)
        metadata.update(
            method="openai",
            model="gpt-6.1-sol",
            requested_model="gpt-6.1-sol",
            response_id="resp_ui_fixture",
        )
        return Advice(evidence_ids=["python"], explanation="Relevant approved project.")

    app.state.service.selector = select
    page.get_by_role("button", name="Agent settings", exact=True).click()
    page.get_by_label("Use GPT-6.1 Sol for document preparation by default", exact=True).check()
    page.get_by_role("button", name="Save agent settings", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Agent settings saved.")
    assert app.state.store.settings().ai_document_preparation
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    expect(page.get_by_role("region", name="Document preparation")).to_contain_text(
        "Preparation origin is unavailable"
    )
    page.get_by_role("button", name="Prepare documents", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Documents prepared from approved evidence.")
    expect(page.get_by_role("region", name="Document preparation")).to_contain_text(
        "Evidence selected with gpt-6.1-sol"
    )
    expect(page.get_by_role("region", name="Document preparation")).to_contain_text(
        "Profile revision 1"
    )
    assert calls == ["Backend Engineer"]
    assert app.state.store.daily_usage().used == 0


@pytest.mark.browser
def test_manual_selection_has_a_distinct_document_origin(dashboard):
    page, app, _ = dashboard
    app_id = app.state.store.applications()[0]["id"]
    app.state.service.prepare(app_id, ["python"])
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    expect(page.get_by_role("region", name="Document preparation")).to_contain_text(
        "Evidence selected manually"
    )


@pytest.mark.browser
def test_queue_monitor_shows_slow_ai_then_form_stage_and_confirmed_result(dashboard):
    page, app, _ = dashboard
    release_ai, release_form = threading.Event(), threading.Event()
    store = app.state.store
    store.set_settings(
        Settings(automation_enabled=True, ai_document_preparation=True, linkedin_authorised=True)
    )

    def select(_profile, _job, metadata):
        assert release_ai.wait(20)
        metadata.update(
            method="openai",
            model="gpt-6.1-sol",
            requested_model="gpt-6.1-sol",
            response_id="resp_ui_queue",
        )
        return Advice(evidence_ids=["python"], explanation="Approved project.")

    def submit(_job, _answers, _folder):
        status = app.state.service.operations.status()["run"]
        Operation(store, status["id"]).progress(
            "answering_questions", "Completing form step 3 using approved answers only."
        )
        assert release_form.wait(20)
        return "fixture:confirmed"

    app.state.service.selector = select
    adapter = Mock()
    adapter.submit.side_effect = submit
    app.state.service.adapters["manual"] = adapter
    monitor = page.locator("#worker-status")
    try:
        page.get_by_role("button", name="Run agent cycle", exact=True).click()
        expect(monitor).to_contain_text("Running")
        expect(monitor).to_contain_text("Backend Engineer")
        expect(monitor).to_contain_text("selecting evidence")
        expect(monitor).to_contain_text("GPT-6.1 Sol")
        expect(page.locator("#workspace")).to_have_attribute("aria-busy", "true")
        release_ai.set()
        expect(monitor).to_contain_text("answering questions")
        expect(monitor).to_contain_text("form step 3")
        release_form.set()
        expect(monitor).to_contain_text("Completed")
        expect(page.locator("#worker-results")).to_contain_text("Submitted")
        expect(page.locator("#worker-results")).to_contain_text("recording confirmation")
        assert store.daily_usage().used == 1
    finally:
        release_ai.set()
        release_form.set()


@pytest.mark.browser
@pytest.mark.parametrize("outcome", ["failed", "interrupted", "paused", "limit_reached"])
def test_queue_monitor_displays_terminal_stage_and_failure_code(dashboard, outcome):
    page, app, _ = dashboard
    with app.state.service.operations.run("submit", 1) as operation:
        operation.progress(
            "awaiting_confirmation", "Waiting for provider confirmation; do not retry."
        )
        operation.finish(outcome, "TimeoutError" if outcome in {"failed", "interrupted"} else None)
    monitor = page.locator("#worker-status")
    labels = {
        "failed": "Failed",
        "interrupted": "Interrupted",
        "paused": "Paused",
        "limit_reached": "Daily sending limit reached; preparation continues",
    }
    expect(monitor).to_contain_text(labels[outcome])
    expect(monitor).to_contain_text("Last stage: awaiting confirmation")
    if outcome in {"failed", "interrupted"}:
        expect(monitor).to_contain_text("TimeoutError")
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    expect(monitor).to_be_empty()
    page.wait_for_timeout(1200)
    expect(monitor).to_be_empty()


@pytest.mark.browser
def test_queue_monitor_reports_temporary_read_failure_and_recovers(dashboard):
    page, _, _ = dashboard
    page.route(
        "**/api/worker/status",
        lambda route: route.fulfill(status=503, json={"detail": "Status temporarily unavailable"}),
    )
    expect(page.locator("#worker-status")).to_contain_text("Live status unavailable")
    page.unroute("**/api/worker/status")
    expect(page.locator("#worker-status")).to_contain_text("Completed")


@pytest.mark.browser
@pytest.mark.parametrize("action", ["reload", "pause"])
def test_queue_monitor_resumes_observation_and_pause_during_slow_preparation(dashboard, action):
    page, app, _ = dashboard
    release = threading.Event()
    calls = []
    app.state.store.set_settings(
        Settings(automation_enabled=True, ai_document_preparation=True, linkedin_authorised=True)
    )

    def select(_profile, _job, metadata):
        calls.append("ai")
        assert release.wait(20)
        metadata.update(
            method="openai",
            model="gpt-6.1-sol",
            requested_model="gpt-6.1-sol",
            response_id="resp_ui_observation",
        )
        return Advice(evidence_ids=["python"], explanation="Approved evidence.")

    adapter = Mock()
    adapter.submit.return_value = "fixture:confirmed"
    app.state.service.adapters["manual"] = adapter
    app.state.service.selector = select
    page.reload()
    expect(page.locator("#readiness")).to_contain_text("Agent enabled")
    try:
        page.get_by_role("button", name="Run agent cycle", exact=True).click()
        expect(page.locator("#worker-status")).to_contain_text("selecting evidence")
        if action == "reload":
            page.reload()
            expect(page.locator("#worker-status")).to_contain_text("selecting evidence")
            expect(page.locator("#worker-status")).to_contain_text("Backend Engineer")
        else:
            page.get_by_role("button", name="Pause all automation", exact=True).click()
            expect(page.locator("#notice")).to_contain_text("Automation paused")
        release.set()
        expect(page.locator("#worker-status")).to_contain_text(
            "Completed" if action == "reload" else "Paused"
        )
        assert calls == ["ai"]
        assert adapter.submit.call_count == (1 if action == "reload" else 0)
        assert app.state.store.daily_usage().used == (1 if action == "reload" else 0)
    finally:
        release.set()


@pytest.mark.browser
def test_failed_queue_job_keeps_its_stage_visible_after_an_empty_cycle(dashboard):
    page, app, _ = dashboard
    app.state.store.set_settings(
        Settings(automation_enabled=True, ai_document_preparation=True, linkedin_authorised=True)
    )
    app.state.service.selector = Mock(
        side_effect=PreparationError("AI advice failed; no documents or applications were sent")
    )
    page.get_by_role("button", name="Run agent cycle", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Agent cycle completed")
    page.get_by_text("Recent application results", exact=True).click()
    expect(page.locator("#worker-results")).to_contain_text("Failed")
    expect(page.locator("#worker-results")).to_contain_text("Failure at selecting evidence")
    expect(page.locator("#worker-results")).to_contain_text("PreparationError")
    assert app.state.store.daily_usage().used == 0
    page.get_by_role("button", name="Run agent cycle", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Agent cycle completed: {}")
    expect(page.locator("#worker-results")).to_contain_text("Failure at selecting evidence")
    app.state.service.selector.assert_called_once()


def assert_networking_accessibility(page):
    axe = Path("node_modules/axe-core/axe.min.js").read_text(encoding="utf-8")
    page.route(
        "**/__test/networking-axe.js",
        lambda route: route.fulfill(content_type="text/javascript", body=axe),
    )
    page.add_script_tag(url=page.url.split("#", 1)[0] + "__test/networking-axe.js")
    result = page.evaluate(
        "async () => await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa']}})"
    )
    assert not result["violations"]


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize(
    "section",
    [
        "Overview",
        "Applications",
        "Candidate profile",
        "Networking",
        "Agent settings",
        "Activity log",
    ],
)
def test_all_views_pass_axe_wcag_checks(dashboard, section, width):
    page, _, _ = dashboard
    page.set_viewport_size({"width": width, "height": 1000})
    page.get_by_role("button", name=section, exact=True).click()
    axe = Path("node_modules/axe-core/axe.min.js").read_text(encoding="utf-8")
    page.route(
        "**/__test/axe.js", lambda route: route.fulfill(content_type="text/javascript", body=axe)
    )
    page.add_script_tag(url=page.url.split("#", 1)[0] + "__test/axe.js")
    result = page.evaluate(
        "async () => await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa']}})"
    )
    assert not result["violations"], [
        (item["id"], [node["target"] for node in item["nodes"]]) for item in result["violations"]
    ]
    assert page.locator('[aria-current="page"]').inner_text() == section


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 768, 1440])
def test_responsive_views_do_not_overflow_and_use_local_assets(dashboard, width, tmp_path):
    page, _, origin = dashboard
    requests = []
    page.on("request", lambda request: requests.append(request.url))
    page.set_viewport_size({"width": width, "height": 900})
    for section in [
        "Overview",
        "Applications",
        "Candidate profile",
        "Networking",
        "Agent settings",
        "Activity log",
    ]:
        page.get_by_role("button", name=section, exact=True).click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), section
    page.get_by_role("button", name="Overview", exact=True).click()
    page.screenshot(path=str(tmp_path / f"dashboard-{width}.png"), full_page=True)
    assert all(url.startswith(origin + "/") for url in requests)


@pytest.mark.browser
def test_stored_markup_is_displayed_as_text(dashboard):
    page, app, _ = dashboard
    hostile = '<img src=x onerror="window.injected=true">'
    profile, _ = app.state.store.profile()
    profile.evidence[0].title = hostile
    profile.evidence[0].text = "<script>window.injected=true</script>"
    app.state.store.save_profile(profile)
    page.reload()
    expect(page.locator("#workspace")).to_be_visible()
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    expect(page.locator("#evidence-list strong")).to_have_text(hostile)
    assert page.locator("#evidence-list img, #evidence-list script").count() == 0
    assert page.evaluate("window.injected") is None


@pytest.mark.browser
def test_malformed_answers_are_explained_without_saving(dashboard):
    page, app, _ = dashboard
    original_revision = app.state.store.profile()[1]
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    page.get_by_role("button", name="Edit candidate profile", exact=True).click()
    answers = page.get_by_label("Approved form answers (JSON object)", exact=True)
    for value in ['{"salary":', "[]", '{"salary":123}']:
        answers.fill(value)
        page.get_by_role("button", name="Save candidate profile", exact=True).click()
        expect(page.locator("#notice")).to_contain_text("Approved answers must be")
    assert app.state.store.profile()[1] == original_revision


@pytest.mark.browser
def test_stale_profile_save_preserves_newer_record_and_the_draft(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    page.get_by_role("button", name="Edit candidate profile", exact=True).click()
    field = page.get_by_label("Professional summary (approved wording)", exact=True)
    field.fill("Draft in this tab")
    newer, _ = app.state.store.profile()
    newer.summary = "Candidate-approved newer record"
    app.state.store.save_profile(newer)
    page.get_by_role("button", name="Save candidate profile", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Candidate profile changed. Reload")
    expect(field).to_have_value("Draft in this tab")
    assert app.state.store.profile()[0].summary == newer.summary


@pytest.mark.browser
def test_lock_clears_token_and_candidate_content_then_allows_unlock(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    expect(page.locator("#workspace")).to_be_hidden()
    expect(page.locator("#login")).to_be_visible()
    assert page.evaluate("sessionStorage.getItem('applicator-token')") is None
    assert app.state.store.profile()[0].email not in page.locator("body").inner_text()
    assert page.locator("#evidence-list").inner_html() == ""
    assert page.locator("#profile-form").count() == 0
    page.get_by_label("Access token", exact=True).fill(TOKEN)
    page.get_by_role("button", name="Unlock workspace").click()
    expect(page.locator("#workspace")).to_be_visible()


@pytest.mark.browser
def test_invalid_and_expired_tokens_return_to_login(dashboard):
    page, _, origin = dashboard
    page.route(
        "**/api/settings",
        lambda route: route.fulfill(
            status=401,
            content_type="application/json",
            body='{"detail":"A valid local access token is required"}',
        ),
    )
    page.reload()
    expect(page.locator("#login")).to_be_visible()
    expect(page.locator("#notice")).to_contain_text("A valid local access token")
    assert page.evaluate("sessionStorage.getItem('applicator-token')") is None
    page.get_by_label("Access token", exact=True).fill("invalid")
    page.get_by_role("button", name="Unlock workspace").click()
    expect(page.locator("#workspace")).to_be_hidden()
    assert page.url == origin + "/"


@pytest.mark.browser
def test_job_edit_can_be_cancelled_and_paused_submission_is_disabled(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="View application queue", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    expect(page.get_by_role("button", name="Run authorised submission")).to_be_disabled()
    page.get_by_role("button", name="Edit job details", exact=True).click()
    page.locator('#job-form input[name="title"]').fill("Unsaved job title")
    page.get_by_role("button", name="Cancel editing", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    page.get_by_role("button", name="Add opportunity", exact=True).click()
    expect(page.locator('#job-form input[name="title"]')).to_have_value("")
    expect(page.get_by_role("button", name="Save opportunity", exact=True)).to_be_visible()
    assert app.state.store.applications()[0]["job"]["title"] == "Backend Engineer"


@pytest.mark.browser
def test_duplicate_clicks_are_suppressed_and_pause_remains_available(dashboard):
    page, app, _ = dashboard
    app.state.store.set_settings(Settings(linkedin_authorised=True, automation_enabled=True))
    page.reload()
    expect(page.locator("#readiness")).to_contain_text("Agent enabled")
    page.get_by_role("button", name="Applications", exact=True).click()
    held = []
    page.route("**/api/discover/linkedin", lambda route: held.append(route))
    button = page.locator("#linkedin-search")
    button.click()
    # Reproduce a second event while the operation is pending; native controls are disabled.
    button.dispatch_event("click")
    page.get_by_role("button", name="Pause all automation", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Automation paused.")
    assert len(held) == 1
    assert not app.state.store.settings().automation_enabled
    held[0].fulfill(status=200, content_type="application/json", body='{"imported":0}')
    expect(page.locator("#workspace")).not_to_have_attribute("aria-busy", "true")


@pytest.mark.browser
@pytest.mark.parametrize("outcome", ["imported", "empty", "failed"])
def test_linkedin_job_search_shows_progress_and_result(dashboard, outcome):
    page, _, _ = dashboard
    page.set_viewport_size({"width": 390, "height": 900})
    page.get_by_role("button", name="Applications", exact=True).click()
    held = []
    page.route("**/api/discover/linkedin", lambda route: held.append(route))
    button = page.locator("#linkedin-search")
    status = page.locator("#linkedin-search-status")
    button.click()
    expect(button).to_have_text("Searching…")
    expect(button).to_have_attribute("aria-busy", "true")
    expect(button).to_be_disabled()
    expect(status).to_have_text("Searching LinkedIn and reading job details…")
    assert_networking_accessibility(page)
    assert len(held) == 1
    if outcome == "failed":
        held[0].fulfill(
            status=502,
            content_type="application/json",
            body='{"detail":"The browser could not read the LinkedIn job search."}',
        )
        expect(status).to_contain_text("Search failed.")
        expect(page.locator("#notice")).to_contain_text("The browser could not read")
    else:
        held[0].fulfill(
            status=200,
            content_type="application/json",
            body='{"imported":' + ("2" if outcome == "imported" else "0") + "}",
        )
        expect(status).to_contain_text(
            "2 new opportunities imported."
            if outcome == "imported"
            else "No new opportunities to import"
        )
    expect(button).to_have_text("Search LinkedIn")
    expect(button).not_to_have_attribute("aria-busy", "true")
    expect(button).to_be_enabled()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.browser
def test_enlarged_text_and_keyboard_navigation_are_usable(dashboard):
    page, _, _ = dashboard
    page.route(
        "**/__test/zoom.css",
        lambda route: route.fulfill(content_type="text/css", body="html { font-size: 200%; }"),
    )
    page.add_style_tag(url=page.url.split("#", 1)[0] + "__test/zoom.css")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("button", name="Overview", exact=True).focus()
    page.keyboard.press("Tab")
    page.keyboard.press("Enter")
    expect(page.locator("#page-title")).to_have_text("Applications")
    page.get_by_role("button", name="Agent settings", exact=True).click()
    expect(page.get_by_label("Daily sent-application limit")).to_be_visible()


@pytest.mark.browser
def test_approved_dropdown_answer_and_sensitive_question_handling(dashboard):
    page, app, _ = dashboard
    row = app.state.store.applications()[0]
    job = Job.model_validate(row["job"])
    job.questions = [
        Question(id="salary", label="Expected salary?", choices=["To be discussed", "50000"]),
        Question(id="health", label="Medical history", sensitive=True),
    ]
    app.state.store.update_job(row["id"], job)
    app.state.service.prepare(row["id"])
    page.reload()
    expect(page.locator("#workspace")).to_be_visible()
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    page.get_by_role("tab", name="Questions (2)", exact=True).click()
    expect(
        page.get_by_text("Medical history: requires manual handling.", exact=True)
    ).to_be_visible()
    page.get_by_label("Expected salary?", exact=True).select_option("To be discussed")
    page.get_by_role("button", name="Approve answer", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Answer approved.")
    assert app.state.store.profile()[0].answers["question:expected salary?"] == "To be discussed"
    assert not app.state.store.application(row["id"])["manifest"]


@pytest.mark.browser
def test_evidence_update_and_removal_invalidate_documents(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    page.locator("#evidence-list").get_by_role("button", name="Edit", exact=True).click()
    page.locator("#evidence-form").get_by_label("Title", exact=True).fill(
        "Candidate-reviewed API project"
    )
    page.get_by_role("button", name="Save evidence", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Evidence saved.")
    assert app.state.store.profile()[0].evidence[0].title == "Candidate-reviewed API project"
    assert not app.state.store.applications()[0]["manifest"]
    page.locator("#evidence-list").get_by_role("button", name="Remove", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Evidence removed")
    assert not app.state.store.profile()[0].evidence
    expect(page.locator("#evidence-list")).to_contain_text("Add a qualification")


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_networking_form_queues_a_contact_and_missing_scope_send_is_held(
    dashboard, width, tmp_path
):
    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 1000})
    page.get_by_role("button", name="Networking", exact=True).click()
    page.get_by_role("button", name="Add contact", exact=True).click()
    for label, value in [
        ("LinkedIn profile URL", "https://www.linkedin.com/in/example-recruiter/"),
        ("Member's displayed name", "Example Recruiter"),
        ("Displayed role / headline", "Technical Recruiter"),
        ("Displayed European location", "Dublin, Ireland"),
    ]:
        page.get_by_label(label, exact=True).fill(value)
    page.get_by_role("button", name="Queue contact", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Contact queued")
    expect(page.locator("#connections")).to_contain_text("Example Recruiter")
    link = page.get_by_role("link", name=re.compile("^Open LinkedIn profile for Example Recruiter"))
    expect(link).to_have_attribute("href", "https://www.linkedin.com/in/example-recruiter/")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    page.context.route(
        "https://www.linkedin.com/**",
        lambda route: route.fulfill(content_type="text/html", body="<h1>Fictional member</h1>"),
    )
    with page.expect_popup() as waiting:
        link.click()
    popup = waiting.value
    expect(popup.get_by_role("heading")).to_have_text("Fictional member")
    assert popup.evaluate("window.opener === null && document.referrer === ''")
    popup.close()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(tmp_path / f"networking-{width}.png"), full_page=True)
    axe = Path("node_modules/axe-core/axe.min.js").read_text(encoding="utf-8")
    page.route(
        "**/__test/axe.js", lambda route: route.fulfill(content_type="text/javascript", body=axe)
    )
    page.add_script_tag(url=page.url.split("#", 1)[0] + "__test/axe.js")
    result = page.evaluate(
        "async () => await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa']}})"
    )
    assert not result["violations"]
    app.state.store.set_settings(Settings())
    page.get_by_role("button", name="Send queued invitation", exact=True).click()
    expect(page.locator("#notice")).to_contain_text(
        "Configure the declared LinkedIn authorisation scope first"
    )
    expect(page.locator(".invitation-progress")).to_contain_text("Failed")
    assert app.state.network.list()[0]["state"] == "queued"
    assert app.state.network.list()[0]["day"] is None


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_manual_invitation_runs_only_selected_contact_with_live_progress(
    dashboard, monkeypatch, width, tmp_path
):
    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 1000})
    candidate, _ = app.state.store.profile()
    candidate.confirmed = False
    app.state.store.save_profile(candidate)
    app.state.network.add(
        "https://www.linkedin.com/in/example-recruiter/",
        "Example Recruiter",
        "Technical Recruiter",
        "Dublin, Ireland",
    )
    app.state.network.add(
        "https://www.linkedin.com/in/other/", "Other Recruiter", "Recruiter", "Ireland"
    )
    applications = app.state.store.applications()
    revision = app.state.store.profile()[1]
    started = threading.Event()
    complete = threading.Event()
    calls = []

    def send(connection_id, *, manual):
        calls.append((connection_id, manual))
        row = app.state.network.reserve(connection_id, manual=manual)
        started.set()
        assert complete.wait(timeout=30)
        app.state.network.finish(connection_id, "fixture:pending", run_id=row["run_id"])
        return "fixture:pending"

    monkeypatch.setattr(app.state.network, "send", send)
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    card = page.locator('[data-connection-id="1"]')
    button = card.get_by_role("button", name="Send queued invitation", exact=True)
    try:
        button.click()
        expect(card.locator(".invitation-progress")).to_contain_text("Started")
        assert started.wait(timeout=5)
        button.dispatch_event("click")
        expect(page.locator("#workspace")).not_to_have_attribute("aria-busy", "true")
        expect(page.locator('[data-connection-id="2"] button')).to_be_disabled()
        row = app.state.network.status(1)
        app.state.network.progress(1, row["run_id"], "Checking the selected member's identity.")
        expect(card.locator(".invitation-progress")).to_contain_text("Running")
        expect(card.locator(".invitation-progress")).to_contain_text("Checking the selected member")
        assert_networking_accessibility(page)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(tmp_path / f"invitation-running-{width}.png"), full_page=True)
        page.get_by_role("button", name="Candidate profile", exact=True).click()
        expect(
            page.get_by_role("button", name="Edit candidate profile", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Networking", exact=True).click()
    finally:
        complete.set()
    expect(card.locator(".invitation-progress")).to_contain_text("Done")
    expect(page.locator("#notice")).to_contain_text("Invitation confirmed")
    expect(page.get_by_role("tab", name="Active (1)", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    expect(page.locator('#connections [data-connection-id="1"]')).to_have_count(0)
    page.get_by_role("tab", name="Archived (1)", exact=True).click()
    expect(card).to_be_visible()
    expect(card.get_by_role("button", name="Send queued invitation", exact=True)).to_have_count(0)
    assert_networking_accessibility(page)
    assert calls == [(1, True)]
    assert app.state.network.status(2)["state"] == "queued"
    assert app.state.network.status(2)["day"] is None
    assert app.state.store.applications() == applications
    assert app.state.store.profile()[1] == revision
    assert not app.state.store.settings().automation_enabled


@pytest.mark.browser
def test_connection_profile_links_remain_available_after_send_or_uncertainty(dashboard):
    page, app, _ = dashboard
    for slug, receipt in [("sent-example", "fixture:pending"), ("uncertain-example", None)]:
        app.state.network.add(
            f"https://www.linkedin.com/in/{slug}/", slug, "Recruiter", "Dublin, Ireland"
        )
        app.state.network.finish(app.state.network.list()[0]["id"], receipt)
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    for slug in ["sent-example", "uncertain-example"]:
        page.get_by_role(
            "tab", name="Archived (1)" if slug == "sent-example" else "Active (1)", exact=True
        ).click()
        link = page.get_by_role("link", name=re.compile(f"^Open LinkedIn profile for {slug}"))
        expect(link).to_have_attribute("href", f"https://www.linkedin.com/in/{slug}/")
    expect(page.get_by_role("button", name="Send queued invitation", exact=True)).to_have_count(0)


@pytest.mark.browser
@pytest.mark.parametrize("uncertain", [False, True])
@pytest.mark.parametrize("width", [390, 1440])
def test_invitation_failure_reports_safe_or_uncertain_outcome(
    dashboard, monkeypatch, uncertain, width
):
    from playwright.sync_api import Error as BrowserError

    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 1000})
    app.state.network.add("https://www.linkedin.com/in/example/", "Example", "Recruiter", "Ireland")

    def send(connection_id, *, manual):
        row = app.state.network.reserve(connection_id, manual=manual)
        if uncertain:
            app.state.network.finish(connection_id, None, run_id=row["run_id"])
        else:
            with app.state.store.connect(True) as db:
                db.execute(
                    "UPDATE connections SET state='failed',run_status='failed',run_message='The browser stopped before connecting.' WHERE id=?",
                    (connection_id,),
                )
        raise BrowserError("private-provider-cookie")

    monkeypatch.setattr(app.state.network, "send", send)
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    page.get_by_role("button", name="Send queued invitation", exact=True).click()
    expect(page.locator(".invitation-progress")).to_contain_text(
        "Needs review" if uncertain else "Failed"
    )
    expect(page.locator(".invitation-progress")).to_contain_text(
        "Check LinkedIn" if uncertain else "before connecting"
    )
    expect(page.get_by_role("button", name="Send queued invitation", exact=True)).to_have_count(0)
    assert "private-provider-cookie" not in page.locator("body").inner_text()
    assert_networking_accessibility(page)


@pytest.mark.browser
def test_lost_send_response_keeps_observing_and_never_resends(dashboard):
    page, app, _ = dashboard
    app.state.network.add("https://www.linkedin.com/in/example/", "Example", "Recruiter", "Ireland")
    requests = []

    def lost_response(route):
        requests.append(route.request.url)
        row = app.state.network.reserve(1, manual=True)
        app.state.network.progress(1, row["run_id"], "Waiting for confirmation.")
        route.fulfill(status=502, content_type="text/plain", body="Connection lost")

    page.route("**/api/connections/1/send", lost_response)
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    page.get_by_role("button", name="Send queued invitation", exact=True).click()
    expect(page.locator(".invitation-progress")).to_contain_text("Running")
    row = app.state.network.status(1)
    app.state.network.finish(1, "fixture:pending", run_id=row["run_id"])
    expect(page.locator(".invitation-progress")).to_contain_text("Done")
    assert len(requests) == 1


@pytest.mark.browser
def test_reload_observes_existing_invitation_and_status_errors_do_not_resend(dashboard):
    page, app, _ = dashboard
    app.state.network.add("https://www.linkedin.com/in/example/", "Example", "Recruiter", "Ireland")
    row = app.state.network.reserve(1, manual=True)
    app.state.network.progress(1, row["run_id"], "Checking the selected profile.")
    sends, polls = [], []
    page.on(
        "request",
        lambda request: sends.append(request.url) if request.url.endswith("/send") else None,
    )

    def first_status_fails(route):
        polls.append(route.request.url)
        if len(polls) == 1:
            route.fulfill(
                status=502,
                content_type="application/json",
                body='{"detail":"Status temporarily unavailable"}',
            )
        else:
            route.continue_()

    page.route("**/api/connections/1/status", first_status_fails)
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    expect(page.locator(".invitation-progress")).to_contain_text("Running")
    app.state.network.finish(1, None, run_id=row["run_id"])
    expect(page.locator(".invitation-progress")).to_contain_text("Needs review")
    assert not sends
    assert len(polls) >= 2


@pytest.mark.browser
def test_lock_during_invitation_clears_progress_without_repeating_send(dashboard):
    page, app, _ = dashboard
    app.state.network.add("https://www.linkedin.com/in/example/", "Example", "Recruiter", "Ireland")
    held = []
    page.route("**/api/connections/1/send", lambda route: held.append(route))
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    page.get_by_role("button", name="Send queued invitation", exact=True).click()
    expect(page.locator(".invitation-progress")).to_contain_text("Started")
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    assert len(held) == 1
    held[0].fulfill(
        status=200, content_type="application/json", body='{"receipt":"fixture:pending"}'
    )
    expect(page.locator("#workspace")).to_be_hidden()
    assert page.locator("#connections").inner_html() == ""
    assert page.evaluate("sessionStorage.getItem('applicator-token')") is None


@pytest.mark.browser
def test_pdf_downloads_contain_approved_facts_and_no_external_requests(dashboard, tmp_path):
    page, app, _ = dashboard
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    with page.expect_download() as waiting:
        page.get_by_role("button", name=re.compile(r"^Download .*_CV\.pdf$")).click()
    download = waiting.value
    path = tmp_path / download.suggested_filename
    download.save_as(path)
    text = " ".join(item.extract_text() for item in PdfReader(path).pages)
    assert app.state.store.profile()[0].email in text
    assert "independent" in text.casefold()


@pytest.mark.browser
def test_lock_during_pending_request_does_not_restore_private_content(dashboard):
    page, _, _ = dashboard
    page.get_by_role("button", name="Applications", exact=True).click()
    held = []
    page.route("**/api/discover/linkedin", lambda route: held.append(route))
    page.get_by_role("button", name="Search LinkedIn", exact=True).click()
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    held[0].fulfill(status=200, content_type="application/json", body='{"imported":0}')
    expect(page.locator("#workspace")).not_to_have_attribute("aria-busy", "true")
    expect(page.locator("#workspace")).to_be_hidden()
    expect(page.locator("#linkedin-search-status")).to_have_text("")
    expect(page.locator("#linkedin-search")).to_have_text("Search LinkedIn")
    assert page.locator("#evidence-list").inner_html() == ""
    assert page.evaluate("sessionStorage.getItem('applicator-token')") is None


@pytest.mark.browser
def test_manual_receipt_and_outcome_are_persisted(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    page.get_by_role("tab", name="Activity & outcome", exact=True).click()
    page.get_by_label("Manual submission receipt or confirmation reference", exact=True).fill(
        "candidate-confirmed-fixture-receipt"
    )
    page.get_by_role("button", name="Record confirmed manual submission", exact=True).click()
    page.get_by_label("Record outcome", exact=True).select_option("interview")
    page.get_by_role("button", name="Save outcome", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Outcome saved.")
    assert app.state.store.applications()[0]["outcome"] == "interview"
    page.get_by_role("button", name="Overview", exact=True).click()
    expect(page.locator("#insights")).to_contain_text("Interviews")


@pytest.mark.browser
def test_board_import_and_non_json_provider_errors_are_readable(dashboard):
    page, _, _ = dashboard
    page.get_by_role("button", name="Applications", exact=True).click()
    page.route(
        "**/api/discover/greenhouse",
        lambda route: route.fulfill(content_type="application/json", body='{"imported":2}'),
    )
    page.get_by_role("button", name="Import from Greenhouse", exact=True).click()
    page.get_by_label("Greenhouse board", exact=True).fill("fixture-employer")
    page.get_by_role("button", name="Import board jobs", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Imported 2 new opportunities.")
    page.unroute("**/api/discover/greenhouse")
    page.route(
        "**/api/discover/greenhouse",
        lambda route: route.fulfill(
            status=502, content_type="text/html", body="Provider unavailable"
        ),
    )
    page.get_by_role("button", name="Import from Greenhouse", exact=True).click()
    page.get_by_label("Greenhouse board", exact=True).fill("fixture-employer")
    page.get_by_role("button", name="Import board jobs", exact=True).click()
    expect(page.locator("#notice")).to_have_text("The request failed (502). Please try again.")


@pytest.mark.browser
def test_settings_thresholds_and_paused_cycle_match_displayed_state(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Agent settings", exact=True).click()
    page.get_by_label("Automatic threshold", exact=True).fill("95")
    page.get_by_label("Review threshold", exact=True).fill("60")
    page.get_by_role("button", name="Save agent settings", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Agent settings saved.")
    assert app.state.store.settings().auto_threshold == 95
    page.get_by_role("button", name="Overview", exact=True).click()
    expect(page.locator("#policy-bands")).to_contain_text("95–100")
    expect(page.locator("#policy-bands")).to_contain_text("60–94")
    page.get_by_role("button", name="Run agent cycle", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Agent cycle completed: {}")


@pytest.mark.browser
def test_job_updates_and_ai_failure_preserve_current_opportunity(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    page.get_by_role("button", name="Edit job details", exact=True).click()
    page.locator("#job-form").get_by_label("Job description", exact=True).fill(
        "Python FastAPI PostgreSQL. Candidate-reviewed revised description."
    )
    page.get_by_role("button", name="Save updated opportunity", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Opportunity imported.")
    assert "revised description" in app.state.store.applications()[0]["job"]["description"]
    assert not app.state.store.applications()[0]["manifest"]
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    page.route(
        "**/api/applications/*/prepare",
        lambda route: route.fulfill(
            status=503,
            content_type="application/json",
            body='{"detail":"Set a fresh OPENAI_API_KEY locally to enable the AI adviser"}',
        ),
    )
    page.get_by_role("button", name="Select evidence with GPT-6.1 Sol", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Set a fresh OPENAI_API_KEY locally")


@pytest.mark.browser
def test_queue_search_status_sort_and_clear_preserve_the_underlying_records(dashboard):
    page, app, _ = dashboard
    original = Job.model_validate(app.state.store.applications()[0]["job"])
    for source_id, title, company, technologies in [
        ("platform", "Platform Engineer", "Acme", ["Go"]),
        ("data", "Data Analyst", "Zed", ["Python", "Rust"]),
    ]:
        job = original.model_copy(
            update={
                "source_id": source_id,
                "title": title,
                "company": company,
                "requirements": technologies,
                "url": f"https://example.test/{source_id}",
            }
        )
        app_id, _ = app.state.store.add_job(job)
        app.state.service.prepare(app_id)
    before = app.state.store.applications()
    page.reload()
    expect(page.locator("#notice")).not_to_have_class("error")
    page.get_by_role("button", name="Applications", exact=True).click()
    expect(page.locator("#queue-count")).to_have_text("3 of 3 opportunities shown")
    page.get_by_label("Sort opportunities", exact=True).select_option("fit")
    expect(page.locator("#application-list td strong")).to_have_text(
        ["Backend Engineer", "Data Analyst", "Platform Engineer"]
    )
    page.get_by_label("Sort opportunities", exact=True).select_option("company")
    expect(page.locator("#application-list td strong")).to_have_text(
        ["Platform Engineer", "Backend Engineer", "Data Analyst"]
    )
    page.get_by_label("Search opportunities", exact=True).fill("  ENGINEER ACME ireland ")
    expect(page.locator("#queue-count")).to_have_text("1 of 3 opportunities shown")
    page.get_by_label("Application status", exact=True).select_option("review")
    expect(page.locator("#application-list")).to_contain_text(
        "No opportunities match these filters"
    )
    page.get_by_role("button", name="Clear filters", exact=True).click()
    expect(page.locator("#queue-count")).to_have_text("3 of 3 opportunities shown")
    page.get_by_label("Application status", exact=True).select_option("review")
    page.get_by_role("button", name="Open Data Analyst at Zed", exact=True).click()
    page.get_by_role("button", name="Prepare documents", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Documents prepared from approved evidence.")
    expect(page.get_by_label("Application status", exact=True)).to_have_value("review")
    expect(page.locator("#queue-count")).to_have_text("1 of 3 opportunities shown")
    assert [row["job"] for row in app.state.store.applications()] == [row["job"] for row in before]
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    expect(page.get_by_label("Search opportunities", exact=True)).to_have_value("")
    expect(page.get_by_label("Application status", exact=True)).to_have_value("all")


@pytest.mark.browser
def test_daily_budget_displays_reserved_uncertain_attempts(dashboard):
    page, app, _ = dashboard
    app.state.store.set_settings(Settings(automation_enabled=True, daily_limit=1))
    row = app.state.store.applications()[0]
    attempt = app.state.store.reserve(row["id"], row["revision"])
    app.state.store.finish(row["id"], attempt, None)
    page.reload()
    expect(page.locator("#daily-usage")).to_contain_text("0 / 1 applications sent")
    expect(page.locator("#readiness")).to_contain_text("0 sending slots remaining today")
    expect(
        page.get_by_role("progressbar", name="Daily confirmed application usage")
    ).to_have_attribute("value", "0")
    assert app.state.store.daily_usage().remaining == 0


def linkedin_opportunity(app):
    job = Job.model_validate(app.state.store.applications()[0]["job"])
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    app_id, _ = app.state.store.add_job(job)
    app.state.service.prepare(app_id)
    app.state.store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True))
    return app_id


@pytest.mark.browser
def test_preflight_recheck_and_mocked_submission_update_budget_and_timeline(dashboard, monkeypatch):
    from applicator.browser import LinkedInBrowser

    page, app, _ = dashboard
    app_id = linkedin_opportunity(app)
    adapter = Mock(return_value="fixture:confirmed-readiness")
    monkeypatch.setattr(LinkedInBrowser, "submit", adapter)
    page.reload()
    expect(page.locator("#readiness")).to_contain_text("Agent enabled")
    page.get_by_role("button", name="Applications", exact=True).click()
    page.locator("#application-list tbody tr").first.get_by_role("button").click()
    checks = page.get_by_role("region", name="Local submission checks")
    expect(checks).to_contain_text("All local checks passed.")
    before = app.state.store.events(app_id)
    page.get_by_role("button", name="Recheck readiness", exact=True).click()
    expect(page.locator("#workspace")).not_to_have_attribute("aria-busy", "true")
    assert app.state.store.events(app_id) == before
    assert app.state.store.daily_usage().used == 0
    adapter.assert_not_called()
    page.get_by_role("button", name="Run authorised submission", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Provider receipt recorded.")
    assert app.state.store.application(app_id)["receipt"] == "fixture:confirmed-readiness"
    adapter.assert_called_once()
    expect(page.locator("#daily-usage")).to_contain_text("1 / 10 applications sent")
    page.get_by_role("tab", name="Activity & outcome", exact=True).click()
    page.get_by_text("Activity for this application", exact=True).click()
    expect(page.locator(".timeline")).to_contain_text("submission finished")
    expect(page.locator(".timeline")).to_contain_text("submission reserved")
    expect(page.locator(".timeline")).not_to_contain_text("settings updated")
    page.get_by_label("Record outcome", exact=True).select_option("offer")
    page.get_by_role("button", name="Save outcome", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Outcome saved.")
    page.get_by_role("tab", name="Overview", exact=True).click()
    page.get_by_role("button", name="Recheck readiness", exact=True).click()
    page.get_by_role("tab", name="Activity & outcome", exact=True).click()
    expect(page.get_by_label("Record outcome", exact=True)).to_have_value("offer")


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_preflight_blocks_changed_profile_and_passes_accessibility_checks(dashboard, width):
    page, app, _ = dashboard
    app_id = linkedin_opportunity(app)
    page.reload()
    expect(page.locator("#readiness")).to_contain_text("Agent enabled")
    page.set_viewport_size({"width": width, "height": 1000})
    page.get_by_role("button", name="Applications", exact=True).click()
    page.locator("#application-list tbody tr").first.get_by_role("button").click()
    profile, _ = app.state.store.profile()
    profile.confirmed = False
    app.state.store.save_profile(profile)
    page.get_by_role("button", name="Recheck readiness", exact=True).click()
    expect(page.get_by_role("region", name="Local submission checks")).to_contain_text(
        "Confirm the candidate facts first."
    )
    expect(page.locator("#workspace")).not_to_have_attribute("aria-busy", "true")
    assert page.get_by_role("button", name="Run authorised submission", exact=True).count() == 0
    assert app.state.store.daily_usage().used == 0
    page.get_by_role("tab", name="Activity & outcome", exact=True).click()
    page.get_by_text("Activity for this application", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.locator(".timeline")).to_have_attribute("open", "")
    axe = Path("node_modules/axe-core/axe.min.js").read_text(encoding="utf-8")
    page.route(
        "**/__test/axe.js", lambda route: route.fulfill(content_type="text/javascript", body=axe)
    )
    page.add_script_tag(url=page.url.split("#", 1)[0] + "__test/axe.js")
    result = page.evaluate(
        "async () => await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa']}})"
    )
    assert not result["violations"], [(item["id"], item["nodes"]) for item in result["violations"]]
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert app.state.store.application(app_id)["state"] == "review"


@pytest.mark.browser
def test_empty_queue_and_activity_states_are_explained(dashboard):
    page, _, _ = dashboard
    for pattern in ["**/api/applications", "**/api/events", "**/api/applications/*/events"]:
        page.route(pattern, lambda route: route.fulfill(content_type="application/json", body="[]"))
    page.reload()
    expect(page.locator("#workspace")).to_be_visible()
    page.get_by_role("button", name="Applications", exact=True).click()
    expect(page.locator("#application-list")).to_contain_text("No opportunities yet.")
    expect(page.locator("#queue-count")).to_have_text("0 of 0 opportunities shown")
    page.get_by_role("button", name="Activity log", exact=True).click()
    expect(page.locator("#events")).to_contain_text("No activity recorded yet.")


@pytest.mark.browser
def test_recruiter_discovery_displays_browser_failure_and_recovers(dashboard, monkeypatch):
    from playwright.sync_api import Error as BrowserError

    import applicator.api as module

    page, app, _ = dashboard
    discover = Mock(side_effect=BrowserError("Internal provider timeout"))
    monkeypatch.setattr(module.LinkedInBrowser, "contacts", discover)
    page.get_by_role("button", name="Networking", exact=True).click()
    page.get_by_role("button", name="Find European recruiters", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("The browser could not read or complete")
    expect(page.locator("#notice")).not_to_contain_text("Internal provider timeout")
    discover.side_effect = None
    discover.return_value = [
        {
            "url": "https://www.linkedin.com/in/example/",
            "name": "Example Recruiter",
            "role": "Technical Recruiter",
            "location": "Dublin, Ireland",
        }
    ]
    page.get_by_role("button", name="Find European recruiters", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Reviewed 1 European hiring contacts.")
    expect(page.locator("#connections")).to_contain_text("Example Recruiter")
    assert app.state.network.list()[0]["state"] == "queued"
    assert app.state.network.list()[0]["receipt"] is None


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("outcome", ["success", "empty", "failure"])
def test_recruiter_search_shows_loading_prevents_duplicates_and_finishes(
    dashboard, monkeypatch, outcome, width
):
    from playwright.sync_api import Error as BrowserError

    import applicator.api as module

    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 1000})
    app.state.store.set_settings(Settings(linkedin_authorised=True, daily_connection_limit=5))
    started, complete = threading.Event(), threading.Event()
    calls = []
    original_profile = app.state.store.profile()
    original_applications = app.state.store.applications()

    def discover(self, location, limit, *, exclude_urls):
        calls.append((location, limit, exclude_urls))
        started.set()
        assert complete.wait(timeout=30)
        if outcome == "failure":
            raise BrowserError("private-provider-diagnostic")
        return (
            []
            if outcome == "empty"
            else [
                {
                    "url": f"https://www.linkedin.com/in/example-{index}/",
                    "name": f"Example Recruiter {index}",
                    "role": "Recruiter",
                    "location": "Ireland",
                }
                for index in range(5)
            ]
        )

    monkeypatch.setattr(module.LinkedInBrowser, "contacts", discover)
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    try:
        page.get_by_role("button", name="Find European recruiters", exact=True).click()
        loading = page.get_by_role("button", name="Searching…", exact=True)
        expect(loading).to_be_disabled()
        expect(loading).to_have_attribute("aria-busy", "true")
        expect(page.locator("#contact-search-status")).to_contain_text("up to 5 new European")
        assert started.wait(timeout=5)
        loading.dispatch_event("click")
        assert calls == [("Ireland", 5, set())]
        assert_networking_accessibility(page)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        complete.set()
    button = page.get_by_role("button", name="Find European recruiters", exact=True)
    expect(button).to_be_enabled()
    expect(button).not_to_have_attribute("aria-busy", "true")
    if outcome == "success":
        expect(page.locator("#contact-search-status")).to_have_text(
            "Search complete. 5 new European hiring contacts found."
        )
        expect(page.get_by_role("tab", name="Active (5)", exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        assert len(app.state.network.list()) == 5
    elif outcome == "empty":
        expect(page.locator("#contact-search-status")).to_contain_text("No new matching contacts")
        page.get_by_role("tab", name="Archived (0)", exact=True).click()
        expect(page.locator("#archived-connections")).to_contain_text("No archived invitations yet")
    else:
        expect(page.locator("#contact-search-status")).to_contain_text("Search failed")
        expect(page.locator("#notice")).to_contain_text("The browser could not read or complete")
        assert "private-provider-diagnostic" not in page.locator("body").inner_text()
    assert calls == [("Ireland", 5, set())]
    assert app.state.network.remaining() == 5
    assert app.state.store.profile() == original_profile
    assert app.state.store.applications() == original_applications
    assert_networking_accessibility(page)


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_connection_archive_preserves_history_and_has_accessible_keyboard_tabs(
    dashboard, width, tmp_path
):
    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 1000})
    for index, state in enumerate(["queued", "uncertain", "failed", "sent"], start=1):
        app.state.network.add(
            f"https://www.linkedin.com/in/example-{index}/",
            f"Example Recruiter {index}",
            "Recruiter",
            "Ireland",
        )
        if state in {"uncertain", "sent"}:
            app.state.network.finish(index, "fixture:pending" if state == "sent" else None)
        elif state == "failed":
            with app.state.store.connect(True) as db:
                db.execute("UPDATE connections SET state='failed' WHERE id=?", (index,))
    original_rows = app.state.network.list()
    original_events = app.state.store.events()
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    active = page.get_by_role("tab", name="Active (3)", exact=True)
    archived = page.get_by_role("tab", name="Archived (1)", exact=True)
    expect(active).to_have_attribute("aria-selected", "true")
    expect(page.locator("#connections .entry")).to_have_count(3)
    expect(page.locator("#connections")).not_to_contain_text("Example Recruiter 4")
    active.focus()
    active.press("End")
    expect(archived).to_be_focused()
    expect(archived).to_have_attribute("aria-selected", "true")
    expect(page.locator("#connections-active-panel")).to_be_hidden()
    expect(page.locator("#archived-connections .entry")).to_have_count(1)
    expect(page.locator("#archived-connections")).to_contain_text("Done")
    expect(page.get_by_role("button", name="Send queued invitation", exact=True)).to_have_count(0)
    expect(
        page.get_by_role("link", name=re.compile("^Open LinkedIn profile for Example Recruiter 4"))
    ).to_have_attribute("href", "https://www.linkedin.com/in/example-4/")
    assert_networking_accessibility(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.screenshot(path=str(tmp_path / f"networking-archive-{width}.png"), full_page=True)
    archived.press("ArrowLeft")
    expect(active).to_be_focused()
    active.press("ArrowRight")
    expect(archived).to_be_focused()
    archived.press("Home")
    expect(active).to_be_focused()
    active.press("Tab")
    expect(page.locator("#connections-active-panel")).to_be_focused()
    assert app.state.network.list() == original_rows
    assert app.state.store.events() == original_events
    assert_networking_accessibility(page)
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    assert page.locator("#archived-connections").inner_html() == ""
    expect(page.locator("#connections-active-tab")).to_have_text("Active (0)")
    expect(page.locator("#connections-archived-tab")).to_have_text("Archived (0)")


@pytest.mark.browser
def test_lock_during_contact_search_discards_the_late_response(dashboard):
    page, _, _ = dashboard
    held = []
    page.route("**/api/discover/contacts", lambda route: held.append(route))
    page.get_by_role("button", name="Networking", exact=True).click()
    page.get_by_role("button", name="Find European recruiters", exact=True).click()
    expect(page.locator("#contact-search-status")).to_contain_text("Searching")
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    assert len(held) == 1
    held[0].fulfill(status=200, content_type="application/json", body='{"reviewed":5}')
    expect(page.locator("#workspace")).to_be_hidden()
    expect(page.locator("#contact-search-status")).to_have_text("")
    expect(page.locator("#contact-search")).not_to_have_attribute("aria-busy", "true")
    assert page.locator("#connections").inner_html() == ""
    assert page.locator("#archived-connections").inner_html() == ""


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_contact_photos_are_private_cached_and_location_is_highlighted(dashboard, width, tmp_path):
    from test_contact_photos import example_photo

    from applicator.photos import save_photo

    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 1000})
    for index in range(1, 4):
        url = f"https://www.linkedin.com/in/photo-example-{index}/"
        app.state.network.add(
            url, f"Example Recruiter {index}", "Technical Recruiter", "Dublin, Ireland"
        )
        if index < 3:
            assert save_photo(app.state.network.data, url, example_photo())
        if index == 2:
            app.state.network.finish(index, "fixture:pending")
    requested = []
    page.on(
        "request",
        lambda request: requested.append(request) if request.url.endswith("/photo") else None,
    )
    page.add_init_script(
        "window.revokedPhotos=[]; const original=URL.revokeObjectURL; URL.revokeObjectURL=url=>{window.revokedPhotos.push(url);original.call(URL,url)}"
    )
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    first = page.locator('[data-connection-id="1"]')
    image = first.get_by_role("img", name="Profile photo of Example Recruiter 1", exact=True)
    expect(image).to_be_visible()
    expect(image).to_have_attribute("src", re.compile("^blob:"))
    expect(first.locator(".contact-initials")).to_be_hidden()
    expect(first.locator(".contact-location")).to_have_text("Dublin, Ireland")
    expect(first.locator(".contact-role")).to_have_text("Technical Recruiter")
    assert image.bounding_box()["width"] == image.bounding_box()["height"] == 64
    assert (
        first.locator(".contact-location").evaluate("el => Number(getComputedStyle(el).fontWeight)")
        >= 600
    )
    expect(page.locator('[data-connection-id="3"] .contact-initials')).to_be_visible()
    assert len(requested) == 1
    assert requested[0].headers["authorization"] == "Bearer " + TOKEN
    blob_url = image.get_attribute("src")
    page.get_by_role("tab", name="Archived (1)", exact=True).click()
    expect(
        page.get_by_role("img", name="Profile photo of Example Recruiter 2", exact=True)
    ).to_be_visible()
    assert len(requested) == 2
    assert_networking_accessibility(page)
    page.screenshot(path=str(tmp_path / f"contact-photo-archive-{width}.png"), full_page=True)
    page.get_by_role("tab", name="Active (2)", exact=True).click()
    expect(image).to_be_visible()
    assert len(requested) == 2
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    assert page.evaluate("url=>window.revokedPhotos.includes(url)", blob_url)
    assert page.locator("#connections img, #archived-connections img").count() == 0


@pytest.mark.browser
@pytest.mark.parametrize(
    "failure", ["missing", "wrong_type", "oversized", "corrupt", "unauthorised"]
)
def test_contact_photo_failure_keeps_initials_or_locks_invalid_auth(dashboard, failure):
    from test_contact_photos import example_photo

    from applicator.photos import save_photo

    page, app, _ = dashboard
    url = "https://www.linkedin.com/in/photo-example/"
    app.state.network.add(url, "Example Recruiter", "Recruiter", "Ireland")
    assert save_photo(app.state.network.data, url, example_photo())
    page.route(
        "**/api/connections/1/photo",
        lambda route: route.fulfill(
            status=401 if failure == "unauthorised" else 404 if failure == "missing" else 200,
            content_type="text/plain" if failure == "wrong_type" else "image/png",
            body=b"x" * 512001
            if failure == "oversized"
            else b"not an image"
            if failure == "corrupt"
            else example_photo(),
        ),
    )
    page.reload()
    if failure == "unauthorised":
        expect(page.locator("#workspace")).to_be_hidden()
        assert page.locator("#connections img").count() == 0
    else:
        page.get_by_role("button", name="Networking", exact=True).click()
        expect(page.locator(".contact-initials")).to_be_visible()
        expect(page.locator(".contact-avatar img")).to_be_hidden()
        expect(page.locator("#connections")).to_contain_text("Example Recruiter")
        assert_networking_accessibility(page)


@pytest.mark.browser
def test_lock_during_photo_download_discards_the_late_image(dashboard):
    from test_contact_photos import example_photo

    from applicator.photos import save_photo

    page, app, _ = dashboard
    url = "https://www.linkedin.com/in/photo-example/"
    app.state.network.add(url, "Example Recruiter", "Recruiter", "Ireland")
    assert save_photo(app.state.network.data, url, example_photo())
    held = []
    page.route("**/api/connections/1/photo", lambda route: held.append(route))
    page.reload()
    page.get_by_role("button", name="Networking", exact=True).click()
    expect(page.locator(".contact-initials")).to_be_visible()
    assert len(held) == 1
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    held[0].fulfill(content_type="image/png", body=example_photo())
    expect(page.locator("#workspace")).to_be_hidden()
    assert page.locator("#connections img, #archived-connections img").count() == 0
