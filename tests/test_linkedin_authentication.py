"""Delayed provider authentication redirects retain truthful submission outcomes."""

from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import Locator
from test_api import client
from test_browser import LINKEDIN_HTML

from applicator.browser import LinkedInBrowser, browser_options, linkedin_page
from applicator.models import Settings, State


@pytest.mark.parametrize("path", ["login", "checkpoint/challenge", "authwall"])
def test_delayed_authentication_error_does_not_expose_provider_diagnostics(path):
    context = Mock()
    context.new_page.return_value.url = f"https://www.linkedin.com/{path}?private-token=secret"
    with pytest.raises(ValueError, match="dedicated browser session") as caught:
        with linkedin_page(context):
            raise BrowserError("private-token=secret; provider locator call log")
    detail = str(caught.value)
    assert "browser-login" in detail and "press Enter" in detail
    assert "reconcile uncertain submissions" in detail
    assert "secret" not in detail and "call log" not in detail


def test_non_authentication_browser_error_is_preserved():
    context = Mock()
    context.new_page.return_value.url = "https://www.linkedin.com/jobs/view/123/"
    failure = BrowserError("Unsupported layout")
    with pytest.raises(BrowserError) as caught:
        with linkedin_page(context):
            raise failure
    assert caught.value is failure


def test_browser_error_after_leaving_approved_origin_is_rejected():
    context = Mock()
    context.new_page.return_value.url = "https://example.test/authwall"
    with pytest.raises(ValueError, match="approved LinkedIn origin"):
        with linkedin_page(context):
            raise BrowserError("Provider failure")


@pytest.fixture
def delayed_redirect(data, monkeypatch):
    """Enter authwall at the actual locator wait, after the initial URL check."""
    visits, actions, waits = [], [], []
    trigger = {"wait": 1, "receipt": False}
    authwall = "https://www.linkedin.com/authwall?private-token=secret"

    def fixture_context(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "test-browser"), headless=True, **browser_options()
        )
        context.expose_binding("recordAction", lambda source, name: actions.append(name))

        def route_request(route):
            path = urlsplit(route.request.url).path
            visits.append(path)
            if path == "/authwall":
                html = "<main><h1>Sign in to LinkedIn</h1></main>"
            elif path == "/jobs/search/":
                html = '<main><a href="https://www.linkedin.com/jobs/view/123/">Job</a></main>'
            elif path == "/search/results/people/":
                html = '<main><a href="https://www.linkedin.com/in/example/">Member</a></main>'
            elif path == "/in/example/":
                html = "<main><h1>Example Recruiter</h1></main>"
            else:
                html = LINKEDIN_HTML.replace(
                    "<script>",
                    "<script>document.querySelector('#easy').addEventListener('click',"
                    "()=>window.recordAction('easy'));"
                    "document.querySelector('#submit').addEventListener('click',"
                    "()=>window.recordAction('submit'));",
                )
            route.fulfill(content_type="text/html", body=html)

        context.route("**/*", route_request)
        return context

    original_wait = Locator.wait_for

    def redirect_while_waiting(locator, **kwargs):
        waits.append(str(locator))
        if (trigger["receipt"] and "Your application was sent" in str(locator)) or (
            not trigger["receipt"] and len(waits) == trigger["wait"]
        ):
            # The production check has already seen the canonical job/search URL.
            # Navigate deterministically here; retain a real Playwright wait/error.
            locator.page.goto(authwall, wait_until="domcontentloaded")
            return original_wait(locator, timeout=250)
        return original_wait(locator, **kwargs)

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    monkeypatch.setattr(Locator, "wait_for", redirect_while_waiting)
    return trigger, visits, actions, waits


@pytest.mark.browser
@pytest.mark.parametrize("kind,wait", [("jobs", 1), ("jobs", 2), ("contacts", 1), ("contacts", 2)])
def test_discovery_detects_delayed_authentication_without_partial_imports(
    data, profile, delayed_redirect, kind, wait
):
    trigger, visits, actions, waits = delayed_redirect
    trigger["wait"] = wait
    app, session = client(data)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(Settings(linkedin_authorised=True))
    response = session.post(
        "/api/discover/linkedin" if kind == "jobs" else "/api/discover/contacts"
    )
    assert response.status_code == 409
    assert "dedicated browser session" in response.json()["detail"]
    assert "secret" not in response.text and "Timeout" not in response.text
    assert len(waits) == wait and visits[-1] == "/authwall"
    assert actions == []
    assert app.state.store.applications() == [] and app.state.network.list() == []
    assert app.state.store.daily_usage().attempts == 0


@pytest.mark.browser
@pytest.mark.parametrize("phase", ["job", "form", "confirmation"])
def test_submission_authentication_stop_preserves_capacity_stage_and_archived_evidence(
    data, profile, job, delayed_redirect, phase
):
    trigger, visits, actions, _ = delayed_redirect
    trigger["wait"] = 3 if phase == "form" else 1
    trigger["receipt"] = phase == "confirmation"
    job.source, job.source_id = "linkedin", "123"
    job.url, job.description = (
        "https://www.linkedin.com/jobs/view/123/",
        "Python FastAPI PostgreSQL",
    )
    app, session = client(data)
    store, service = app.state.store, app.state.service
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True, daily_limit=1))
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    before_manifest = store.application(app_id)["manifest"]
    response = session.post(f"/api/applications/{app_id}/submit")
    assert response.status_code == 409
    assert "dedicated browser session" in response.json()["detail"]
    assert "secret" not in response.text and "Timeout" not in response.text
    expected_state = State.UNCERTAIN if phase == "confirmation" else State.REVIEW
    assert store.application(app_id)["state"] == expected_state
    assert visits[-1] == "/authwall"
    assert actions == (
        [] if phase == "job" else ["easy"] if phase == "form" else ["easy", "submit"]
    )
    usage = store.daily_usage()
    assert (usage.used, usage.held, usage.remaining, usage.attempts) == (
        0,
        int(phase == "confirmation"),
        int(phase != "confirmation"),
        1,
    )
    assert store.application(app_id)["manifest"] == before_manifest
    run = service.operations.status()["run"]
    expected_stage = {
        "job": "verifying_opportunity",
        "form": "opening_application",
        "confirmation": "awaiting_confirmation",
    }[phase]
    assert run["status"] == "failed" and run["stage"] == expected_stage
    record = service.records.read(app_id)["attempts"][0]
    assert record["status"] == ("held" if phase == "confirmation" else "released")
    assert record["confirmation"] == {} and record["receipt"] is None
    assert service.records.artifact(app_id, record["id"], "cv_pdf").is_file()
    before_visits = visits.copy()
    assert service.tick() == {} and visits == before_visits  # No automatic replay.
