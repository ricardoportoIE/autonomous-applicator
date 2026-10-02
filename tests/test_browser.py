import socket
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from playwright.sync_api import sync_playwright

from applicator.api import create_app
from applicator.browser import (
    FixtureBrowser,
    LinkedInBrowser,
    approved_answer,
    browser_options,
    describe_questions,
    ensure_linkedin,
    fill_questions,
    form_questions,
    linkedin_job_id,
)
from applicator.documents import generate

TOKEN = "browser-fixture-local-token-01234567890123456789"


@contextmanager
def server(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    runner = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    thread = threading.Thread(target=runner.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    ready = threading.Event()
    for _ in range(200):
        if runner.started:
            break
        ready.wait(0.02)
    assert runner.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        runner.should_exit = True
        thread.join(timeout=5)
        sock.close()


@pytest.mark.browser
def test_fixture_real_browser_submission(profile, job, tmp_path):
    app = FastAPI()

    @app.get("/apply")
    def form():
        return HTMLResponse(
            """<form><label>Email<input type="email" required></label><label>CV<input type="file" required></label><button type="submit">Submit application</button></form><p id="receipt"></p><script>document.querySelector('form').onsubmit=e=>{e.preventDefault();document.querySelector('#receipt').textContent='fixture:confirmed';}</script>"""
        )

    with server(app) as origin:
        job.url = origin + "/apply"
        generate(profile, job, ["python"], tmp_path, 1)
        assert (
            FixtureBrowser().submit(job, {"Email": profile.email}, tmp_path) == "fixture:confirmed"
        )


@pytest.mark.browser
def test_dashboard_full_journey(data, profile, tmp_path):
    app = create_app(data, TOKEN)
    with server(app) as origin, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(origin)
        page.get_by_label("Access token", exact=True).fill(TOKEN)
        page.get_by_role("button", name="Unlock workspace").click()
        page.get_by_role("button", name="Candidate profile", exact=True).click()
        page.get_by_label("Professional name", exact=True).fill(profile.name)
        page.get_by_label("E-mail", exact=True).fill(profile.email)
        page.get_by_label("Phone", exact=True).fill(profile.phone)
        page.locator("#profile-form").get_by_label("Location", exact=True).fill(profile.location)
        page.get_by_label("I have reviewed and confirmed the candidate facts").check()
        page.get_by_role("button", name="Save candidate profile").click()
        page.get_by_text("Profile saved. Earlier documents need regeneration.").wait_for()
        evidence = profile.evidence[0]
        for label, value in (
            ("Evidence identifier", evidence.id),
            ("Title", evidence.title),
            ("Factual description", evidence.text),
            ("Technology tags, comma-separated", ",".join(evidence.tags)),
            ("Evidence source", evidence.source),
        ):
            page.locator("#evidence-form").get_by_label(label, exact=True).fill(value)
        page.get_by_label("Category", exact=True).select_option("project")
        page.get_by_label("Reviewed and approved for applications").check()
        page.get_by_role("button", name="Save evidence", exact=True).click()
        page.get_by_text("Evidence saved.").wait_for()
        page.get_by_role("button", name="Applications", exact=True).click()
        for label, value in (
            ("Job title", "Backend Engineer"),
            ("Company", "Example Employer"),
            ("Location", "Dublin, Ireland"),
            ("Job URL", "https://example.test/job/1"),
            ("Job description", "Python FastAPI PostgreSQL"),
            ("Required technologies, comma-separated", "Python, FastAPI, PostgreSQL"),
        ):
            page.locator("#job-form").get_by_label(label, exact=True).fill(value)
        page.get_by_role("button", name="Save opportunity").click()
        page.get_by_role("button", name="Open", exact=True).first.click()
        page.get_by_role("button", name="Prepare documents", exact=True).click()
        page.get_by_text("Documents prepared from approved evidence.").wait_for()
        assert app.state.store.applications()[0]["evaluation"]["score"] == 100
        page.get_by_role("button", name="Agent settings", exact=True).click()
        page.get_by_label("Daily application attempt limit").fill("10")
        page.get_by_role("button", name="Save agent settings").click()
        page.get_by_text("Agent settings saved.").wait_for()
        page.get_by_role("button", name="Overview", exact=True).click()
        page.screenshot(path=str(tmp_path / "dashboard.png"), full_page=True)
        assert not errors
        browser.close()


def test_browser_contracts(profile, job, tmp_path, monkeypatch):
    assert linkedin_job_id("https://www.linkedin.com/jobs/view/123/?tracking=1") == "123"
    for url in (
        "https://evil.test/jobs/view/123/",
        "http://www.linkedin.com/jobs/view/123/",
        "https://www.linkedin.com/in/person/",
    ):
        with pytest.raises(ValueError):
            linkedin_job_id(url)
    with pytest.raises(ValueError):
        ensure_linkedin(Mock(url="https://evil.test/"))
    with pytest.raises(ValueError):
        ensure_linkedin(Mock(url="https://www.linkedin.com/checkpoint/challenge"))
    assert approved_answer("Email address", profile) == profile.email
    assert approved_answer("First name", profile) == "Alex"
    assert approved_answer("Last name", profile) == "Example"
    assert approved_answer("Unknown salary", profile) is None
    profile.answers["question:how many years?"] = "2"
    assert approved_answer("How many years?", profile) == "2"
    monkeypatch.setenv("APPLICATOR_BROWSER_CHANNEL", "malicious")
    with pytest.raises(ValueError):
        browser_options()
    monkeypatch.setenv("APPLICATOR_BROWSER_CHANNEL", "msedge")
    assert browser_options() == {"channel": "msedge"}
    monkeypatch.delenv("APPLICATOR_BROWSER_CHANNEL", raising=False)
    monkeypatch.setattr(Path, "is_file", lambda path: False)
    assert browser_options() == {}
    job.url = "https://evil.test/"
    with pytest.raises(ValueError):
        FixtureBrowser().submit(job, {}, tmp_path)


@pytest.mark.browser
def test_linkedin_form_controls_are_grounded(profile):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        page = browser.new_page()
        page.set_content(
            '<div role="dialog"><label>Email<input id="email" required></label><label>Will you require sponsorship?<select id="sponsorship" required><option>No</option><option>Yes</option></select></label><label>Optional field<input id="optional"></label></div>'
        )
        profile.answers["question:will you require sponsorship?"] = "Yes"
        fill_questions(page, profile)
        assert page.locator("#email").input_value() == profile.email
        assert page.locator("#sponsorship").input_value() == "Yes"
        assert len(describe_questions(form_questions(page))) == 3
        page.set_content(
            '<div role="dialog"><input id="unknown" required aria-label="Unknown salary"></div>'
        )
        with pytest.raises(ValueError, match="Approve"):
            fill_questions(page, profile)
        page.set_content('<div role="dialog"><input id="x" required></div>')
        with pytest.raises(ValueError, match="Unlabelled"):
            fill_questions(page, profile)
        page.set_content(
            '<div role="dialog"><label>Consent<input id="consent" type="checkbox" required></label></div>'
        )
        with pytest.raises(ValueError, match="consent"):
            fill_questions(page, profile)
        page.set_content(
            '<div role="dialog"><label>Will you require sponsorship?<select id="s"><option>True</option></select></label></div>'
        )
        with pytest.raises(ValueError, match="choices"):
            fill_questions(page, profile)
        page.set_content(
            '<div role="dialog"><fieldset><legend>Will you require sponsorship?</legend><label>Yes<input id="yes" type="radio" name="sponsor" required></label><label>No<input id="no" type="radio" name="sponsor"></label></fieldset></div>'
        )
        fill_questions(page, profile)
        assert page.locator("#yes").is_checked()
        assert not page.locator("#no").is_checked()
        profile.answers.clear()
        with pytest.raises(ValueError, match="Approve"):
            fill_questions(page, profile)
        browser.close()


LINKEDIN_HTML = """<main><h1>Backend Engineer</h1><div class="job-details-jobs-unified-top-card__company-name">Example Employer</div><div class="job-details-jobs-unified-top-card__tertiary-description-container">Dublin, Ireland · Full-time</div><div id="job-details">Python FastAPI PostgreSQL</div><a href="https://www.linkedin.com/jobs/view/123/">Job</a><button id="easy">Easy Apply</button><section role="dialog" hidden><label>Email<input id="email" required></label><label>CV<input type="file" aria-label="CV"></label><button id="next">Next</button><button id="submit" hidden>Submit application</button></section><p id="receipt"></p></main><script>document.querySelector('#easy').onclick=()=>document.querySelector('section').hidden=false;document.querySelector('#next').onclick=()=>{document.querySelector('#next').hidden=true;document.querySelector('#submit').hidden=false;};document.querySelector('#submit').onclick=()=>{document.querySelector('section').hidden=true;document.querySelector('#receipt').textContent='Your application was sent';};</script>"""


@pytest.mark.browser
def test_linkedin_search_and_apply_with_fully_intercepted_origin(
    data, profile, job, tmp_path, monkeypatch
):
    job.source = "linkedin"
    job.source_id = "123"
    job.url = "https://www.linkedin.com/jobs/view/123/"
    job.description = "Python FastAPI PostgreSQL"
    generate(profile, job, ["python"], tmp_path, 1)

    def fixture_context(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )
        context.route(
            "**/*",
            lambda route: route.fulfill(status=200, content_type="text/html", body=LINKEDIN_HTML),
        )
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    adapter = LinkedInBrowser(data, profile)
    found = adapter.search("Python", "Ireland", limit=1)
    assert found[0].title == job.title and found[0].source_id == "123"
    assert adapter.submit(job, {}, tmp_path) == "linkedin:123:confirmed"
    job.title = "Changed title"
    with pytest.raises(ValueError, match="title changed"):
        adapter.submit(job, {}, tmp_path)
    job.title = "Backend Engineer"
    job.company = "Changed company"
    with pytest.raises(ValueError, match="Company changed"):
        adapter.submit(job, {}, tmp_path)
