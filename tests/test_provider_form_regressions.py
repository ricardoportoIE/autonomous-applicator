"""Fictional reproductions of provider form failures; no live submissions."""

import json
from unittest.mock import Mock

import pytest
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import sync_playwright

from applicator.browser import (
    advance_application,
    browser_options,
    fill_questions,
    form_questions,
    open_easy_apply,
)
from applicator.models import Question
from applicator.routine_answers import routine_answer


@pytest.fixture(scope="module")
def local_browser():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        yield browser


@pytest.mark.browser
@pytest.mark.parametrize("label", ["Phone", "Phone number", "Mobile phone number"])
def test_contact_phone_aliases_split_confirmed_international_number(local_browser, profile, label):
    page = local_browser.new_page()
    try:
        page.set_content(
            f'<dialog open><label>Phone country code<select id="country"><option>Ireland (+353)</option><option>United Kingdom (+44)</option></select></label><label>{label}<input id="phone" type="tel" required></label></dialog>'
        )
        fill_questions(page, profile)
        assert page.locator("#country").input_value() == "Ireland (+353)"
        assert page.locator("#phone").input_value() == "000000000"
    finally:
        page.close()


@pytest.mark.browser
def test_numeric_keyboard_hint_does_not_strip_an_approved_telephone_prefix(local_browser, profile):
    page = local_browser.new_page()
    try:
        page.set_content(
            '<dialog open><label>Phone<input id="phone" type="tel" inputmode="numeric" required></label></dialog>'
        )
        fill_questions(page, profile)
        assert page.locator("#phone").input_value() == profile.phone
    finally:
        page.close()


def city_html(case):
    label = "Location (city)*" if case == "required" else "Location (city)"
    attributes = 'aria-label="Unreviewed location claim"' if case == "conflict" else ""
    if case == "unrecognised":
        label = "Where will you relocate?"
    choices = [
        "Dublin, Ohio, United States",
        "Greater Dublin",
        "Dublin, County Dublin, Ireland",
        "Dublin 4, Ireland",
    ]
    if case == "ambiguous":
        choices.append("Dublin, Ireland")
    if case == "foreign":
        choices = ["Dublin, Ohio, United States", "Dublin, Northern Ireland, United Kingdom"]
    if case == "disabled":
        choices = ["Dublin, County Dublin, Ireland"]
    offered = "".join(
        f'<div role="option" {"aria-disabled=true" if case == "disabled" else ""} onclick="choose(this)"><button type="button">{choice}</button></div>'
        for choice in choices
    )
    return f"""<dialog open><div componentkey="easyApplyFieldFocus_city">
      <p>{label}</p><div role="status" aria-live="polite"></div>
      <div data-expanded="false"><input id="city" data-testid="typeahead-input" aria-autocomplete="list" placeholder="Enter city or location" {attributes}>
      <div data-testid="typeahead-results-container" role="listbox" aria-labelledby="city" hidden>{offered}</div></div>
      </div><button onclick="window.sent=true">Submit application</button></dialog>
      <script>
      const mode={json.dumps(case)};
      document.querySelector('input').oninput=function(){{
        const list=document.querySelector('[role=listbox]');
        if(mode==='missing') return;
        if(mode==='rerender'){{const fresh=this.cloneNode();fresh.id='new-city';this.replaceWith(fresh);list.setAttribute('aria-labelledby',fresh.id);}}
        list.hidden=false;
        if(mode==='unmapped') list.setAttribute('aria-labelledby','unrelated');
      }};
      function choose(el){{
        const input=document.querySelector('input');
        input.value=mode==='wrong'?'Dublin, Ohio, United States':el.textContent.trim();
        if(mode==='invalid') input.setCustomValidity('Rejected selection');
        if(mode!=='open') document.querySelector('[role=listbox]').hidden=true;
      }}
      </script>"""


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "normal",
        "required",
        "rerender",
        "ambiguous",
        "foreign",
        "disabled",
        "unmapped",
        "wrong",
        "invalid",
        "open",
        "missing",
        "unrecognised",
        "conflict",
        "unconfirmed",
        "empty",
        "missing_country",
        "country_only",
    ],
)
def test_city_requires_verified_pattern_unique_country_and_selection(local_browser, profile, case):
    page = local_browser.new_page()
    try:
        page.set_content(city_html(case))
        if case == "unconfirmed":
            profile.confirmed = False
        elif case == "empty":
            profile.location = ""
        elif case == "missing_country":
            profile.location = "Dublin, "
        elif case == "country_only":
            profile.location = "Ireland"
        field = form_questions(page)[0]
        if case in {"normal", "required", "rerender"}:
            assert field["type"] == "location-typeahead"
            assert field["required"] == (case == "required")
            fill_questions(page, profile)
            assert page.locator("input").input_value() == "Dublin, County Dublin, Ireland"
            assert not page.get_by_role("listbox").is_visible()
        elif case == "missing":
            with pytest.raises(BrowserTimeout):
                fill_questions(page, profile)
        elif case == "conflict":
            assert field["type"] == "text"
            assert page.locator("input").input_value() == ""
        else:
            with pytest.raises(ValueError):
                fill_questions(page, profile)
        assert page.evaluate("window.sent") is None
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize(
    "label,mode,value,accepted",
    [
        (
            "How many years of work experience do you have with Python (Programming Language)?",
            "",
            "Experience since 2023.",
            False,
        ),
        (
            "How many years of work experience do you have with Python (Programming Language)?",
            "",
            "3",
            True,
        ),
        ("How many years of work experience do you have with AI Agents?", "", "0", True),
        ("How many years of experience with Python?", "", "2.5", True),
        ("Approved numeric field", "numeric", "three", False),
        ("Approved decimal field", "decimal", "2.5", True),
        ("Approved description", "", "Experience since 2023.", True),
    ],
)
def test_numeric_text_fields_reject_narrative_before_filling(
    local_browser, profile, label, mode, value, accepted
):
    profile.answers["question:" + label.casefold()] = value
    page = local_browser.new_page()
    try:
        page.set_content(
            f'<dialog open><label>{label}<input id="q" type="text" inputmode="{mode}" required></label><button onclick="window.clicked=true">Next</button></dialog>'
        )
        if accepted:
            fill_questions(page, profile)
            assert page.locator("#q").input_value() == value
        else:
            with pytest.raises(ValueError, match="Approve an exact answer for:"):
                fill_questions(page, profile)
            assert not page.locator("#q").input_value()
        assert page.evaluate("window.clicked") is None
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("case", ["labelled", "unlabelled", "unrelated"])
def test_provider_inline_validation_stops_before_repeated_navigation(local_browser, profile, case):
    row_label = "<p>Approved numeric field*</p>" if case != "unlabelled" else ""
    message = '<div role="status">Private rejected answer text</div>'
    scope = "other" if case == "unrelated" else "easyApplyFieldFocus_number"
    handler = "window.clicks++;"
    if case == "unrelated":
        handler += "document.querySelector('h2').textContent='Next stage';"
    html = f'<main><dialog open><h2>Questions</h2><div componentkey="{scope}">{row_label}{message}<label>Email<input value="{profile.email}"></label></div><button onclick="{handler}">Next</button></dialog></main><script>window.clicks=0</script>'
    page = local_browser.new_page()
    try:
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        page.goto("https://www.linkedin.com/jobs/view/123/")
        arguments = dict(resume_field_ids=None, resolver=None, progress=Mock(), memory=Mock())
        if case == "unrelated":
            advance_application(page, profile, **arguments)
        else:
            with pytest.raises(ValueError, match="invalid fields:") as error:
                advance_application(page, profile, **arguments)
            assert "Private rejected answer text" not in str(error.value)
            assert profile.email not in str(error.value)
            assert ("Approved numeric field" if case == "labelled" else "Unlabelled field") in str(
                error.value
            )
        assert page.evaluate("window.clicks") == 1
    finally:
        page.close()


