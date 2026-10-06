"""Bounded read waits, exact failure stages and private-error isolation."""

import json
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as BrowserTimeout
from test_job_discovery import modern_job

from applicator.api import create_app
from applicator.browser import LinkedInBrowser, browser_options
from applicator.models import Settings


@pytest.mark.browser
@pytest.mark.parametrize(
    ("failure", "expected_stage"),
    [
        ("search_navigation", "opening_job_search"),
        ("search_results", "reading_job_results"),
        ("results_list", "reading_job_results"),
        ("job_navigation", "opening_discovered_job"),
        ("job_header", "reading_discovered_job"),
        ("job_description", "reading_discovered_job"),
        (None, "reading_discovered_job"),
    ],
)
def test_search_records_exact_read_boundary_without_raw_provider_errors(
    data, monkeypatch, failure, expected_stage
):
    visits, stages, waits = [], [], []
    results = '<main><div class="jobs-search-results-list"><a href="https://www.linkedin.com/jobs/view/123/?tracking=private">Vacancy</a></div></main>'

    def context_fixture(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "test-browser"), headless=True, **browser_options()
        )

        def route_request(route):
            path = urlsplit(route.request.url).path
            visits.append(path)
            route.fulfill(
                content_type="text/html",
                body=results if path == "/jobs/search/" else modern_job(),
            )

        context.route("**/*", route_request)
        return context

    goto, wait = Page.goto, Locator.wait_for

    def checked_goto(self, url, **kwargs):
        assert kwargs["timeout"] == 60000
        path = urlsplit(url).path
        if failure == ("search_navigation" if path == "/jobs/search/" else "job_navigation"):
            # A failed navigation can still leave the browser at a valid provider origin.
            goto(self, url, **kwargs)
            raise BrowserTimeout("private-provider-token and raw call log")
        return goto(self, url, **kwargs)

    def checked_wait(self, **kwargs):
        assert kwargs["timeout"] == 30000
        waits.append(kwargs["timeout"])
        boundary = ["search_results", "results_list", "job_header", "job_description"][
            len(waits) - 1
        ]
        if failure == boundary:
            raise BrowserTimeout("private-provider-token and raw call log")
        return wait(self, **kwargs)

    monkeypatch.setattr(LinkedInBrowser, "context", context_fixture)
    monkeypatch.setattr(Page, "goto", checked_goto)
    monkeypatch.setattr(Locator, "wait_for", checked_wait)
    adapter = LinkedInBrowser(data)
    adapter.progress = lambda stage, detail: stages.append((stage, detail))
    if failure:
        with pytest.raises(BrowserTimeout):
            adapter.search("Python", "Ireland")
        assert "Check the dedicated browser session" in stages[-1][1]
        assert "Discovery has not sent any applications" in stages[-1][1]
    else:
        assert [job.source_id for job in adapter.search("Python", "Ireland")] == ["123"]
        assert len(waits) == 4
    assert stages[-1][0] == expected_stage
    assert "private" not in json.dumps(stages)
    assert len(visits) <= 2  # No retries or action endpoints.
    if expected_stage.endswith("discovered_job"):
        assert "Opportunity 1/1: https://www.linkedin.com/jobs/view/123/" in stages[-1][1]


@pytest.mark.parametrize("failed", [False, True])
def test_worker_persists_discovery_progress_without_application_or_capacity_changes(
    data, profile, monkeypatch, failed
):
    token = "discovery-test-token-01234567890123456789"
    app = create_app(data, token)
    store = app.state.store
    store.save_profile(profile)
    store.set_settings(
        Settings(automation_enabled=True, linkedin_authorised=True, discovery_enabled=True)
    )

    def search(self, keywords, location, *, excluded_ids):
        assert excluded_ids == set()
        self.report("reading_job_results", "Reading the LinkedIn search results.")
        if failed:
            self.report("reading_job_results", "The provider did not complete the read step.")
            raise BrowserTimeout("private-provider-token")
        return []

    monkeypatch.setattr(LinkedInBrowser, "search", search)
    session = TestClient(app, headers={"Authorization": "Bearer " + token})
    response = session.post("/api/worker/tick")
    assert response.status_code == (502 if failed else 200)
    record = session.get("/api/worker/status").json()
    assert record["run"]["status"] == ("failed" if failed else "completed")
    assert record["run"]["stage"] == "reading_job_results"
    assert record["run"]["application_id"] is None
    assert record["results"] == []
    if failed:
        assert record["run"]["error_code"] == "TimeoutError"
        assert record["run"]["detail"] == "The provider did not complete the read step."
    assert "private-provider-token" not in json.dumps(record)
    assert "private-provider-token" not in json.dumps(store.events())
    assert store.daily_usage().used == 0
