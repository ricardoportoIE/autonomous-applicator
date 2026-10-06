"""Current accessible CV selectors and post-dispatch timeouts, using fictional data."""

from unittest.mock import Mock

import pytest
from playwright.sync_api import Locator, sync_playwright
from playwright.sync_api import TimeoutError as BrowserTimeout
from test_application_dialog import resume_html
from test_form_recovery import recovery_service

from applicator.browser import (
    advance_application,
    application_dialog,
    browser_options,
    upload_resume,
)
from applicator.store import Store


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as b:
        yield b


@pytest.mark.parametrize(
    ("shape", "strategy"),
    [
        ("resume-widget", "aria"),
        ("resume-widget", "label"),
        ("advance-step", "settled"),
        ("advance-step", "timeout-transition"),
    ],
)
def test_document_and_navigation_hints_survive_restart(data, shape, strategy):
    store = Store(data / "applicator.sqlite3")
    assert store.recovery_strategy(shape) is None
    assert store.recovery_strategy(shape, strategy) == strategy
    assert Store(store.path).recovery_strategy(shape) == strategy
    with pytest.raises(ValueError, match="strategy"):
        store.recovery_strategy(shape, "submit")


def test_proven_unsupported_upload_receives_a_bounded_new_budget(data, profile, job):
    store, _, _, ident = recovery_service(data, profile, job)
    with store.connect() as db:
        db.execute(
            "UPDATE events SET detail=? WHERE kind='provider_review_required'",
            ("The uploaded resume selection is unsupported; review manually",),
        )
        db.execute("INSERT INTO config VALUES (?,?)", (f"form_recovery:v2:{ident}", "2"))
    assert store.form_recovery_available(ident, claim=True)
    assert Store(store.path).form_recovery_available(ident, claim=True)
    assert not Store(store.path).form_recovery_available(ident, claim=True)


@pytest.mark.browser
@pytest.mark.parametrize(
    "case", ["aria", "learned", "legacy", "delayed", "wrong_label", "old_unselected"]
)
def test_resume_accessible_name_outside_the_radio_requires_fresh_upload_proof(
    browser, tmp_path, case
):
    document = tmp_path / "Approved_CV.pdf"
    document.write_bytes(b"%PDF-1.4 fictional CV")
    store = Store(tmp_path / "memory.sqlite3")
    html = resume_html("custom")
    if case != "legacy":
        name = "Different.pdf" if case == "wrong_label" else document.name
        html = html.replace(
            "card.append(label);",
            f"label.textContent='';card.setAttribute('aria-label','{name}');card.append(input);"
            "const sibling=document.createElement('span');sibling.textContent=e.target.files[0].name;document.querySelector('#new').append(sibling);",
        )
    if case == "learned":
        store.recovery_strategy("resume-widget", "aria")
    if case == "delayed":
        html = html.replace(
            "document.querySelector('#new').append(card);",
            "setTimeout(()=>document.querySelector('#new').append(card),500);",
        )
    if case == "old_unselected":
        html = html.replace(
            'aria-checked="false"', 'aria-checked="false" aria-label="Approved_CV.pdf"'
        )
        html = html.replace(
            "document.querySelector('#new').append(card);",
            "const old=document.querySelector('[role=radio]');old.setAttribute('aria-checked','true');old.querySelector('input').checked=true;",
        )
    page = browser.new_page()
    try:
        page.set_content(html)
        if case in {"wrong_label", "old_unselected"}:
            with pytest.raises(ValueError, match="unsupported|previous selection"):
                upload_resume(
                    page, application_dialog(page), document, memory=store.recovery_strategy
                )
            assert store.recovery_strategy("resume-widget") is None
        else:
            verified = {}
            assert upload_resume(
                page,
                application_dialog(page),
                document,
                verified=verified,
                memory=store.recovery_strategy,
            ) == {"old", "uploaded"}
            assert Store(store.path).recovery_strategy("resume-widget") == (
                "label" if case == "legacy" else "aria"
            )
            assert page.locator("#uploaded").is_checked()
            assert upload_resume(
                page,
                application_dialog(page),
                document,
                verified=verified,
                memory=store.recovery_strategy,
            ) == {"old", "uploaded"}
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize(
    "case", ["after_dispatch", "before_dispatch", "delayed", "stalled", "validation", "learned"]
)
def test_navigation_timeout_checks_the_actual_step_before_any_second_click(
    browser, tmp_path, profile, monkeypatch, case
):
    store = Store(tmp_path / "memory.sqlite3")
    if case == "learned":
        store.recovery_strategy("advance-step", "timeout-transition")
    transition = "this.hidden=true;document.getElementById('submit').hidden=false;"
    if case == "delayed":
        transition = "setTimeout(()=>{document.getElementById('next').hidden=true;document.getElementById('submit').hidden=false;},500);"
    handler = "window.clicks++;" + ("" if case in {"stalled", "validation"} else transition)
    page = browser.new_page()
    page.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="text/html",
            body='<main><dialog open><button id="next" onclick="' + handler + '">Next</button>'
            '<button id="submit" hidden onclick="window.sent=true">Submit application</button>'
            + ('<label>Email<input aria-invalid="true"></label>' if case == "validation" else "")
            + "</dialog></main><script>window.clicks=0;</script>",
        ),
    )
    page.goto("https://www.linkedin.com/jobs/view/123/")
    actual = Locator.click
    dispatches = []

    def click(locator, **kwargs):
        dispatches.append(locator)
        if case == "before_dispatch" and len(dispatches) == 1:
            raise BrowserTimeout("Fixture private provider diagnostic")
        actual(locator, **kwargs)
        if case != "learned":
            raise BrowserTimeout("Fixture private provider diagnostic")

    monkeypatch.setattr(Locator, "click", click)
    if case != "delayed":
        monkeypatch.setattr(page, "wait_for_timeout", lambda ms: None)
    progress = Mock()
    try:
        kwargs = dict(
            resume_field_ids=None, resolver=None, progress=progress, memory=store.recovery_strategy
        )
        if case in {"stalled", "validation"}:
            with pytest.raises(ValueError, match="did not advance") as error:
                advance_application(page, profile, **kwargs)
            assert "private provider diagnostic" not in str(error.value)
            assert store.recovery_strategy("advance-step") is None
            assert len(dispatches) == (1 if case == "validation" else 3)
        else:
            advance_application(page, profile, **kwargs)
            assert len(dispatches) == (2 if case == "before_dispatch" else 1)
            assert page.evaluate("window.clicks") == 1
            assert Store(store.path).recovery_strategy("advance-step") == (
                "settled" if case == "learned" else "timeout-transition"
            )
        assert page.evaluate("window.sent") is None
    finally:
        page.close()
