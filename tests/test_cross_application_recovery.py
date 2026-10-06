"""Prove general recovery works for fresh opportunities and after workspace restart."""

import hashlib
from contextlib import nullcontext
from html import escape
from unittest.mock import Mock

import pytest
from playwright.sync_api import Locator, sync_playwright
from playwright.sync_api import TimeoutError as BrowserTimeout
from test_application_dialog import resume_html
from test_form_recovery import recovery_service
from test_large_choice_lists import dialling_choices
from test_provider_form_regressions import city_html
from test_question_collection import provider_html

from applicator.browser import (
    LinkedInBrowser,
    QuestionnaireReview,
    ReviewRequired,
    advance_application,
    application_dialog,
    browser_options,
    fill_questions,
    upload_resume,
)
from applicator.models import Question, Settings
from applicator.question_adviser import question_key
from applicator.service import Service
from applicator.store import Store

YEARS = "How many years of work experience do you have with Python (Programming Language)?"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as instance:
        yield instance


def opportunities(job):
    return [
        job.model_copy(
            update={
                "source_id": f"future-contract-{index}",
                "title": title,
                "url": f"http://127.0.0.1:9999/future-contract-{index}",
            }
        )
        for index, title in enumerate(["Backend Engineer", "Python Developer"], start=1)
    ]


@pytest.mark.browser
@pytest.mark.parametrize("city_case", ["normal", "rerender"])
@pytest.mark.parametrize("choice_count", [249, 500])
def test_new_opportunity_uses_contact_city_and_grounded_duration_contracts_after_restart(
    browser, data, profile, job, city_case, choice_count
):
    profile.phone = "+3535550100"
    profile.answers[question_key(Question(id="years", label=YEARS))] = "I used Python since 2023."
    profile.evidence[0].category = "experience"
    profile.evidence[0].text = "3 years Python."
    profile.evidence[0].source = "Candidate-reviewed fictional employment record"
    store = Store(data / "applicator.sqlite3")
    revision = store.save_profile(profile)
    choices = dialling_choices()
    choices.extend(f"Other region {i} (+{11000 + i})" for i in range(choice_count - len(choices)))
    options = "".join(
        f'<option value="{i}">{escape(label)}</option>' for i, label in enumerate(choices)
    )
    for vacancy in opportunities(job):
        restarted = Store(store.path)
        app_id = restarted.add_job(vacancy)[0]
        service = Service(restarted, data)
        page = browser.new_page()
        try:
            page.set_content(city_html(city_case))
            page.locator("dialog").evaluate(
                "(dialog, html) => dialog.insertAdjacentHTML('beforeend', html)",
                '<label>Phone country code<select id="country" required>'
                + options
                + "</select></label>"
                '<label>Mobile phone number<input id="phone" type="tel" required></label>'
                f'<label>{YEARS}<input id="years" type="text" required></label>',
            )
            page.evaluate(
                """() => {
                  const list=document.querySelector('[role=listbox]');
                  list.removeAttribute('data-testid');
                  document.querySelector('dialog').append(list);
                }"""
            )
            fill_questions(
                page,
                profile,
                resolver=lambda q: service.resolve_question(app_id, profile, revision, vacancy, q),
            )
            assert page.locator("#country").input_value() == str(choices.index("Ireland (+353)"))
            assert page.locator("#country option").count() == choice_count
            assert page.locator("#phone").input_value() == "5550100"
            assert page.locator("#years").input_value() == "3"
            assert (
                page.locator('[data-testid="typeahead-input"]').input_value()
                == "Dublin, County Dublin, Ireland"
            )
            assert page.evaluate("window.sent") is None
            record = restarted.application(app_id)["routine_answers"][0]
            assert record["answer"] == "3" and record["source"] == "verified_evidence"
            assert restarted.profile() == (profile, revision)
            assert restarted.daily_usage().attempts == 0
        finally:
            page.close()


