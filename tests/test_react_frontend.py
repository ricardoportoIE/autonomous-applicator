"""React migration parity, native dialogue behaviour and document tab regressions."""

import re
import threading
from pathlib import Path

import pytest
from playwright.sync_api import expect
from test_browser import TOKEN
from test_frontend import dashboard as dashboard

from applicator.browser import LinkedInBrowser
from applicator.models import Settings
from applicator.service import PreparationError


def check_accessibility(page):
    axe = Path("node_modules/axe-core/axe.min.js").read_text(encoding="utf-8")
    page.route(
        "**/__test/axe.js", lambda route: route.fulfill(content_type="text/javascript", body=axe)
    )
    page.add_script_tag(url=page.url.split("#", 1)[0] + "__test/axe.js")
    result = page.evaluate(
        "async () => await axe.run(document, {runOnly: {type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})"
    )
    assert not result["violations"], [
        (item["id"], [node["target"] for node in item["nodes"]]) for item in result["violations"]
    ]


@pytest.mark.browser
@pytest.mark.parametrize("existing", [False, True])
def test_url_only_modal_imports_with_loading_and_preserves_duplicates(
    dashboard, job, monkeypatch, existing
):
    page, app, _ = dashboard
    store = app.state.store
    original = store.applications()
    store.set_settings(Settings(linkedin_authorised=True))
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    if existing:
        store.add_job(job)
    held = threading.Event()
    calls = []

    def read(self, url):
        calls.append(url)
        self.report("extracting_opportunity", "Reading the job details.")
        assert held.wait(15), "The browser test did not release the import"
        return job

    monkeypatch.setattr(LinkedInBrowser, "read_opportunity", read)
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name="Add opportunity", exact=True).click()
    assert page.get_by_label("Job title", exact=True).count() == 0
    page.get_by_label("Job URL", exact=True).fill(job.url)
    page.get_by_role("button", name="Save opportunity", exact=True).click()
    try:
        expect(page.get_by_role("button", name="Importing…", exact=True)).to_be_disabled()
        expect(page.get_by_role("dialog")).to_contain_text("Opening the opportunity")
        page.locator("#job-form").dispatch_event("submit")
    finally:
        held.set()
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.locator("#notice")).to_contain_text(
        "already in your queue" if existing else "preparation queue"
    )
    assert calls == [job.url]
    assert len(store.applications()) == len(original) + 1
    imported = next(row for row in store.applications() if row["source_id"] == "123")
    assert imported["job"] == job.model_dump()
    assert all(row in store.applications() for row in original)
    assert store.daily_usage().used == 0


