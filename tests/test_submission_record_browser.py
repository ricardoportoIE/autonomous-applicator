"""Real provider fixtures and the complete private application record page."""

import re
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from playwright.sync_api import Page, expect
from test_browser import LINKEDIN_HTML, TOKEN, server
from test_frontend import dashboard as dashboard
from test_react_frontend import check_accessibility
from test_store_service import setup

from applicator.browser import FixtureBrowser, LinkedInBrowser, browser_options
from applicator.models import Job, Question, Settings, State
from applicator.policy import answer_questions


@pytest.mark.browser
@pytest.mark.parametrize("capture_failure", [False, True])
def test_linkedin_visible_confirmation_archives_actual_form_and_screenshot(
    data, profile, job, monkeypatch, capture_failure
):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    job.description = "Python FastAPI PostgreSQL"

    def fixture_context(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )
        context.route(
            "**/*", lambda route: route.fulfill(content_type="text/html", body=LINKEDIN_HTML)
        )
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    if capture_failure:
        monkeypatch.setattr(
            Page, "screenshot", Mock(side_effect=TimeoutError("Screenshot timeout"))
        )
    store, service, app_id = setup(data, profile, job)
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True))
    adapter = LinkedInBrowser(data, profile)
    service.adapters["linkedin"] = adapter
    stages = []
    assert (
        service.submit(app_id, progress=lambda stage, _: stages.append(stage))
        == "linkedin:123:confirmed"
    )
    assert "capturing_confirmation" in stages
    attempt = service.records.read(app_id)["attempts"][0]
    assert attempt["sent_at"] and attempt["confirmed_at"]
    fields = attempt["fields"]
    assert any(item["label"] == "Email" and item["value"] == profile.email for item in fields)
    assert any(item["type"] == "file" and item["value"].endswith("_CV.pdf") for item in fields)
    assert {item["step"] for item in fields} == {1, 2}
    assert store.application(app_id)["state"] == State.SUBMITTED and store.daily_usage().used == 1
    if capture_failure:
        assert attempt["confirmation"] == {"url": job.url, "capture_error": "TimeoutError"}
        assert not list((data / "submissions").rglob("*.png"))
    else:
        evidence = attempt["confirmation"]
        assert evidence["url"] == job.url and evidence["captured_at"]
        assert (
            service.records.artifact(app_id, attempt["id"], "confirmation")
            .read_bytes()
            .startswith(b"\x89PNG")
        )


@pytest.mark.browser
def test_real_local_employer_fixture_captures_confirmation_only_after_send(data, profile, job):
    employer = FastAPI()

    @employer.get("/apply")
    def form():
        return HTMLResponse(
            """<meta charset="utf-8"><h1>Example Employer</h1><form><label>Email<input type="email" required></label><label>CV<input type="file" required></label><button>Submit application</button></form><p id="receipt"></p><script>document.querySelector('form').onsubmit=e=>{e.preventDefault();document.querySelector('#receipt').textContent='fixture:employer-confirmed';}</script>"""
        )

    with server(employer) as origin:
        job.url = origin + "/apply"
        job.questions = [Question(id="Email", label="Email", answer_key="email")]
        store, service, app_id = setup(data, profile, job, FixtureBrowser())
        assert not list((data / "submissions").rglob("*.png"))
        assert service.submit(app_id) == "fixture:employer-confirmed"
        attempt = service.records.read(app_id)["attempts"][0]
        assert attempt["confirmation"]["url"] == job.url
        assert any(
            item["label"] == "Email" and item["value"] == profile.email
            for item in attempt["fields"]
        )
        assert service.records.artifact(app_id, attempt["id"], "confirmation").stat().st_size > 1000
        assert store.daily_usage().used == 1


