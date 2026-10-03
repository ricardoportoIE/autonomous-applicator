"""Current and legacy job layouts, bounded discovery and exact identity checks."""

import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright
from test_browser import LINKEDIN_HTML

from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options, job_details
from applicator.documents import generate


def modern_job(*, title="Backend Engineer", company="Example Employer", location="Dublin, Ireland"):
    return f"""<!doctype html><meta charset="utf-8"><main>
      <article><div class="changing-header-classes">
        <div><div aria-label="Company, {company}."><a href="https://www.linkedin.com/company/example/">{company}</a></div></div>
        <div><div><p>{title}<a href="#"><span role="img" aria-label="Verified job"></span></a></p></div></div>
        <div></div><p><span>{location}</span> · <span>1 day ago</span> · <span>12 applicants</span></p>
        <div><p>Promoted by hirer</p></div>
      </div></article>
      <section><div><h2>About the job</h2></div><p>Build Python APIs with FastAPI.</p>
        <ul><li>PostgreSQL and Docker</li><li>Automated testing</li></ul>
        <button data-testid="expandable-text-button">more</button>
        <p>Requirements added by the job poster</p><p>Authorised to work in Ireland</p>
      </section>
      <aside><h2>More jobs</h2><p>Recommended title</p><a href="https://www.linkedin.com/jobs/view/999/">Unrelated job</a>
        <div aria-label="Company, Unrelated Employer."><a href="https://www.linkedin.com/company/unrelated/">Unrelated Employer</a></div>
      </aside></main>"""


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "current",
        "legacy",
        "delayed",
        "missing_title",
        "missing_location",
        "wrong_company_label",
        "two_titles",
        "two_locations",
        "missing_body",
        "oversized_title",
        "oversized_body",
        "wrong_company_origin",
        "wrong_job",
        "login",
        "external_origin",
        "ambiguous_legacy",
    ],
)
def test_job_reader_requires_a_complete_primary_job(case):
    content = modern_job()
    url = "https://www.linkedin.com/jobs/view/123/"
    if case == "legacy":
        content = LINKEDIN_HTML
    elif case == "missing_title":
        content = modern_job(title="")
    elif case == "missing_location":
        content = modern_job(location="")
    elif case == "wrong_company_label":
        content = content.replace(
            'aria-label="Company, Example Employer."', 'aria-label="Company, Different Employer."'
        )
    elif case == "two_titles":
        content = content.replace("<div></div>", "<div><p>Second title</p></div>")
    elif case == "two_locations":
        content = content.replace("<div></div>", "<p><span>Berlin, Germany</span></p>")
    elif case == "missing_body":
        content = (
            content[: content.index("<section>")]
            + "<section><div><h2>About the job</h2></div></section></main>"
        )
    elif case == "oversized_title":
        content = modern_job(title="x" * 201)
    elif case == "oversized_body":
        content = content.replace("Build Python APIs with FastAPI.", "x" * 40001)
    elif case == "wrong_company_origin":
        content = content.replace(
            "https://www.linkedin.com/company/example/", "https://example.test/company/example/"
        )
    elif case == "wrong_job":
        url = "https://www.linkedin.com/jobs/view/456/"
    elif case == "login":
        url = "https://www.linkedin.com/checkpoint/"
    elif case == "external_origin":
        url = "https://example.test/jobs/view/123/"
    elif case == "ambiguous_legacy":
        content = LINKEDIN_HTML.replace("<h1>", "<h1>Another job</h1><h1>")
    with (
        sync_playwright() as playwright,
        playwright.chromium.launch(headless=True, **browser_options()) as browser,
    ):
        page = browser.new_page()
        if case == "delayed":
            content = (
                "<main></main><script>setTimeout(()=>document.body.innerHTML="
                + json.dumps(content)
                + ",200)</script>"
            )
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=content))
        page.goto(url)
        if case in {"current", "legacy", "delayed"}:
            job = job_details(page, "123")
            assert (job.title, job.company, job.location) == (
                "Backend Engineer",
                "Example Employer",
                "Dublin, Ireland",
            )
            assert "PostgreSQL" in job.description
            assert "Recommended" not in job.description and "more" not in job.description
            if case != "legacy":
                assert "Authorised to work in Ireland" in job.description
                assert "\n" in job.description
        else:
            with pytest.raises(ValueError):
                job_details(page, "123")


