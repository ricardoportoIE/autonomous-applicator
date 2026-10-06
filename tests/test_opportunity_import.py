"""Single-link imports preserve identity, queue ownership and sending budgets."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Error as BrowserError
from test_api import client
from test_browser import LINKEDIN_HTML

from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options
from applicator.models import Settings

URL = "https://www.linkedin.com/jobs/view/123/"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.linkedin.com/jobs/view/123/",
        "https://linkedin.com/jobs/view/123/",
        "https://www.linkedin.com.evil.test/jobs/view/123/",
        "https://127.0.0.1/jobs/view/123/",
        "https://user@www.linkedin.com/jobs/view/123/",
        "https://www.linkedin.com:443/jobs/view/123/",
        "https://www.linkedin.com/jobs/search/",
        "https://www.linkedin.com/in/example/",
        "https://www.linkedin.com/jobs/view/123/../456/",
        "file:///jobs/view/123/",
        "https://www.linkedin.com/jobs/view/not-an-id/",
        "https://example.test/job",
    ],
)
def test_import_rejects_unsupported_urls_before_browser_access(data, monkeypatch, url):
    app, session = client(data)
    read = Mock()
    monkeypatch.setattr(LinkedInBrowser, "read_opportunity", read)
    assert session.post("/api/jobs/from-url", json={"url": url}).status_code == 409
    read.assert_not_called()
    assert app.state.service.operations.status()["run"] is None
    assert app.state.store.applications() == []


def test_import_requires_local_token_scope_and_a_bounded_request(data, monkeypatch):
    app, session = client(data)
    read = Mock()
    monkeypatch.setattr(LinkedInBrowser, "read_opportunity", read)
    assert TestClient(app).post("/api/jobs/from-url", json={"url": URL}).status_code == 401
    assert session.post("/api/jobs/from-url", json={"url": URL}).status_code == 409
    for body in [{}, {"url": ""}, {"url": "x" * 2001}, {"url": URL, "title": "Untrusted"}]:
        assert session.post("/api/jobs/from-url", json=body).status_code == 422
    read.assert_not_called()


def test_import_saves_once_preserves_existing_records_and_reports_stages(data, job, monkeypatch):
    app, session = client(data)
    store = app.state.store
    # Reading is allowed whilst automation is paused, without a candidate record.
    store.set_settings(Settings(linkedin_authorised=True, daily_limit=1))
    job.source, job.source_id, job.url = "linkedin", "123", URL

    def read(self, url):
        assert url == URL + "?tracking=ignored"
        self.report("opening_opportunity", "Opening the opportunity.")
        assert app.state.service.operations.status()["run"]["stage"] == "opening_opportunity"
        self.report("extracting_opportunity", "Reading the job details.")
        return job

    monkeypatch.setattr(LinkedInBrowser, "read_opportunity", read)
    response = session.post("/api/jobs/from-url", json={"url": URL + "?tracking=ignored"})
    assert response.status_code == 200
    app_id = response.json()["id"]
    assert response.json()["created"] is True
    before = store.application(app_id)
    job.title = "Changed live title"
    assert session.post("/api/jobs/from-url", json={"url": URL + "?tracking=ignored"}).json() == {
        "id": app_id,
        "created": False,
    }
    assert store.application(app_id) == before
    status = app.state.service.operations.status()
    assert status["run"]["status"] == "completed"
    assert status["run"]["stage"] == "opportunity_saved"
    assert status["run"]["application_id"] is None
    assert f"#{app_id}" in status["run"]["detail"]
    assert status["results"] == []
    assert store.daily_usage().used == 0
    assert store.settings().automation_enabled is False


@pytest.mark.parametrize(
    "error,code,detail",
    [
        (BrowserError("private locator token"), 502, "No opportunity was saved"),
        (ReviewRequired("LinkedIn opened a different job"), 409, "different job"),
        (
            ValueError("LinkedIn requires login in the dedicated browser session"),
            409,
            "dedicated browser",
        ),
    ],
)
def test_import_failure_is_durable_without_partial_save(data, monkeypatch, error, code, detail):
    app, session = client(data)
    app.state.store.set_settings(Settings(linkedin_authorised=True))

    def read(self, url):
        self.report("extracting_opportunity", "Reading job details.")
        raise error

    monkeypatch.setattr(LinkedInBrowser, "read_opportunity", read)
    response = session.post("/api/jobs/from-url", json={"url": URL})
    assert response.status_code == code and detail in response.json()["detail"]
    assert "private locator" not in response.text
    run = app.state.service.operations.status()["run"]
    assert run["status"] == "failed" and run["stage"] == "extracting_opportunity"
    assert app.state.store.applications() == []
    assert app.state.store.daily_usage().used == 0


def test_import_cannot_interrupt_queue_owner(data, monkeypatch):
    app, session = client(data)
    app.state.store.set_settings(Settings(linkedin_authorised=True))
    read = Mock()
    monkeypatch.setattr(LinkedInBrowser, "read_opportunity", read)
    with app.state.service.operations.run("cycle"):
        response = session.post("/api/jobs/from-url", json={"url": URL})
        assert response.status_code == 409 and "already running" in response.json()["detail"]
    read.assert_not_called()


def test_import_continues_after_confirmed_sending_capacity_is_full(data, profile, job, monkeypatch):
    app, session = client(data)
    store = app.state.store
    revision = store.save_profile(profile)
    store.set_settings(Settings(linkedin_authorised=True, automation_enabled=True, daily_limit=1))
    previous, _ = store.add_job(job)
    app.state.service.prepare(previous)
    attempt = store.reserve(previous, revision)
    store.finish(previous, attempt, "fixture:confirmed")
    assert store.daily_usage().remaining == 0
    store.set_settings(Settings(linkedin_authorised=True, daily_limit=1))
    imported = job.model_copy(update={"source": "linkedin", "source_id": "123", "url": URL})
    monkeypatch.setattr(LinkedInBrowser, "read_opportunity", Mock(return_value=imported))
    response = session.post("/api/jobs/from-url", json={"url": URL})
    assert response.status_code == 200 and response.json()["created"] is True
    assert len(store.applications()) == 2
    assert store.daily_usage().used == 1 and store.daily_usage().held == 0


def test_interrupted_import_journal_preserves_prepared_application(data, profile, job):
    app, _ = client(data)
    store = app.state.store
    store.save_profile(profile)
    app_id, _ = store.add_job(job)
    app.state.service.prepare(app_id)
    before = store.application(app_id)
    assert before["manifest"]["files"]
    results = app.state.service.operations.status()["results"]
    with app.state.service.operations.run("import_opportunity") as operation:
        operation.progress("opportunity_saved", f"Opportunity #{app_id}: already in the queue.")
        assert store.recover() == 0
        assert store.recover() == 0
    assert store.application(app_id) == before
    assert app.state.service.operations.status()["run"]["status"] == "interrupted"
    assert app.state.service.operations.status()["results"] == results
    assert store.daily_usage().used == 0


@pytest.mark.browser
@pytest.mark.parametrize("landing", ["job", "different", "authwall"])
def test_real_browser_import_reads_only_canonical_verified_opportunity(data, monkeypatch, landing):
    visits, clicks, options = [], [], []

    def context(self, playwright, **kwargs):
        options.append(kwargs)
        browser = playwright.chromium.launch_persistent_context(
            str(data / "import-fixture"), headless=True, **browser_options()
        )
        browser.expose_binding("recordClick", lambda source: clicks.append(True))

        def route(route):
            visits.append(route.request.url)
            if len(visits) == 1 and landing != "job":
                route.fulfill(
                    status=302,
                    headers={
                        "Location": URL.replace("123", "456")
                        if landing == "different"
                        else "https://www.linkedin.com/authwall"
                    },
                )
            else:
                route.fulfill(
                    content_type="text/html",
                    body=LINKEDIN_HTML
                    + "<script>document.addEventListener('click',()=>window.recordClick())</script>",
                )

        browser.route("**/*", route)
        return browser

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    adapter = LinkedInBrowser(data)
    stages = []
    adapter.progress = lambda stage, detail: stages.append(stage)
    if landing == "job":
        job = adapter.read_opportunity(URL + "?tracking=private#fragment")
        assert job.title == "Backend Engineer" and job.company == "Example Employer"
        assert job.location.startswith("Dublin, Ireland")
        assert job.description == "Python FastAPI PostgreSQL"
        assert job.url == URL and job.source_id == "123" and job.source == "linkedin"
        assert job.questions == [] and job.sponsorship == "unknown"
    else:
        with pytest.raises(
            ValueError, match="different job" if landing == "different" else "browser-login"
        ):
            adapter.read_opportunity(URL)
    assert stages == ["opening_opportunity", "extracting_opportunity"]
    assert visits[0] == URL and clicks == [] and options == [{"headless": False}]


def test_browser_import_validates_before_launch(data, monkeypatch):
    context = Mock()
    monkeypatch.setattr(LinkedInBrowser, "context", context)
    with pytest.raises(ValueError, match="exact LinkedIn"):
        LinkedInBrowser(data).read_opportunity("https://example.test/jobs/123")
    context.assert_not_called()
