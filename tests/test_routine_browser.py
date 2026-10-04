"""Live questions and the final sending gate use a fully intercepted provider."""

import pytest
from playwright.sync_api import sync_playwright
from test_application_dialog import SCREENING
from test_browser import LINKEDIN_HTML

from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options, fill_questions
from applicator.documents import generate
from applicator.routine_answers import routine_answer


@pytest.mark.browser
def test_live_radio_resolution_is_cached_and_consent_is_never_automatic(profile, job):
    html = SCREENING.replace("Are you legally authorised to work here?", "Have you used Python?")
    calls = []

    def resolve(question):
        calls.append(question)
        result = routine_answer(profile, job, question)
        return result.answer if result else None

    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(html)
        fill_questions(page, profile, resolver=resolve)
        assert page.locator("#yes").is_checked() and len(calls) == 1
        assert calls[0].choices == ["Yes", "No"] and calls[0].required
        page.set_content(
            '<dialog open><label>I agree<input type="checkbox" id="consent" required></label></dialog>'
        )
        with pytest.raises(ValueError, match="consent requires manual review"):
            fill_questions(page, profile, resolver=resolve)
        assert not page.locator("#consent").is_checked() and len(calls) == 1


@pytest.mark.browser
@pytest.mark.parametrize("allow", [False, True])
def test_final_gate_runs_before_irreversible_click(
    data, profile, job, tmp_path, monkeypatch, allow
):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    job.description = "Python FastAPI PostgreSQL"
    generate(profile, job, ["python"], tmp_path, 1)
    clicks = []
    trace = []

    def context(self, playwright, **_):
        session = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )
        session.route(
            "**/*", lambda route: route.fulfill(content_type="text/html", body=LINKEDIN_HTML)
        )
        session.expose_binding("recordClick", lambda *_: clicks.append("sent"))
        session.add_init_script(
            "document.addEventListener('click',event=>{if(event.target.id==='submit') window.recordClick();},true)"
        )
        return session

    def gate():
        assert not clicks
        trace.append("checked")
        if not allow:
            raise ValueError("Permission changed before sending")

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    adapter = LinkedInBrowser(data, profile)
    adapter.before_submit = gate
    if allow:
        assert adapter.submit(job, {}, tmp_path) == "linkedin:123:confirmed"
        assert clicks == ["sent"]
    else:
        with pytest.raises(ReviewRequired, match="Permission changed"):
            adapter.submit(job, {}, tmp_path)
        assert clicks == []
    assert trace == ["checked"]
