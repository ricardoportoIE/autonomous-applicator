"""City portals are linked to the reviewed input; unrelated suggestions cannot qualify."""

from unittest.mock import Mock

import pytest
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import sync_playwright
from test_provider_form_regressions import city_html

from applicator.browser import browser_options, collect_questions, fill_questions


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as instance:
        yield instance


@pytest.mark.browser
@pytest.mark.parametrize("placement", ["row", "dialogue_portal", "body_portal"])
@pytest.mark.parametrize("replacement", [False, True])
def test_city_selection_uses_linked_portal_without_test_id(
    browser, profile, placement, replacement
):
    page = browser.new_page()
    try:
        page.set_content(city_html("rerender" if replacement else "normal"))
        page.evaluate(
            """placement => {
              const list=document.querySelector('[role=listbox]');
              list.removeAttribute('data-testid');
              if(placement==='dialogue_portal') document.querySelector('dialog').append(list);
              if(placement==='body_portal') {
                document.body.append(list);
                list.style.cssText='position:relative;z-index:10;background:white';
              }
              const unrelated=document.createElement('div');
              unrelated.setAttribute('role','listbox');
              unrelated.setAttribute('aria-labelledby','another-city');
              unrelated.innerHTML='<div role="option" onclick="window.wrong=true">Dublin, Ireland</div>';
              document.body.append(unrelated);
            }""",
            placement,
        )
        fill_questions(page, profile)
        assert page.locator("input").input_value() == "Dublin, County Dublin, Ireland"
        assert page.evaluate("window.wrong") is None
        assert page.evaluate("window.sent") is None
    finally:
        page.close()


@pytest.mark.browser
def test_city_mapping_escapes_id_and_accepts_labelledby_token_relationship(browser, profile):
    page = browser.new_page()
    try:
        page.set_content(city_html("normal"))
        page.evaluate(
            """() => {
              document.querySelector('input').id='city:with"quote';
              document.querySelector('[role=listbox]').setAttribute('aria-labelledby','description city:with"quote');
            }"""
        )
        fill_questions(page, profile)
        assert page.locator("input").input_value() == "Dublin, County Dublin, Ireland"
        assert page.evaluate("window.sent") is None
    finally:
        page.close()


@pytest.mark.browser
def test_delayed_mapped_city_portal_is_observed_before_selection(browser, profile):
    page = browser.new_page()
    try:
        page.set_content(city_html("missing"))
        page.evaluate(
            """() => document.querySelector('input').oninput = () => {
              setTimeout(()=>document.querySelector('[role=listbox]').hidden=false,100);
            }"""
        )
        fill_questions(page, profile)
        assert page.locator("input").input_value() == "Dublin, County Dublin, Ireland"
        assert page.evaluate("window.sent") is None
    finally:
        page.close()


@pytest.mark.browser
def test_missing_city_input_identifier_cannot_map_any_portal(browser, profile, monkeypatch):
    from playwright.sync_api import Locator

    original_attribute = Locator.get_attribute
    monkeypatch.setattr(
        Locator,
        "get_attribute",
        lambda locator, name, **kwargs: (
            None if name == "id" else original_attribute(locator, name, **kwargs)
        ),
    )
    page = browser.new_page()
    try:
        page.set_content(city_html("normal"))
        with pytest.raises(ValueError, match="Unmapped city suggestions"):
            fill_questions(page, profile)
        assert page.locator("input").input_value() == "Dublin"
        assert page.evaluate("window.sent") is None
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("failure", ["duplicate_list", "duplicate_city", "foreign", "disabled"])
def test_ambiguous_or_ineligible_portal_choices_fail_without_selection(browser, profile, failure):
    page = browser.new_page()
    try:
        mode = {"duplicate_city": "ambiguous", "foreign": "foreign", "disabled": "disabled"}.get(
            failure, "normal"
        )
        page.set_content(city_html(mode))
        page.evaluate(
            """duplicate => {
              const list=document.querySelector('[role=listbox]');
              document.body.append(list);
              if(duplicate) {
                const other=list.cloneNode(true); other.hidden=false;
                document.body.append(other);
              }
            }""",
            failure == "duplicate_list",
        )
        with pytest.raises(ValueError, match="City suggestions"):
            fill_questions(page, profile)
        assert page.locator("input").input_value() == "Dublin"
        assert page.evaluate("window.sent") is None
    finally:
        page.close()


@pytest.mark.browser
def test_city_timeout_retains_other_pending_questions_and_completes_known_fields(
    browser, profile, monkeypatch
):
    page = browser.new_page()
    try:
        page.set_content(city_html("missing"))
        page.locator("dialog").evaluate(
            """dialog => dialog.insertAdjacentHTML('beforeend',
              '<label>First name<input id="first" required></label>'+
              '<label>Unconfirmed salary<input id="salary" required></label>')"""
        )
        from playwright.sync_api import Locator

        original_wait = Locator.wait_for
        observed_timeouts = []

        def wait(locator, **kwargs):
            if "listbox" in str(locator):
                observed_timeouts.append(kwargs["timeout"])
                raise BrowserTimeout("Fictional mapped portal timeout")
            return original_wait(locator, **kwargs)

        monkeypatch.setattr(Locator, "wait_for", wait)
        pending = {}
        assert not collect_questions(
            page,
            profile,
            pending,
            resume_field_ids=None,
            resolver=Mock(return_value=None),
            progress=Mock(),
            memory=None,
        )
        assert set(pending) == {"question:location (city)", "question:unconfirmed salary"}
        assert observed_timeouts == [10000]
        assert page.locator("#first").input_value() == profile.name.split()[0]
        assert page.locator("#salary").input_value() == ""
        assert page.evaluate("window.sent") is None
    finally:
        page.close()
