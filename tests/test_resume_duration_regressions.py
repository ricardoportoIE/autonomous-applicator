"""Fictional reproductions of duplicate CV labels and narrative duration approvals."""

from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright
from test_application_dialog import resume_html

from applicator.api import create_app
from applicator.browser import application_dialog, browser_options, fill_questions, upload_resume
from applicator.models import Question, Settings, State
from applicator.policy import answer_compatible, answer_questions, evaluate
from applicator.question_adviser import question_key
from applicator.routine_answers import routine_answer
from applicator.store import Store

YEARS = "How many years of work experience do you have with Python (Programming Language)?"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as instance:
        yield instance


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    ["reference", "existing_copy", "repeated_card_text", "deep_filename", "hidden_reference"],
)
def test_resume_selection_uses_the_fresh_selected_card_instead_of_filename_count(
    browser, tmp_path, profile, case
):
    document = tmp_path / "Approved_CV.pdf"
    document.write_bytes(b"%PDF-1.4 fictional current CV")
    html = resume_html("custom")
    if case == "existing_copy":
        html = html.replace("Previous.pdf", document.name).replace(
            'name="cv">', 'name="cv" checked>'
        )
    elif case == "repeated_card_text":
        html = html.replace(
            "card.append(label);",
            "card.append(label); const repeated=document.createElement('span'); repeated.textContent=e.target.files[0].name; card.append(repeated);",
        )
    elif case == "deep_filename":
        html = html.replace(
            "label.append(input,document.createTextNode(e.target.files[0].name));",
            "label.append(input); const name=document.createElement('span'); name.textContent=e.target.files[0].name; let root=name; for(let i=0;i<10;i++){const parent=document.createElement('div');parent.append(root);root=parent;}label.append(root);",
        )
    else:
        hidden = 'style="display:none"' if case == "hidden_reference" else ""
        html = html.replace(
            "<h3>Resume*</h3>",
            f"<h3>Resume*</h3><p {hidden}><button>PDF<span>{document.name}</span></button></p>",
        )
    page = browser.new_page()
    try:
        page.set_content(html)
        assert upload_resume(page, application_dialog(page), document) == {"old", "uploaded"}
        assert page.locator("#uploaded").is_checked()
        assert page.locator("#picker").evaluate("el=>el.files[0].name") == document.name
        fill_questions(page, profile, resume_field_ids={"old", "uploaded"})
        assert not page.locator("#old").is_checked()
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("case", ["two_selected", "two_native", "unchanged_selection"])
def test_ambiguous_or_unchanged_resume_selection_stops_before_advancing(browser, tmp_path, case):
    document = tmp_path / "Approved_CV.pdf"
    document.write_bytes(b"%PDF-1.4 fictional current CV")
    html = resume_html("custom")
    if case == "two_selected":
        html = html.replace(
            "document.querySelector('#new').append(card);",
            "document.querySelector('#new').append(card); const clone=card.cloneNode(true); clone.querySelector('input').id='duplicate'; clone.querySelector('input').name='different'; clone.querySelector('input').checked=true; document.querySelector('#new').append(clone);",
        )
    elif case == "two_native":
        html = html.replace(
            "card.append(label);",
            "card.append(label); const other=input.cloneNode(); other.id='duplicate';other.name='different';other.checked=true;card.append(other);",
        )
    else:
        html = (
            html.replace("Previous.pdf", document.name)
            .replace('aria-checked="false"', 'aria-checked="true"')
            .replace('name="cv">', 'name="cv" checked>')
        )
        html = html.replace("document.querySelector('#new').append(card);", "")
    page = browser.new_page()
    try:
        page.set_content(html)
        with pytest.raises(ValueError, match="ambiguous|previous selection"):
            upload_resume(page, application_dialog(page), document)
        assert page.get_by_role("button", name="Next", exact=True).is_visible()
        assert not page.get_by_role("button", name="Submit application", exact=True).count()
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize(
    "change", ["none", "hash", "node", "unchecked", "two_selected", "two_native", "empty_cache"]
)
def test_resume_reuse_is_scoped_to_verified_bytes_and_the_same_selected_dom_control(
    browser, tmp_path, change
):
    document = tmp_path / "Approved_CV.pdf"
    document.write_bytes(b"%PDF-1.4 fictional current CV")
    html = resume_html("custom").replace(
        "document.querySelector('#new').append(card);",
        "document.querySelector('#new').replaceChildren(card);",
    )
    page = browser.new_page()
    choosers, verified = [], {}
    page.on("filechooser", lambda chooser: choosers.append(chooser))
    try:
        page.set_content(html)
        dialog = application_dialog(page)
        assert upload_resume(page, dialog, document, verified=verified) == {"old", "uploaded"}
        if change == "hash":
            document.write_bytes(b"%PDF-1.4 changed fictional CV")
        elif change == "node":
            page.locator("#uploaded").evaluate("el=>el.replaceWith(el.cloneNode(true))")
        elif change == "unchecked":
            page.locator("#uploaded").evaluate("el=>el.checked=false")
        elif change == "two_selected":
            page.locator("#new").evaluate("el=>el.append(el.firstElementChild.cloneNode(true))")
        elif change == "two_native":
            page.locator("#uploaded").evaluate("el=>el.parentElement.append(el.cloneNode(true))")
        elif change == "empty_cache":
            verified.clear()
        page.locator("#picker").evaluate("el=>el.value=''")
        assert upload_resume(page, dialog, document, verified=verified) == {"old", "uploaded"}
        assert len(choosers) == (1 if change == "none" else 2)
        assert page.locator("#uploaded").is_checked()
        assert page.locator("#picker").evaluate("el=>el.files.length") == (
            0 if change == "none" else 1
        )
    finally:
        page.close()


