"""Modern company logos and per-page read recovery use real, offline browser fixtures."""

import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as BrowserTimeout
from test_job_discovery import modern_job

from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options, job_details
from applicator.discovery_memory import DiscoveryMemory
from applicator.store import Store


def logo_job():
    return modern_job().replace(
        '<div aria-label="Company, Example Employer."><a href="https://www.linkedin.com/company/example/">Example Employer</a></div>',
        '<div><figure><svg role="img" aria-label="Company logo for, Example Employer."></svg></figure><p>Example Employer</p></div>',
    )


@pytest.mark.browser
@pytest.mark.parametrize(
    "case", ["valid", "nested_logo", "wrong_label", "missing_name", "two_names", "two_titles"]
)
def test_company_logo_requires_matching_unique_primary_identity(case):
    content = logo_job()
    if case == "nested_logo":
        content = modern_job().replace(
            '<a href="https://www.linkedin.com/company/example/">Example Employer</a>',
            '<a href="https://www.linkedin.com/company/example/"><svg role="img" aria-label="Company logo for, Example Employer."></svg>Example Employer</a>',
        )
    elif case == "wrong_label":
        content = content.replace("logo for, Example Employer.", "logo for, Other Company.")
    elif case == "missing_name":
        content = content.replace("<p>Example Employer</p>", "")
    elif case == "two_names":
        content = content.replace(
            "<p>Example Employer</p>", "<p>Example Employer</p><p>Other Company</p>"
        )
    elif case == "two_titles":
        content = content.replace("<div></div>", "<div><p>Ambiguous title</p></div>")
    with (
        sync_playwright() as playwright,
        playwright.chromium.launch(headless=True, **browser_options()) as browser,
    ):
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=content))
        page.goto("https://www.linkedin.com/jobs/view/123/")
        if case in {"valid", "nested_logo"}:
            job = job_details(page, "123")
            assert (job.title, job.company, job.location) == (
                "Backend Engineer",
                "Example Employer",
                "Dublin, Ireland",
            )
            assert "Recommended" not in job.description
        else:
            with pytest.raises(ReviewRequired, match="incomplete or unsupported"):
                job_details(page, "123")


@pytest.mark.browser
@pytest.mark.parametrize("failure", ["timeout", "navigation", "review", "auth", "origin", "pause"])
def test_batch_retains_valid_reads_defers_only_page_errors_and_never_clicks(
    data, monkeypatch, failure
):
    store = Store(data / "db.sqlite3")
    memory = DiscoveryMemory(store)
    visits, actions, stages = [], [], []
    results = (
        '<main><div class="jobs-search-results-list">'
        + "".join(
            f'<a href="https://www.linkedin.com/jobs/view/{key}/">Job</a>'
            for key in ("123", "456", "789")
        )
        + "</div></main>"
    )

    def fixture(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )
        context.expose_binding("recordAction", lambda source: actions.append(True))

        def route(route):
            path = urlsplit(route.request.url).path
            visits.append(path)
            route.fulfill(
                content_type="text/html",
                body=results
                if path == "/jobs/search/"
                else logo_job() + '<button onclick="recordAction()">Easy Apply</button>',
            )

        context.route("**/*", route)
        return context

    original = job_details
    original_goto = Page.goto

    def goto(self, url, **kwargs):
        result = original_goto(self, url, **kwargs)
        if failure == "navigation" and urlsplit(url).path == "/jobs/view/456/":
            raise BrowserTimeout("private-provider-data")
        return result

    def read(page, expected_id, **kwargs):
        if expected_id == "456":
            if failure == "auth":
                page.goto("https://www.linkedin.com/authwall")
            elif failure == "origin":
                page.goto("https://external.test/")
            if failure == "review":
                raise ReviewRequired("private-provider-data")
            raise BrowserTimeout("private-provider-data")
        return original(page, expected_id, **kwargs)

    monkeypatch.setattr(LinkedInBrowser, "context", fixture)
    monkeypatch.setattr(Page, "goto", goto)
    monkeypatch.setattr("applicator.browser.job_details", read)
    adapter = LinkedInBrowser(data)
    adapter.discovery_failure = memory.defer
    adapter.progress = lambda stage, detail: stages.append((stage, detail))
    adapter.discovery_stopping = lambda: failure == "pause" and "/jobs/view/123/" in visits
    if failure in {"auth", "origin"}:
        with pytest.raises(ValueError, match="login or verification|approved LinkedIn origin"):
            adapter.search("Python", "Ireland")
        assert memory.holds() == {} and "/jobs/view/789/" not in visits
    else:
        jobs = adapter.search("Python", "Ireland")
        assert [job.source_id for job in jobs] == (
            ["123"] if failure == "pause" else ["123", "789"]
        )
        if failure == "pause":
            assert visits == ["/jobs/search/", "/jobs/view/123/"]
            assert stages[-1][0] == "discovery_paused" and not memory.holds()
        else:
            assert memory.excluded_ids() == {"456"}
            assert any(stage == "deferring_discovered_job" for stage, _ in stages)
            visits.clear()
            assert [
                job.source_id
                for job in adapter.search("Python", "Ireland", excluded_ids=memory.excluded_ids())
            ] == ["123", "789"]
            assert "/jobs/view/456/" not in visits
    assert not actions and store.applications() == [] and store.discovery_discards() == []
    assert "private-provider-data" not in json.dumps(stages) + json.dumps(store.events())
