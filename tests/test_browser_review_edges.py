"""Unsupported provider controls and upload failures must stop before sending."""

import pytest
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import sync_playwright
from test_browser import LINKEDIN_HTML

from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options, fill_questions
from applicator.documents import generate
from applicator.models import Settings, State
from applicator.service import Service
from applicator.store import Store


@pytest.mark.browser
@pytest.mark.parametrize(
    ("html", "answers", "message"),
    [
        (
            '<label>Yes<input id="yes" type="radio" name="answer"></label>',
            {},
            "Unlabelled radio group",
        ),
        (
            '<fieldset><legend>Work authorisation?</legend><label>Yes<input id="yes" type="radio" name="answer"></label><label>No<input id="no" type="radio" name="answer"></label></fieldset>',
            {"question:work authorisation?": "Maybe"},
            "available choices",
        ),
        ('<label>Salary<input id="salary" value="50000"></label>', {}, "Approve an exact answer"),
        (
            '<label>Salary<input id="salary" required></label>',
            {"question:salary": " "},
            "Approve an exact answer",
        ),
    ],
)
def test_unapproved_form_controls_require_review(profile, html, answers, message):
    profile.answers = answers
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        try:
            page = browser.new_page()
            page.set_content('<div role="dialog">' + html + "</div>")
            with pytest.raises(ValueError, match=message):
                fill_questions(page, profile)
        finally:
            browser.close()


@pytest.mark.browser
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("description", "description changed"),
        ("missing_cv", "Expected the verified document"),
        ("ambiguous_upload", "Ambiguous upload"),
        ("missing_cover", "Expected the verified document"),
        ("unsupported_step", "Unsupported Easy Apply step"),
    ],
)
def test_provider_failures_do_not_attempt_submission(
    data, profile, job, tmp_path, monkeypatch, change, message
):
    job.source = "linkedin"
    job.source_id = "123"
    job.url = "https://www.linkedin.com/jobs/view/123/"
    job.description = "Python FastAPI PostgreSQL"
    generate(profile, job, ["python"], tmp_path, 1)
    html = LINKEDIN_HTML
    if change == "description":
        job.description = "Changed responsibilities"
    elif change == "missing_cv":
        for path in tmp_path.glob("*_CV.pdf"):
            path.unlink()
    elif change == "ambiguous_upload":
        html = html.replace('aria-label="CV"', 'aria-label="Unknown file"').replace(
            '<button id="next">',
            '<input type="file" aria-label="Unknown second file"><button id="next">',
        )
    elif change == "missing_cover":
        html = html.replace('aria-label="CV"', 'aria-label="Cover letter"')
    elif change == "unsupported_step":
        html = html.replace('id="next">Next', 'id="next">Continue')
    submissions = []

    def context_fixture(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "review-browser"), headless=True, **browser_options()
        )
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        # Any submit click is observable even if its confirmation could be missed.
        context.expose_binding("recordSubmission", lambda source: submissions.append(True))
        context.add_init_script(
            "document.addEventListener('click', e => {if(e.target.id === 'submit') window.recordSubmission();}, true)"
        )
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", context_fixture)
    with pytest.raises(ReviewRequired, match=message):
        LinkedInBrowser(data, profile).submit(job, {}, tmp_path)
    assert not submissions


@pytest.mark.browser
def test_missing_confirmation_after_submit_is_uncertain_and_cannot_retry(
    data, profile, job, monkeypatch
):
    job.source = "linkedin"
    job.source_id = "123"
    job.url = "https://www.linkedin.com/jobs/view/123/"
    job.description = "Python FastAPI PostgreSQL"
    html = LINKEDIN_HTML.replace("Your application was sent", "Confirmation unavailable")
    submissions = []

    def context_fixture(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "receipt-browser"), headless=True, **browser_options()
        )
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        context.expose_binding("recordSubmission", lambda source: submissions.append(True))
        context.add_init_script(
            "document.addEventListener('click', e => {if(e.target.id === 'submit') window.recordSubmission();}, true)"
        )
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", context_fixture)
    store = Store(data / "test.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True))
    app_id, _ = store.add_job(job)
    service = Service(store, data, {"linkedin": LinkedInBrowser(data, profile)})
    service.prepare(app_id)
    with pytest.raises(BrowserTimeout):
        service.submit(app_id)
    assert store.application(app_id)["state"] == State.UNCERTAIN
    assert submissions == [True]
    with pytest.raises(ValueError):
        service.submit(app_id)
    assert submissions == [True]