@pytest.mark.browser
def test_url_import_failure_retains_draft_and_manual_entry(dashboard):
    page, app, _ = dashboard
    before = app.state.store.applications()
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name="Add opportunity", exact=True).click()
    url = "https://example.test/job"
    page.get_by_label("Job URL", exact=True).fill(url)
    page.get_by_role("button", name="Save opportunity", exact=True).click()
    expect(page.get_by_role("dialog").get_by_role("alert")).to_contain_text(
        "Enable company-site applications"
    )
    expect(page.get_by_label("Job URL", exact=True)).to_have_value(url)
    expect(page.get_by_role("button", name="Save opportunity", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Enter details manually", exact=True).click()
    expect(page.get_by_label("Job title", exact=True)).to_be_visible()
    assert app.state.store.applications() == before


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize(
    "view,button,title",
    [
        ("Applications", "Add opportunity", "Add an opportunity"),
        ("Applications", "Import from Greenhouse", "Import Greenhouse opportunities"),
        ("Candidate profile", "Edit candidate profile", "Edit candidate profile"),
        ("Candidate profile", "Add evidence", "Add evidence"),
        ("Networking", "Add contact", "Queue a professional connection"),
    ],
)
def test_native_modals_are_accessible_contain_focus_and_restore_it(
    dashboard, width, view, button, title
):
    page, app, _ = dashboard
    before = app.state.store.profile()[1]
    page.set_viewport_size({"width": width, "height": 900})
    page.get_by_role("button", name=view, exact=True).click()
    trigger = page.get_by_role("button", name=button, exact=True)
    assert page.get_by_role("dialog").count() == 0
    trigger.click()
    dialogue = page.get_by_role("dialog", name=title, exact=True)
    expect(dialogue).to_be_visible()
    check_accessibility(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for _ in range(16):
        page.keyboard.press("Tab")
        assert page.evaluate("Boolean(document.activeElement.closest('dialog'))")
    page.keyboard.press("Escape")
    expect(dialogue).to_have_count(0)
    expect(trigger).to_be_focused()
    assert app.state.store.profile()[1] == before


@pytest.mark.browser
def test_add_opportunity_and_evidence_from_modals_preserve_all_contract_fields(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name="Add opportunity", exact=True).click()
    page.get_by_role("button", name="Enter details manually", exact=True).click()
    for label, value in [
        ("Job title", "Data Engineer"),
        ("Company", "Example Data"),
        ("Location", "London, United Kingdom"),
        ("Job URL", "https://example.test/jobs/data"),
        ("Job description", "Build Python data pipelines."),
        ("Required technologies, comma-separated", "Python, SQL, Python"),
    ]:
        page.get_by_label(label, exact=True).fill(value)
    page.get_by_label("Sponsorship", exact=True).select_option("available")
    page.get_by_label("Cover letter required", exact=True).check()
    page.get_by_role("button", name="Save opportunity", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    job = app.state.store.applications()[0]["job"]
    assert job["requirements"] == ["Python", "SQL"]
    assert job["sponsorship"] == "available" and job["cover_letter_required"]
    assert job["source"] == "manual" and len(job["source_id"]) == 64
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    page.get_by_role("button", name="Add evidence", exact=True).click()
    for label, value in [
        ("Evidence identifier", "degree"),
        ("Title", "Approved qualification"),
        ("Factual description", "Candidate-confirmed qualification."),
        ("Evidence source", "Approved certificate"),
        ("Dates as confirmed", "2025"),
        ("Technology tags, comma-separated", "SQL, Python"),
    ]:
        page.get_by_label(label, exact=True).fill(value)
    page.get_by_label("Category", exact=True).select_option("education")
    page.get_by_label("Reviewed and approved for applications", exact=True).check()
    page.get_by_role("button", name="Save evidence", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    evidence = next(e for e in app.state.store.profile()[0].evidence if e.id == "degree")
    assert evidence.category == "education" and evidence.verified and evidence.dates == "2025"
    assert evidence.source == "Approved certificate" and evidence.tags == ["SQL", "Python"]
    assert not app.state.store.application(1)["manifest"]


@pytest.mark.browser
def test_profile_modal_saves_all_approved_facts_and_retains_draft_on_error(dashboard):
    page, app, _ = dashboard
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    page.get_by_role("button", name="Edit candidate profile", exact=True).click()
    page.get_by_label("Professional summary (approved wording)", exact=True).fill(
        "Approved revised summary."
    )
    page.get_by_label("Professional links, one per line", exact=True).fill(
        "https://example.test/portfolio\nhttps://example.test/portfolio"
    )
    page.get_by_label("Approved form answers (JSON object)", exact=True).fill("[]")
    page.get_by_role("button", name="Save candidate profile", exact=True).click()
    expect(page.get_by_role("dialog").get_by_role("alert")).to_contain_text(
        "Approved answers must be"
    )
    expect(page.get_by_label("Professional summary (approved wording)", exact=True)).to_have_value(
        "Approved revised summary."
    )
    page.get_by_label("Approved form answers (JSON object)", exact=True).fill(
        '{"question:sponsorship?":"Yes"}'
    )
    page.get_by_role("button", name="Save candidate profile", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    profile, revision = app.state.store.profile()
    assert revision == 2 and profile.summary == "Approved revised summary."
    assert (
        profile.links == ["https://example.test/portfolio"]
        and profile.answers["question:sponsorship?"] == "Yes"
    )
    assert profile.evidence and profile.confirmed and profile.sponsorship_required


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_application_tabs_keep_full_opportunity_documents_questions_and_activity(dashboard, width):
    page, app, _ = dashboard
    page.set_viewport_size({"width": width, "height": 900})
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    page.get_by_text("Full opportunity details", exact=True).click()
    expect(page.get_by_text("Cover letter: Not required", exact=True)).to_be_visible()
    for label in [re.compile("^Documents"), re.compile("^Questions"), "Activity & outcome"]:
        page.get_by_role("tab", name=label).click()
        check_accessibility(page)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.get_by_role("tab", name=re.compile("^Documents")).click()
    page.get_by_text("Choose approved evidence manually", exact=True).click()
    page.get_by_role("button", name="Prepare with selected evidence", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Documents prepared from approved evidence.")
    assert app.state.store.application(1)["manifest"]["generation"]["method"] == "manual"
    page.get_by_role("tab", name="Overview", exact=True).click()
    expect(page.get_by_role("region", name="Document preparation")).to_contain_text(
        "Evidence selected manually"
    )
    assert app.state.store.daily_usage().used == 0


@pytest.mark.browser
def test_lock_closes_open_modal_and_discards_candidate_draft(dashboard):
    page, app, _ = dashboard
    revision = app.state.store.profile()[1]
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    page.get_by_role("button", name="Edit candidate profile", exact=True).click()
    page.get_by_label("Professional summary (approved wording)", exact=True).fill(
        "Private unsaved draft"
    )
    # A real modal deliberately makes the background inert; close before using the global lock.
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert "Private unsaved draft" not in page.locator("body").inner_text()
    assert app.state.store.profile()[1] == revision


@pytest.mark.browser
def test_failed_ai_preparation_refreshes_document_provenance_and_review_state(dashboard):
    page, app, _ = dashboard

    def failed_selection(*_args):
        raise PreparationError("AI preparation could not finish. Review this opportunity.")

    app.state.service.selector = failed_selection
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    expect(page.get_by_role("region", name="Document preparation")).to_contain_text("local rules")
    page.get_by_role("button", name="Select evidence with GPT-6.1 Sol", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("AI preparation could not finish")
    expect(page.get_by_role("region", name="Document preparation")).to_contain_text(
        "Preparation origin is unavailable"
    )
    expect(page.locator("#application-detail .badge").first).to_have_text("For review")
    assert page.get_by_role("button", name=re.compile("^Download ")).count() == 0
    assert app.state.store.application(1)["state"] == "review"
    assert app.state.store.daily_usage().used == 0


@pytest.mark.browser
def test_transient_read_failure_recovers_without_repeating_a_command(dashboard):
    page, app, _ = dashboard
    calls = []

    def temporary_failure(route):
        calls.append(route.request.method)
        if len(calls) == 1:
            route.abort("connectionreset")
        else:
            route.continue_()

    page.route("**/api/settings", temporary_failure)
    page.reload()
    expect(page.locator("#workspace")).to_be_visible()
    assert calls == ["GET", "GET"]
    assert app.state.store.daily_usage().used == 0


@pytest.mark.browser
def test_lock_during_opportunity_hashing_cannot_import_a_stale_draft(dashboard):
    page, app, _ = dashboard
    before = app.state.store.applications()
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name="Add opportunity", exact=True).click()
    page.get_by_role("button", name="Enter details manually", exact=True).click()
    for label, value in [
        ("Job title", "Unsaved role"),
        ("Company", "Example"),
        ("Location", "Ireland"),
        ("Job URL", "https://example.test/jobs/unsaved"),
        ("Job description", "Private unsaved candidate draft"),
    ]:
        page.get_by_label(label, exact=True).fill(value)
    page.evaluate(
        "() => {crypto.subtle.digest = () => new Promise(resolve => {window.finishHash = () => resolve(new ArrayBuffer(32));});}"
    )
    page.get_by_role("button", name="Save opportunity", exact=True).click()
    page.get_by_role("button", name="Close dialogue", exact=True).click()
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    page.get_by_label("Access token", exact=True).fill(TOKEN)
    page.get_by_role("button", name="Unlock workspace", exact=True).click()
    expect(page.locator("#notice")).to_have_text("Local workspace unlocked.")
    requests = []
    page.on("request", lambda request: requests.append((request.method, request.url)))
    page.evaluate("async () => {window.finishHash(); await new Promise(requestAnimationFrame);}")
    expect(page.locator("#workspace")).not_to_have_attribute("aria-busy", "true")
    assert not any(method == "POST" and url.endswith("/api/jobs") for method, url in requests)
    assert app.state.store.applications() == before