@pytest.mark.browser
@pytest.mark.parametrize("case", ["closed", "recommendation", "missing_anchor", "no_main"])
def test_closed_status_is_scoped_to_primary_job_header(local_browser, case):
    status = "<p>No longer accepting applications</p>"
    anchor = '<h2>About the job</h2><div id="job-details">Description</div>'
    body = status + anchor if case == "closed" else anchor + status
    if case == "missing_anchor":
        body = status
    if case == "no_main":
        body = ""
    html = f"<main>{body}<button onclick=\"window.clicked=true;document.querySelector('dialog').showModal()\">Easy Apply</button><dialog><button>Next</button></dialog></main>"
    if case == "no_main":
        html = html.replace("<main>", "<div>").replace("</main>", "</div>")
    page = local_browser.new_page()
    try:
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        page.goto("https://www.linkedin.com/jobs/view/123/")
        if case == "closed":
            with pytest.raises(ValueError, match="no longer accepting applications"):
                open_easy_apply(page, Mock())
            assert page.evaluate("window.clicked") is None
        else:
            open_easy_apply(page, Mock())
            assert page.evaluate("window.clicked") is True
    finally:
        page.close()


@pytest.mark.parametrize(
    "location,choices,expected",
    [
        ("Dublin, Ireland", ["Yes", "No"], "Yes"),
        ("Belfast, Northern Ireland", ["Yes", "No"], None),
        ("London, United Kingdom", ["Yes", "No"], None),
        ("Ireland", [], None),
    ],
)
def test_current_residence_is_not_legal_eligibility(profile, job, location, choices, expected):
    profile.location = location
    result = routine_answer(
        profile,
        job,
        Question(id="q", label="Are you currently located and living in Ireland?", choices=choices),
    )
    assert (result.answer if result else None) == expected
    assert (
        routine_answer(
            profile,
            job,
            Question(
                id="legal",
                label="Are you legally authorised to work in Ireland?",
                choices=["Yes", "No"],
            ),
        )
        is None
    )


@pytest.mark.parametrize("category,expected", [("experience", "3"), ("project", None)])
def test_work_experience_duration_requires_approved_employment_evidence(
    profile, job, category, expected
):
    profile.evidence[0].category = category
    profile.evidence[0].text = "3 years Python."
    result = routine_answer(
        profile,
        job,
        Question(id="q", label="How many years of work experience do you have with Python?"),
    )
    assert (result.answer if result else None) == expected
