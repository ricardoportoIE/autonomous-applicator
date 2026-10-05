"""Bounded technical learning against fictional controls, with no external sends."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from playwright.sync_api import Locator, sync_playwright
from playwright.sync_api import TimeoutError as BrowserTimeout

from applicator.browser import (
    ReviewRequired,
    advance_application,
    browser_options,
    fill_questions,
    form_questions,
    open_easy_apply,
)
from applicator.models import Settings, State
from applicator.service import Service
from applicator.store import Store, day_key


@pytest.mark.parametrize("shape", ["checkbox-010", "radio-111"])
@pytest.mark.parametrize("method", ["native", "label", "aria"])
def test_verified_strategy_survives_restart_without_answers(data, shape, method):
    store = Store(data / "applicator.sqlite3")
    assert store.recovery_strategy(shape) is None
    assert store.recovery_strategy(shape, method) == method
    restarted = Store(store.path)
    assert restarted.recovery_strategy(shape) == method
    with store.connect() as db:
        assert db.execute(
            "SELECT key,value FROM config WHERE key LIKE 'browser_recovery:%'"
        ).fetchall()[0][:] == ("browser_recovery:" + shape, method)


@pytest.mark.parametrize("case", ["shape", "method", "corrupt"])
def test_strategy_memory_cannot_supply_arbitrary_actions(data, case):
    store = Store(data / "applicator.sqlite3")
    if case == "corrupt":
        with store.connect() as db:
            db.execute(
                "INSERT INTO config VALUES (?,?)", ("browser_recovery:checkbox-010", "submit")
            )
        assert store.recovery_strategy("checkbox-010") is None
    else:
        with pytest.raises(ValueError):
            store.recovery_strategy("unsafe" if case == "shape" else "checkbox-010", "submit")


def recovery_service(data, profile, job):
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    ident, _ = store.add_job(job)
    adapter = Mock()
    service = Service(store, data, {"fixture": adapter})
    service.prepare(ident)
    adapter.submit.side_effect = ReviewRequired("Locator.click: Timeout on a reversible control")
    with pytest.raises(ReviewRequired):
        service.submit(ident)
    return store, service, adapter, ident


@pytest.mark.parametrize(
    "case", ["resume", "exhausted", "paused", "quota", "budget", "documents", "unknown", "race"]
)
def test_fifo_recovery_reuses_documents_respects_limits_and_never_loops(
    data, profile, job, case, monkeypatch
):
    store, service, adapter, ident = recovery_service(data, profile, job)
    original = store.application(ident)["manifest"]
    assert "Locator.click" in service.preflight(ident).checks[2].detail
    if case == "paused":
        settings = store.settings()
        settings.automation_enabled = False
        store.set_settings(settings)
    elif case == "quota":
        with store.connect() as db:
            db.execute("UPDATE attempts SET status='sending'")
    elif case == "budget":
        settings = store.settings()
        settings.daily_limit = 1
        store.set_settings(settings)
        other, _ = store.add_job(
            job.model_copy(update={"source_id": "other", "url": "https://example.test/other"})
        )
        with store.connect() as db:
            db.execute(
                "INSERT INTO attempts(application_id,day,started,status,confirmed_day) VALUES(?,?,?,'confirmed',?)",
                (other, day_key(), "fixture", day_key()),
            )
    elif case == "documents":
        document = data / "documents" / str(ident) / original["files"]["cv_pdf"]["name"]
        document.write_bytes(document.read_bytes() + b"Changed fixture")
    elif case == "unknown":
        with store.connect() as db:
            db.execute(
                "UPDATE events SET detail='Approve an exact answer for: Salary' WHERE kind='provider_review_required'"
            )
    elif case == "race":
        available = store.form_recovery_available
        monkeypatch.setattr(
            store,
            "form_recovery_available",
            lambda app_id, claim=False: False if claim else available(app_id),
        )
    if case == "resume":
        adapter.submit.side_effect = None
        adapter.submit.return_value = "fixture:confirmed"
        assert service.queue_pending()
    for _ in range(4):
        service.tick()
    assert store.application(ident)["manifest"] == original
    if case == "resume":
        assert adapter.submit.call_count == 2
        assert store.application(ident)["state"] == State.SUBMITTED
        assert store.daily_usage().used == 1
    elif case == "exhausted":
        assert adapter.submit.call_count == 3
        assert not service.queue_pending()
        assert not Store(store.path).form_recovery_available(ident)
        assert store.daily_usage().remaining == 10
    else:
        assert adapter.submit.call_count == 1


def test_recovery_budget_is_transactional_and_persists_across_restart(data, profile, job):
    store, _, _, ident = recovery_service(data, profile, job)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda _: Store(store.path).form_recovery_available(ident, claim=True), range(12)
            )
        )
    assert results.count(True) == 2
    assert not Store(store.path).form_recovery_available(ident)
    assert (
        len([event for event in store.events(ident) if event["kind"] == "form_recovery_queued"])
        == 2
    )


def test_provider_blocker_is_retained_once_with_unchanged_materials(data, profile, job):
    store, service, _, ident = recovery_service(data, profile, job)
    before = store.application(ident)
    detail = "Locator.click: Timeout on a reversible control"
    store.hold(ident, detail)
    after = store.application(ident)
    assert after["evaluation"]["blockers"].count(detail) == 1
    assert after["manifest"] == before["manifest"]
    assert detail in service.preflight(ident).checks[2].detail


def test_uncertain_outcome_cannot_enter_technical_recovery(data, profile, job):
    store, service, adapter, ident = recovery_service(data, profile, job)
    service.refresh_readiness(ident)
    adapter.submit.side_effect = TimeoutError("Fixture confirmation unavailable")
    with pytest.raises(TimeoutError):
        service.submit(ident)
    assert store.application(ident)["state"] == State.UNCERTAIN
    assert not store.form_recovery_available(ident, claim=True)
    for _ in range(3):
        service.tick()
    assert adapter.submit.call_count == 2


@pytest.mark.parametrize(
    "case",
    [
        "absent",
        "no_attempt",
        "held",
        "sending",
        "submitted",
        "no_event",
        "login",
        "unknown",
        "corrupt",
    ],
)
def test_only_proven_released_technical_holds_can_recover(data, profile, job, case):
    store, _, _, ident = recovery_service(data, profile, job)
    with store.connect() as db:
        if case == "no_attempt":
            db.execute("DELETE FROM attempts")
        elif case in {"held", "sending"}:
            db.execute("UPDATE attempts SET status=?", (case,))
        elif case == "submitted":
            db.execute("UPDATE applications SET state='submitted'")
        elif case == "no_event":
            db.execute("DELETE FROM events WHERE kind='provider_review_required'")
        elif case in {"login", "unknown"}:
            db.execute(
                "UPDATE events SET detail=? WHERE kind='provider_review_required'",
                (
                    "Locator.wait: authwall login"
                    if case == "login"
                    else "Approve an exact answer for: Consent",
                ),
            )
        elif case == "corrupt":
            db.execute("INSERT INTO config VALUES (?,?)", (f"form_recovery:v1:{ident}", "-1"))
    assert not store.form_recovery_available(999 if case == "absent" else ident, claim=True)


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "hidden_label",
        "wrapped",
        "aria",
        "rerender",
        "timeout",
        "memory",
        "changed",
        "broken",
        "idless",
    ],
)
def test_boolean_recovery_verifies_state_after_alternative_interaction(
    profile, data, case, monkeypatch
):
    label = "Follow Example Employer to stay up to date with their page."
    html = (
        f'<label for="q">{label}</label><input id="q" type="checkbox" checked style="display:none">'
    )
    target = False
    if case in {"wrapped", "aria", "broken"}:
        native = '<input id="q" type="checkbox" hidden checked>' if case != "aria" else ""
        identity = 'id="q"' if case == "aria" else 'id="card"'
        handler = "this.setAttribute('aria-checked','false');" + (
            "this.querySelector('input').checked=false;" if case == "wrapped" else ""
        )
        if case == "broken":
            handler = ""
        html = f'<div {identity} role="checkbox" aria-label="{label}" aria-checked="true" onclick="{handler}">{label}{native}</div>'
    elif case in {"timeout", "memory"}:
        html = html.replace('style="display:none"', "")
    elif case == "rerender":
        html += "<script>document.getElementById('q').onchange=()=>{const old=document.getElementById('q');const fresh=old.cloneNode();fresh.id='new';fresh.checked=false;old.replaceWith(fresh);document.querySelector('label').htmlFor='new';};</script>"
    elif case == "changed":
        html += "<script>document.getElementById('q').onchange=()=>document.querySelector('label').textContent='Different consent';</script>"
    elif case == "idless":
        label = "Optional newsletter"
        target = True
        profile.answers["question:" + label.casefold()] = "Yes"
        html = f'<label>{label}<input type="checkbox"></label>'
    store = Store(data / "applicator.sqlite3")
    if case == "memory":
        store.recovery_strategy("checkbox-110", "aria")
    if case == "timeout":
        original = Locator.set_checked

        def fail_once(locator, value, **kwargs):
            if not getattr(fail_once, "failed", False):
                fail_once.failed = True
                raise BrowserTimeout("Fixture input became stale")
            return original(locator, value, **kwargs)

        monkeypatch.setattr(Locator, "set_checked", fail_once)
    stages = []
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content("<dialog open>" + html + "</dialog>")
        if case in {"changed", "broken"}:
            with pytest.raises(ValueError, match="identity|three recovery"):
                fill_questions(page, profile, memory=store.recovery_strategy)
        else:
            fill_questions(
                page,
                profile,
                memory=store.recovery_strategy,
                progress=lambda s, d: stages.append((s, d)),
            )
            control = page.locator(
                "#new" if case == "rerender" else "input" if case == "idless" else "#q"
            )
            assert (
                (control.get_attribute("aria-checked") == str(target).lower())
                if case == "aria"
                else control.is_checked() == target
            )
            assert any(stage == "form_recovered" for stage, _ in stages)
            with store.connect() as db:
                learned = db.execute(
                    "SELECT value FROM config WHERE key LIKE 'browser_recovery:%'"
                ).fetchall()
                assert learned and all(row[0] in {"native", "label", "aria"} for row in learned)
        assert page.get_by_role("button", name="Submit application").count() == 0


@pytest.mark.browser
def test_hidden_radio_reacquires_both_changed_ids_and_remembers_label_strategy(profile, data):
    label = "Will you require sponsorship?"
    profile.answers["question:" + label.casefold()] = "Yes"
    html = f'<fieldset><legend>{label}</legend><label for="yes">Yes</label><input id="yes" type="radio" name="q" style="display:none"><label for="no">No</label><input id="no" type="radio" name="q" checked style="display:none"></fieldset><button>Next</button>'
    html += """<script>document.getElementById('yes').onchange=()=>{
      document.querySelectorAll('input').forEach(old=>{
        const fresh=old.cloneNode();fresh.id=old.id+'-new';fresh.checked=old.checked;
        document.querySelector('label[for='+old.id+']').htmlFor=fresh.id;old.replaceWith(fresh);
      });};</script>"""
    memory = Store(data / "applicator.sqlite3")
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content("<dialog open>" + html + "</dialog>")
        fill_questions(page, profile, memory=memory.recovery_strategy)
        assert page.locator("#yes-new").is_checked()
        assert not page.locator("#no-new").is_checked()
        assert Store(memory.path).recovery_strategy("radio-010") == "label"


@pytest.mark.browser
@pytest.mark.parametrize(
    "case", ["missing_state", "disabled_race", "changed_choices", "post_constraint"]
)
def test_recovery_stops_on_changed_identity_constraints_or_unreadable_state(
    profile, case, monkeypatch
):
    label = "Follow Example Employer to stay up to date"
    html = f'<label>{label}<input id="q" type="checkbox" checked></label>'
    if case == "missing_state":
        html = f'<div id="q" role="checkbox" aria-label="{label}">{label}</div>'
    if case == "changed_choices":
        label = "Sponsorship required"
        profile.answers["question:" + label.casefold()] = "Yes"
        html = f'<fieldset><legend>{label}</legend><label>Yes<input id="q" type="radio" name="choice" onchange="document.getElementById(\'no\').disabled=true"></label><label>No<input id="no" type="radio" name="choice"></label></fieldset>'
    if case == "post_constraint":
        label = "Recruitment notice"
        profile.answers["question:" + label.casefold()] = "Yes"
        html = f'<label>{label}<input id="q" type="checkbox" onclick="this.setCustomValidity(\'Fixture constraint\')"></label>'
    if case == "disabled_race":
        original = Locator.evaluate

        def disable_before_observation(locator, expression, *args, **kwargs):
            if "native:el.tagName" in expression:
                original(locator, "el=>el.disabled=true")
            return original(locator, expression, *args, **kwargs)

        monkeypatch.setattr(Locator, "evaluate", disable_before_observation)
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content("<dialog open>" + html + "<button>Next</button></dialog>")
        with pytest.raises(ValueError, match="checked state|disabled|choices|invalid constraint"):
            fill_questions(page, profile)
        assert page.get_by_role("button", name="Next").is_visible()


@pytest.mark.browser
def test_hidden_duplicates_are_ignored_but_visible_phone_ambiguity_is_retained(profile):
    html = '<label>Email<input id="email"></label><div hidden><label>Phone country code<select id="clone"><option>Ireland (+353)</option></select></label><label>Mobile phone number<input id="clone-phone"></label><input required id="unknown"></div>'
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content("<dialog open>" + html + "</dialog>")
        assert len(form_questions(page)) == 1
        fill_questions(page, profile)
        assert page.locator("#email").input_value() == profile.email
        assert not page.locator("#clone-phone").input_value()


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    ["duplicate_id", "visibility_hidden", "opacity_zero", "disabled_wrapper", "disabled_fieldset"],
)
def test_recovery_preserves_visible_identity_and_disabled_boundaries(profile, case):
    html = '<label>Email<input id="q"></label>'
    if case == "duplicate_id":
        html += '<label>Salary<input id="q"></label>'
    elif case in {"visibility_hidden", "opacity_zero"}:
        style = "visibility:hidden" if case == "visibility_hidden" else "opacity:0"
        html += f'<div style="{style}"><label>Phone country code<select id="clone"><option>Ireland (+353)</option></select></label><input required></div>'
    elif case == "disabled_wrapper":
        html += '<div role="checkbox" aria-disabled="true" aria-checked="true" aria-label="Follow Example Employer to stay up to date" onclick="window.clicked=true"><input id="disabled" type="checkbox" checked hidden></div>'
    else:
        html += '<fieldset disabled><label>Unknown required fact<input required id="disabled"></label></fieldset>'
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content("<dialog open>" + html + "<button>Next</button></dialog>")
        if case == "duplicate_id":
            with pytest.raises(ValueError, match="Ambiguous form control identifiers"):
                fill_questions(page, profile)
            assert all(
                not value
                for value in page.locator("input").evaluate_all("nodes=>nodes.map(n=>n.value)")
            )
        else:
            fill_questions(page, profile)
            assert page.locator("#q").input_value() == profile.email
            assert len(form_questions(page)) == 1
            assert page.evaluate("window.clicked") is None


@pytest.mark.browser
def test_advance_rereads_a_transition_that_completed_before_the_next_action(profile, monkeypatch):
    from applicator import browser as module

    original = module.application_step
    reads = []

    def transition(dialog):
        result = original(dialog)
        reads.append(result)
        if len(reads) == 1:
            dialog.evaluate(
                "el=>{el.querySelector('#next').hidden=true;el.querySelector('#submit').hidden=false;}"
            )
        return result

    monkeypatch.setattr(module, "application_step", transition)
    html = '<main><dialog open><button id="next" onclick="window.clicked=true">Next</button><button id="submit" hidden>Submit application</button></dialog></main>'
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body=html))
        page.goto("https://www.linkedin.com/jobs/view/123/")
        advance_application(
            page, profile, resume_field_ids=None, resolver=None, progress=Mock(), memory=Mock()
        )
        assert page.evaluate("window.clicked") is None
        assert page.locator("#submit").is_visible()


@pytest.mark.browser
def test_invalid_field_diagnostics_exclude_dropdown_answer_values(profile):
    html = f'<main><dialog open><label>Email<select id="q" aria-invalid="true"><option>{profile.email}</option></select></label><button>Next</button></dialog></main>'
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body=html))
        page.goto("https://www.linkedin.com/jobs/view/123/")
        with pytest.raises(ValueError, match="invalid fields: Email") as error:
            advance_application(
                page, profile, resume_field_ids=None, resolver=None, progress=Mock(), memory=Mock()
            )
        assert profile.email not in str(error.value)


@pytest.mark.browser
@pytest.mark.parametrize("case", ["second_click", "stalled", "invalid"])
def test_advance_recovery_does_not_reupload_or_submit(profile, case):
    handler = (
        "window.clicks++;if(window.clicks===2){this.hidden=true;document.getElementById('submit').hidden=false;}"
        if case == "second_click"
        else "window.clicks++;"
    )
    html = f'<main><dialog open><label>Email<input id="email" required value="{profile.email}"></label><button id="next" onclick="{handler}">Next</button><button id="submit" hidden>Submit application</button></dialog></main><script>window.clicks=0;</script>'
    if case == "invalid":
        html = html.replace(
            "window.clicks++;",
            "window.clicks++;document.getElementById('email').setCustomValidity('Fixture validation');",
            1,
        )
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body=html))
        page.goto("https://www.linkedin.com/jobs/view/123/")
        arguments = dict(
            resume_field_ids=None, resolver=None, progress=Mock(), memory=Mock(return_value=None)
        )
        if case == "second_click":
            advance_application(page, profile, **arguments)
            assert page.evaluate("window.clicks") == 2
        else:
            with pytest.raises(ValueError, match="did not advance"):
                advance_application(page, profile, **arguments)
            assert page.evaluate("window.clicks") == (1 if case == "invalid" else 3)
        assert page.locator("input[type=file]").count() == 0


@pytest.mark.browser
@pytest.mark.parametrize("case", ["link", "external", "ambiguous", "partial_open", "missing"])
def test_opening_recovery_remains_on_the_reviewed_opportunity(case, monkeypatch):
    action = (
        '<a href="#" onclick="document.querySelector(\'dialog\').showModal()">Easy Apply</a>'
        if case in {"link", "external"}
        else "<button onclick=\"document.querySelector('dialog').showModal()\">Easy Apply</button>"
    )
    if case == "external":
        action = action.replace('href="#"', 'href="https://example.test/apply"')
    if case == "ambiguous":
        action += action
    if case == "missing":
        action = ""
    html = "<main>" + action + "<dialog><button>Next</button></dialog></main>"
    if case == "missing":
        original_wait = Locator.wait_for

        def fast_wait(locator, **kwargs):
            if locator.count() == 0:
                raise BrowserTimeout("Fixture missing control")
            return original_wait(locator, **kwargs)

        monkeypatch.setattr(Locator, "wait_for", fast_wait)
    if case == "partial_open":
        original_click = Locator.click

        def partial_click(locator, **kwargs):
            original_click(locator, **kwargs)
            raise BrowserTimeout("Fixture dialogue opened before timeout")

        monkeypatch.setattr(Locator, "click", partial_click)
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body=html))
        page.goto("https://www.linkedin.com/jobs/view/123/")
        if case in {"external", "ambiguous", "missing"}:
            with pytest.raises(ValueError):
                open_easy_apply(page, Mock())
        else:
            open_easy_apply(page, Mock())
            assert page.get_by_role("dialog").is_visible()
        assert page.url.startswith("https://www.linkedin.com/jobs/view/123/")