def add_confirmed_record(app, origin):
    store, service = app.state.store, app.state.service
    row = store.applications()[0]
    profile, revision = store.profile()
    attempt = store.reserve(row["id"], revision)
    answers, unresolved = answer_questions(Job.model_validate(row["job"]), profile)
    assert not unresolved
    service.records.begin(
        row["id"],
        attempt,
        profile,
        revision,
        Job.model_validate(row["job"]),
        row["manifest"],
        answers,
    )
    service.records.observe(
        row["id"],
        attempt,
        [
            {"label": "E-mail address", "type": "text", "value": profile.email, "step": 1},
            {"label": "Follow employer", "type": "checkbox", "checked": False, "step": 1},
            {
                "label": "CV",
                "type": "file",
                "value": row["manifest"]["files"]["cv_pdf"]["name"],
                "step": 1,
            },
        ],
    )
    store.mark_sending(row["id"], attempt, revision, Job.model_validate(row["job"]))
    store.finish(row["id"], attempt, "fixture:private-confirmation")
    return row["id"], attempt


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_full_record_has_private_proof_archived_downloads_dates_and_accessible_layout(
    dashboard, width
):
    page, app, origin = dashboard
    app.state.store.set_settings(Settings(automation_enabled=True))
    app_id, attempt = add_confirmed_record(app, origin)
    page.set_viewport_size({"width": width, "height": 950})
    page.reload()
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("tab", name="Archive (1)", exact=True).click()
    page.get_by_role("button", name=re.compile("^Open Backend Engineer")).click()
    page.get_by_role("link", name="View full application record", exact=True).click()
    expect(
        page.get_by_role("heading", name="Application record", exact=True, level=1)
    ).to_be_visible()
    expect(page.get_by_role("heading", name="Candidate snapshot", exact=True)).to_be_visible()
    expect(page.get_by_role("article", name="Submission history")).to_contain_text(
        "fixture:private-confirmation"
    )
    expect(page.get_by_role("article", name="Observed application form")).to_contain_text(
        "alex@example.test"
    )
    expect(page.get_by_role("article", name="Observed application form")).to_contain_text(
        "Not selected"
    )
    expect(page.get_by_role("link", name="Open original opportunity")).to_have_attribute(
        "href", "https://example.test/jobs/backend"
    )
    expect(
        page.get_by_text("No confirmation screenshot is available for this attempt.", exact=True)
    ).to_be_visible()
    from applicator.submission_records import capture_confirmation

    evidence = capture_confirmation(page, app.state.service.records.folder(app_id, attempt))
    app.state.service.records.confirmation(app_id, attempt, evidence)
    page.reload()
    expect(
        page.get_by_role("img", name=re.compile("Provider submission confirmation"))
    ).to_be_visible()
    expect(page.get_by_role("link", name="Open recorded confirmation page")).to_have_attribute(
        "href", evidence["url"]
    )
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="Download confirmation screenshot", exact=True).click()
    assert downloaded.value.suggested_filename.endswith("confirmation.png")
    assert Path(downloaded.value.path()).read_bytes().startswith(b"\x89PNG")
    with page.expect_download() as pdf:
        page.get_by_role("button", name=re.compile("^Download .+_CV.pdf$")).click()
    assert Path(pdf.value.path()).read_bytes().startswith(b"%PDF")
    page.get_by_text("Reviewed evidence used in these documents", exact=True).click()
    expect(
        page.locator("#application-record").get_by_text("Independent API project", exact=True)
    ).to_be_visible()
    page.get_by_text("Complete preparation metadata", exact=True).click()
    expect(page.locator("#application-record pre")).to_contain_text("sha256")
    check_accessibility(page)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    folder = Path("test-results/application-record-layouts")
    folder.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(folder / f"record-{width}.png"), full_page=True)
    assert page.url.endswith(f"#/applications/{app_id}")
    page.get_by_role("button", name="Back to application queue", exact=True).click()
    expect(page.get_by_role("heading", name="Application queue", exact=True)).to_be_visible()
    expect(page.get_by_role("tab", name="Active (0)", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    expect(
        page.get_by_role("link", name=re.compile("^Full record for Backend Engineer"))
    ).to_have_count(0)
    page.get_by_role("tab", name="Archive (1)", exact=True).click()
    page.get_by_role("link", name=re.compile("^Full record for Backend Engineer")).click()
    expect(page.locator("#application-record")).to_be_visible()
    page.get_by_role("button", name="Manage this application", exact=True).click()
    expect(page.locator("#application-detail")).to_be_visible()
    page.goto(origin + f"/#/applications/{app_id}")
    expect(page.locator("#application-record")).to_be_visible()
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    expect(page.locator("#application-record")).to_have_count(0)
    assert not page.evaluate("document.body.innerText.includes('alex@example.test')")


@pytest.mark.browser
def test_record_journal_paginates_and_switches_historical_and_uncertain_attempts(dashboard):
    page, app, origin = dashboard
    store, service = app.state.store, app.state.service
    store.set_settings(Settings(automation_enabled=True))
    row = store.applications()[0]
    old = store.reserve(row["id"], 1)
    store.finish(row["id"], old, None)
    store.confirm_not_sent(row["id"], 1)
    service.prepare(row["id"])
    new = store.reserve(row["id"], 1)
    service.records.begin(
        row["id"],
        new,
        store.profile()[0],
        1,
        Job.model_validate(row["job"]),
        store.application(row["id"])["manifest"],
        {},
    )
    store.finish(row["id"], new, None)
    for number in range(210):
        with store.connect() as db:
            store.event(db, "fixture_record_history", str(number), row["id"])
    page.goto(origin + f"/#/applications/{row['id']}")
    expect(page.get_by_role("article", name="Submission history")).to_contain_text(
        "Pending or uncertain"
    )
    expect(page.get_by_role("article", name="Observed application form")).to_contain_text(
        "No provider form observations"
    )
    expect(page.get_by_role("button", name="Load older activity", exact=True)).to_be_visible()
    page.get_by_role("button", name="Load older activity", exact=True).click()
    expect(page.get_by_role("button", name="Load older activity", exact=True)).to_have_count(0)
    expect(page.get_by_role("article", name="Application activity")).to_contain_text(
        f"{service.records.read(row['id'])['dates']['event_count']} of {service.records.read(row['id'])['dates']['event_count']} entries loaded"
    )
    page.get_by_label("Submission attempt", exact=True).select_option(str(old))
    expect(
        page.get_by_text(re.compile("Historical attempt: no submission snapshot"))
    ).to_be_visible()
    expect(page.get_by_role("article", name="Candidate snapshot")).to_have_count(0)


@pytest.mark.browser
def test_record_deep_link_requires_login_and_reports_missing_record(dashboard):
    page, app, origin = dashboard
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    page.goto(origin + "/#/applications/1")
    expect(page.locator("#application-record")).to_have_count(0)
    page.get_by_label("Access token", exact=True).fill(TOKEN)
    page.get_by_role("button", name="Unlock workspace").click()
    expect(page.locator("#application-record")).to_be_visible()
    expect(page.get_by_text("No submission attempt has been started.", exact=True)).to_be_visible()
    page.goto(origin + "/#/applications/999")
    expect(page.locator("#notice")).not_to_be_empty()
    expect(
        page.get_by_text("Application record unavailable. Check the message above.", exact=True)
    ).to_be_visible()
    page.get_by_role("button", name="Back to application queue", exact=True).click()
    expect(page.locator('[data-section="applications"]')).to_be_visible()


@pytest.mark.browser
def test_record_preserves_questionnaire_cover_documents_and_capture_issue(dashboard):
    page, app, origin = dashboard
    store, service = app.state.store, app.state.service
    row = store.applications()[0]
    vacancy = Job.model_validate(row["job"])
    vacancy.cover_letter_required = True
    vacancy.questions = [
        Question(
            id="sponsor",
            label="Sponsorship required?",
            answer_key="sponsorship",
            choices=["Yes", "No"],
        ),
        Question(id="contact", label="Contact email", answer_key="email", required=False),
    ]
    store.update_job(row["id"], vacancy)
    service.prepare(row["id"])
    store.set_settings(Settings(automation_enabled=True))
    app_id, attempt = add_confirmed_record(app, origin)
    service.records.confirmation(
        app_id, attempt, {"url": origin + "/confirmation", "capture_error": "TimeoutError"}
    )
    page.goto(origin + f"/#/applications/{app_id}")
    expect(page.get_by_role("heading", name="Candidate snapshot", exact=True)).to_be_visible()
    page.get_by_text("Recorded application questions", exact=True).click()
    opportunity = page.get_by_role("article", name="Opportunity and decision", exact=True)
    expect(opportunity).to_contain_text("Sponsorship required? · Required · Yes / No")
    expect(opportunity).to_contain_text("Contact email · Optional")
    documents = page.get_by_role("article", name="Archived documents for this attempt", exact=True)
    page.get_by_text("Approved answers supplied to the adapter", exact=True).click()
    expect(documents).to_contain_text("Sponsorship required?")
    expect(documents).to_contain_text("alex@example.test")
    expect(
        documents.get_by_role("button", name=re.compile("^Download .+_Cover_Letter.pdf$"))
    ).to_be_visible()
    page.get_by_text("Opportunity snapshot for this attempt", exact=True).click()
    expect(page.get_by_role("article", name="Candidate snapshot")).to_contain_text(
        vacancy.description
    )
    confirmation = page.get_by_role("article", name="Provider confirmation", exact=True)
    expect(confirmation).to_contain_text(
        "Capture issue: TimeoutError. The confirmed receipt remains recorded."
    )
    expect(
        confirmation.get_by_role("link", name="Open recorded confirmation page")
    ).to_have_attribute("href", origin + "/confirmation")
    expect(page.get_by_role("article", name="Submission history")).to_contain_text(
        "Confirmed submission"
    )
    assert store.daily_usage().used == 1
    check_accessibility(page)


@pytest.mark.browser
def test_missing_private_image_keeps_confirmed_receipt_and_archived_cv_available(dashboard):
    page, app, origin = dashboard
    store, service = app.state.store, app.state.service
    store.set_settings(Settings(automation_enabled=True))
    app_id, attempt = add_confirmed_record(app, origin)
    service.records.confirmation(
        app_id,
        attempt,
        {"url": origin + "/confirmation", "name": "confirmation.png", "sha256": "missing-file"},
    )
    page.goto(origin + f"/#/applications/{app_id}")
    expect(
        page.get_by_text(
            "The confirmation screenshot is unavailable or failed its integrity check.", exact=True
        )
    ).to_be_visible()
    expect(page.get_by_role("article", name="Submission history")).to_contain_text(
        "fixture:private-confirmation"
    )
    expect(
        page.get_by_role("button", name="Download confirmation screenshot", exact=True)
    ).to_have_count(0)
    with page.expect_download() as pdf:
        page.get_by_role("button", name=re.compile("^Download .+_CV.pdf$")).click()
    assert Path(pdf.value.path()).read_bytes().startswith(b"%PDF")
    assert store.application(app_id)["state"] == State.SUBMITTED
    assert store.daily_usage().used == 1 and len(service.records.read(app_id)["attempts"]) == 1
