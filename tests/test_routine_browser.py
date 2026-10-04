"""Live questions and the final sending gate use a fully intercepted provider."""

import pytest
from playwright.sync_api import sync_playwright
from test_application_dialog import SCREENING
from test_browser import LINKEDIN_HTML

from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options, fill_questions
from applicator.documents import generate
from applicator.question_adviser import question_key
from applicator.routine_answers import routine_answer


@pytest.mark.browser
@pytest.mark.parametrize("widget", ["radio", "select"])
@pytest.mark.parametrize("resolution", ["known", "unknown", "disabled"])
def test_incompatible_legacy_answer_checks_live_choices_before_any_selection(
    profile, job, widget, resolution
):
    label = "Will you now or in the future require sponsorship for employment visa status?"
    profile.answers["question:" + label.casefold()] = "Full-time work requires sponsorship."
    profile.sponsorship_required = True
    if widget == "radio":
        html = SCREENING.replace("Are you legally authorised to work here?", label)
        control = "#yes"
    else:
        html = (
            f'<dialog open><label>{label}<select id="sponsor" required>'
            "<option>No</option><option>Yes</option></select></label></dialog>"
        )
        control = "#sponsor"
    calls = []

    def resolve(question):
        calls.append(question)
        answer = routine_answer(profile, job, question) if resolution == "known" else None
        return answer.answer if answer else None

    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(html)
        before = (
            page.locator(control).is_checked()
            if widget == "radio"
            else page.locator(control).input_value()
        )
        if resolution == "known":
            fill_questions(page, profile, resolver=resolve)
            assert (
                page.locator(control).is_checked()
                if widget == "radio"
                else page.locator(control).input_value() == "Yes"
            )
        else:
            message = "available choices" if resolution == "disabled" else "Approve an exact answer"
            with pytest.raises(ValueError, match=message):
                fill_questions(
                    page, profile, resolver=None if resolution == "disabled" else resolve
                )
            assert (
                page.locator(control).is_checked() == before
                if widget == "radio"
                else page.locator(control).input_value() == before
            )
        assert len(calls) == (0 if resolution == "disabled" else 1)
        if calls:
            assert calls[0].choices == (["Yes", "No"] if widget == "radio" else ["No", "Yes"])
            assert calls[0].required
            assert question_key(calls[0]) == "question:" + label.casefold()


@pytest.mark.parametrize("required", [False, True])
def test_employment_visa_status_uses_the_explicit_candidate_sponsorship_fact(
    profile, job, required
):
    from applicator.models import Question

    profile.sponsorship_required = required
    question = Question(
        id="sponsor",
        choices=["Yes", "No"],
        label="Will you now or in the future require sponsorship for employment visa status?",
    )
    answer = routine_answer(profile, job, question)
    assert answer is not None and answer.source == "candidate_facts"
    assert answer.answer == ("Yes" if required else "No")
    assert (
        routine_answer(
            profile,
            job,
            question.model_copy(
                update={"label": question.label + " and have unrestricted work authorisation?"}
            ),
        )
        is None
    )


@pytest.mark.browser
@pytest.mark.parametrize("widget", ["radio", "select"])
def test_an_exact_approved_choice_keeps_precedence_over_automatic_resolution(profile, widget):
    label = "Will you now or in the future require sponsorship for employment visa status?"
    profile.answers["question:" + label.casefold()] = "No"
    profile.sponsorship_required = True

    def forbidden(question):
        raise AssertionError("An exact approved choice must not trigger automatic resolution")

    html = (
        SCREENING.replace("Are you legally authorised to work here?", label)
        if widget == "radio"
        else f'<dialog open><label>{label}<select id="sponsor" required>'
        "<option>Yes</option><option>No</option></select></label></dialog>"
    )
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(html)
        fill_questions(page, profile, resolver=forbidden)
        assert (
            page.locator("#no").is_checked() and not page.locator("#yes").is_checked()
            if widget == "radio"
            else page.locator("#sponsor").input_value() == "No"
        )


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