@pytest.mark.browser
@pytest.mark.parametrize("method", ["label", "aria"])
def test_new_opportunity_reuses_cv_strategy_but_uploads_its_own_document(
    browser, data, profile, job, method
):
    store = Store(data / "applicator.sqlite3")
    revision = store.save_profile(profile)
    store.set_settings(Settings(ai_document_preparation=False))
    uploaded_names = []
    for vacancy in opportunities(job):
        restarted = Store(store.path)
        app_id = restarted.add_job(vacancy)[0]
        Service(restarted, data).prepare(app_id)
        record = restarted.application(app_id)["manifest"]["files"]["cv_pdf"]
        cv = data / "documents" / str(app_id) / record["name"]
        html = resume_html("custom")
        if method == "aria":
            html = html.replace(
                "card.append(label);",
                "card.setAttribute('aria-label',e.target.files[0].name);card.append(input);"
                "const text=document.createElement('span');text.textContent=e.target.files[0].name;"
                "document.querySelector('#new').append(text);",
            )
        page = browser.new_page()
        try:
            page.set_content(html)
            assert upload_resume(
                page, application_dialog(page), cv, verified={}, memory=restarted.recovery_strategy
            ) == {"old", "uploaded"}
            assert restarted.recovery_strategy("resume-widget") == method
            file = page.locator("#picker").evaluate(
                "async el => ({name:el.files[0].name,bytes:[...new Uint8Array(await el.files[0].arrayBuffer())]})"
            )
            assert file["name"] == cv.name
            assert hashlib.sha256(bytes(file["bytes"])).hexdigest() == record["sha256"]
            uploaded_names.append(file["name"])
            assert restarted.profile() == (profile, revision)
            assert restarted.daily_usage().attempts == 0
        finally:
            page.close()
    assert len(set(uploaded_names)) == 2


@pytest.mark.browser
def test_learned_boolean_method_is_shared_but_each_opportunity_keeps_its_approved_answer(
    browser, data, profile, job
):
    question = Question(id="selection", label="Fictional approved selection", choices=["Yes", "No"])
    job.questions = [question]
    store = Store(data / "applicator.sqlite3")
    revision = store.save_profile(profile)
    for index, vacancy in enumerate(opportunities(job)):
        restarted = Store(store.path)
        app_id = restarted.add_job(vacancy)[0]
        value = "Yes" if index == 0 else "No"
        restarted.approve_answer(app_id, question.id, value, revision, vacancy)
        initial = "false" if index == 0 else "true"
        page = browser.new_page()
        progress = Mock()
        try:
            page.set_content(
                f"""<dialog open><div role="checkbox" aria-label="{question.label}" aria-checked="{initial}"
                onclick="const target=this.getAttribute('aria-checked')!=='true';
                this.setAttribute('aria-checked',String(target));this.querySelector('input').checked=target;">
                {question.label}
                <input id="control-{app_id}" type="checkbox" hidden {"checked" if index else ""}></div>
                <button onclick="window.sent=true">Submit application</button></dialog>"""
            )
            fill_questions(
                page,
                restarted.effective_profile(app_id, profile, vacancy),
                progress=progress,
                memory=restarted.recovery_strategy,
            )
            assert page.locator("input").is_checked() == (value == "Yes")
            assert Store(store.path).recovery_strategy("checkbox-001") == "aria"
            methods = [
                call.args[1]
                for call in progress.call_args_list
                if call.args[0] == "recovering_form"
            ]
            if index:
                assert len(methods) == 1 and "Trying aria interaction (1/3)" in methods[0]
            else:
                assert len(methods) == 3
            assert page.evaluate("window.sent") is None
            assert restarted.profile() == (profile, revision)
        finally:
            page.close()


@pytest.mark.browser
def test_learned_navigation_does_not_replay_a_completed_step_in_a_future_opportunity(
    browser, data, profile, job, monkeypatch
):
    store = Store(data / "applicator.sqlite3")
    actual_click = Locator.click
    for index, vacancy in enumerate(opportunities(job)):
        restarted = Store(store.path)
        restarted.add_job(vacancy)
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=""))
        page.goto(f"https://www.linkedin.com/jobs/view/{201 + index}/")
        page.set_content(
            '<dialog open><button onclick="window.clicks++;this.hidden=true;'
            "document.querySelector('#submit').hidden=false;\">Next</button>"
            '<button id="submit" hidden onclick="window.sent=true">Submit application</button>'
            "</dialog><script>window.clicks=0</script>"
        )
        clicks = []

        def click(locator, **kwargs):
            clicks.append(True)
            actual_click(locator, **kwargs)
            if index == 0:
                raise BrowserTimeout("Fictional timeout after completed navigation")

        monkeypatch.setattr(Locator, "click", click)
        try:
            advance_application(
                page,
                profile,
                resume_field_ids=None,
                resolver=None,
                progress=Mock(),
                memory=restarted.recovery_strategy,
            )
            assert len(clicks) == 1 and page.evaluate("window.clicks") == 1
            assert page.evaluate("window.sent") is None
            assert restarted.recovery_strategy("advance-step") == (
                "timeout-transition" if index == 0 else "settled"
            )
        finally:
            page.close()