@pytest.mark.parametrize("value", ["3", "0", "2.5", " 3 ", "03"])
def test_duration_answers_accept_approved_non_negative_numbers(profile, job, value):
    question = Question(id="years", label=YEARS)
    profile.answers[question_key(question)] = value
    job.questions = [question]
    assert answer_compatible(question, value)
    assert answer_questions(job, profile) == ({"years": value}, [])
    assert routine_answer(profile, job, question).answer == value.strip()


@pytest.mark.parametrize(
    "value",
    ["From 2023, I used Python occasionally.", "3 years", "-1", "NaN", "2023-2026", "", "\u0663"],
)
def test_duration_narratives_cannot_pass_readiness_or_trigger_date_inference(profile, job, value):
    question = Question(id="years", label=YEARS)
    profile.answers[question_key(question)] = value
    job.questions = [question]
    selector = Mock()
    assert not answer_compatible(question, value)
    assert answer_questions(job, profile) == ({}, ["years"])
    assert evaluate(job, profile, Settings()).state == State.REVIEW
    assert routine_answer(profile, job, question, selector) is None
    selector.assert_not_called()


def test_offered_duration_ranges_remain_exact_choices():
    question = Question(id="years", label=YEARS, choices=["Less than 1 year", "3-5 years"])
    assert answer_compatible(question, "3-5 years")
    assert not answer_compatible(question, "3")


def test_invalid_duration_approval_is_rejected_without_mutating_profile_or_queue(
    data, profile, job
):
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    job.questions = [Question(id="years", label=YEARS)]
    app_id, _ = store.add_job(job)
    before = store.application(app_id)
    with pytest.raises(ValueError, match="years of experience require a number"):
        store.approve_answer(app_id, "years", "Since 2023", 1, job)
    assert store.application(app_id) == before
    assert store.profile() == (profile, 1)


def test_scoped_numeric_approval_repairs_the_blocked_job_and_reuses_its_documents(
    data, profile, job
):
    question = Question(id="years", label=YEARS)
    profile.answers[question_key(question)] = "From 2023, I used Python occasionally."
    job.questions = [question]
    app = create_app(data, "fictional-duration-regression-token-0123456789")
    store, service = app.state.store, app.state.service
    store.save_profile(profile)
    jobs = [
        job.model_copy(update={"source_id": str(i), "url": f"http://127.0.0.1:9999/{i}"})
        for i in (1, 2)
    ]
    ids = [store.add_job(item)[0] for item in jobs]
    for app_id in ids:
        service.prepare(app_id)
    before = [store.application(i) for i in ids]
    assert all(row["state"] == State.REVIEW for row in before)
    store.approve_answer(ids[0], "years", "3", 1, jobs[0])
    service.refresh_readiness(ids[0])
    assert store.application(ids[0])["state"] == State.READY
    assert store.application(ids[0])["manifest"] == before[0]["manifest"]
    assert store.application(ids[1]) == before[1]
    assert store.profile() == (profile, 1)
    assert Store(store.path).application(ids[0])["approved_answers"][question_key(question)] == "3"
    assert store.daily_usage().attempts == 0