@pytest.mark.browser
@pytest.mark.parametrize("case", ["bounded", "empty", "invalid_links", "redirect", "login"])
def test_job_search_is_read_only_and_canonical(data, monkeypatch, case):
    results = """<main><div class="jobs-search-results-list">
      <a href="https://www.linkedin.com/jobs/view/123/?tracking=x#details">First</a>
      <a href="https://www.linkedin.com/jobs/view/123/">Duplicate</a>
      <a href="https://www.linkedin.com/jobs/view/not-a-number/">Malformed</a>
      <a href="https://example.test/jobs/view/987/">External</a>
      <a href="https://www.linkedin.com/jobs/view/456/">Second</a>
      <a href="https://www.linkedin.com/jobs/view/789/">Over limit</a>
    </div><aside><a href="https://www.linkedin.com/jobs/view/999/">Recommendation</a></aside>
    <button onclick="window.recordAction()">Easy Apply</button></main>"""
    if case == "empty":
        results = "<main><h2>No matching jobs found.</h2></main>"
    elif case == "invalid_links":
        results = '<main><a href="https://example.test/jobs/view/987/">External</a></main>'
    visits, actions = [], []

    def context_fixture(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "test-browser"), headless=True, **browser_options()
        )
        context.expose_binding("recordAction", lambda source: actions.append(True))

        def route_request(route):
            path = urlsplit(route.request.url).path
            visits.append(path)
            if path == "/jobs/search/":
                if case == "login":
                    route.fulfill(
                        status=302, headers={"Location": "https://www.linkedin.com/login/"}
                    )
                else:
                    route.fulfill(content_type="text/html", body=results)
            elif case == "redirect" and path == "/jobs/view/123/":
                route.fulfill(
                    status=302, headers={"Location": "https://www.linkedin.com/jobs/view/456/"}
                )
            else:
                route.fulfill(content_type="text/html", body=modern_job())

        context.route("**/*", route_request)
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", context_fixture)
    adapter = LinkedInBrowser(data)
    if case in {"invalid_links", "redirect", "login"}:
        with pytest.raises(ValueError):
            adapter.search("Python", "Ireland", limit=2)
    else:
        jobs = adapter.search("Python", "Ireland", limit=2)
        assert [job.source_id for job in jobs] == ([] if case == "empty" else ["123", "456"])
    assert not actions
    assert not any(
        path in visits for path in ["/jobs/view/987/", "/jobs/view/789/", "/jobs/view/999/"]
    )


@pytest.mark.parametrize("limit", [0, 11])
def test_job_search_rejects_unbounded_limits(data, limit):
    with pytest.raises(ValueError, match="between 1 and 10"):
        LinkedInBrowser(data).search("Python", "Ireland", limit=limit)


@pytest.mark.browser
@pytest.mark.parametrize("changed", [None, "title", "company", "location", "description"])
def test_current_job_layout_retains_pre_submission_snapshot_checks(
    data, profile, tmp_path, monkeypatch, changed
):
    content = modern_job()
    actions = []

    def context_fixture(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "test-browser"), headless=True, **browser_options()
        )
        context.expose_binding("recordAction", lambda source: actions.append(True))
        page_html = (
            content
            + """<button onclick="window.recordAction();document.querySelector('[role=dialog]').hidden=false">Easy Apply</button>
        <section role="dialog" hidden><button onclick="document.querySelector('#receipt').textContent='Your application was sent'">Submit application</button></section><p id="receipt"></p>"""
        )
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=page_html))
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", context_fixture)
    adapter = LinkedInBrowser(data, profile)
    with sync_playwright() as playwright, adapter.context(playwright) as context:
        page = context.new_page()
        page.goto("https://www.linkedin.com/jobs/view/123/")
        job = job_details(page, "123")
    generate(profile, job, ["python"], tmp_path, 1)
    if changed:
        setattr(job, changed, "Changed value")
        with pytest.raises(ReviewRequired, match="changed"):
            adapter.submit(job, {}, tmp_path)
        assert not actions
    else:
        assert adapter.submit(job, {}, tmp_path) == "linkedin:123:confirmed"
        assert actions == [True]