@pytest.mark.parametrize(
    "label,value,choices",
    [
        (YEARS, "3", []),
        ("Expected salary?", "70000", []),
        ("Are you legally authorised to work here?", "No", ["Yes", "No"]),
        ("Can you relocate?", "Yes", ["Yes", "No"]),
    ],
)
def test_learning_cannot_promote_an_opportunity_answer_to_an_unapproved_candidate_fact(
    data, profile, job, label, value, choices
):
    question = Question(id="scoped", label=label, choices=choices)
    job.questions = [question]
    store = Store(data / "applicator.sqlite3")
    revision = store.save_profile(profile)
    first, future = opportunities(job)
    first_id = store.add_job(first)[0]
    store.approve_answer(first_id, question.id, value, revision, first)
    restarted = Store(store.path)
    future_id = restarted.add_job(future)[0]
    service = Service(restarted, data)
    assert service.resolve_question(first_id, profile, revision, first, question) == value
    assert service.resolve_question(future_id, profile, revision, future, question) is None
    assert restarted.application(future_id)["approved_answers"] == {}
    assert restarted.application(future_id)["routine_answers"] == []
    assert restarted.profile() == (profile, revision)
    assert restarted.daily_usage().attempts == 0


def test_future_opportunity_keeps_its_own_bounded_budget_with_shared_technical_learning(
    data, profile, job
):
    store, service, adapter, first_id = recovery_service(data, profile, job)
    assert store.form_recovery_available(first_id, claim=True)
    assert store.form_recovery_available(first_id, claim=True)
    assert not store.form_recovery_available(first_id)
    future = opportunities(job)[1]
    future_id = store.add_job(future)[0]
    service.prepare(future_id)
    with pytest.raises(ReviewRequired):
        service.submit(future_id)
    restarted = Store(store.path)
    assert restarted.form_recovery_available(future_id, claim=True)
    assert restarted.form_recovery_available(future_id, claim=True)
    assert not Store(store.path).form_recovery_available(future_id)
    assert not restarted.form_recovery_available(first_id)
    assert adapter.submit.call_count == 2
    assert restarted.daily_usage().used == 0 and restarted.daily_usage().held == 0


@pytest.mark.browser
def test_each_future_opportunity_collects_all_reachable_questions_and_keeps_its_own_html(
    browser, data, profile, job, monkeypatch
):
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(
        Settings(automation_enabled=True, linkedin_authorised=True, ai_document_preparation=False)
    )
    # Reuse the fixture's real browser rather than nesting Playwright event loops.
    monkeypatch.setattr("applicator.browser.sync_playwright", lambda: nullcontext(None))
    sources = set()
    paths = set()
    sends = []
    for index, vacancy in enumerate(opportunities(job)):
        vacancy = vacancy.model_copy(
            update={
                "source": "linkedin",
                "source_id": str(701 + index),
                "url": f"https://www.linkedin.com/jobs/view/{701 + index}/",
                "description": "Python FastAPI PostgreSQL",
            }
        )
        html = (
            provider_html(
                [
                    "<label>Unconfirmed salary<input required></label>",
                    "<label>Unconfirmed availability<textarea required></textarea></label>",
                ]
            )
            .replace("Backend Engineer", vacancy.title)
            .replace("https://www.linkedin.com/jobs/view/123/", vacancy.url)
        )

        def context(self, playwright, **kwargs):
            session = browser.new_context()
            session.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
            session.expose_binding("recordSend", lambda *_: sends.append(True))
            session.add_init_script(
                "document.addEventListener('click',e=>{if(e.target.id==='submit')window.recordSend();},true)"
            )
            return session

        monkeypatch.setattr(LinkedInBrowser, "context", context)
        restarted = Store(store.path)
        app_id = restarted.add_job(vacancy)[0]
        adapter = LinkedInBrowser(data, profile)
        service = Service(restarted, data, {"linkedin": adapter})
        service.prepare(app_id)
        with pytest.raises(QuestionnaireReview):
            service.submit(app_id)
        saved = Store(store.path).application(app_id)
        assert {q["label"] for q in saved["job"]["questions"]} == {
            "Unconfirmed salary",
            "Unconfirmed availability",
        }
        evidence = adapter.form_diagnostics_evidence
        assert {item["step"] for item in evidence} == {1, 2}
        assert all(item["source_id"] == vacancy.source_id for item in evidence)
        for item in evidence:
            path = data / item["path"]
            assert path.exists()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
            assert item["path"] not in paths
            paths.add(item["path"])
        sources.add(vacancy.source_id)
        assert not restarted.form_recovery_available(app_id)
    assert len(sources) == 2 and not sends
    assert Store(store.path).daily_usage().used == 0 and Store(store.path).daily_usage().held == 0
