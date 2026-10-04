"""Typed questionnaire controls, available options and verified selections in Chromium."""

import pytest
from playwright.sync_api import sync_playwright

from applicator.browser import browser_options, fill_questions, form_questions


@pytest.mark.browser
@pytest.mark.parametrize("widget", ["native", "aria", "wrapped"])
@pytest.mark.parametrize("answer", ["Yes", "No", "unknown", "invalid", "broken", "required_no"])
def test_checkboxes_use_exact_answers_and_verify_both_states(profile, widget, answer):
    label = "I agree to the recruitment privacy notice"
    expected = answer == "Yes"
    required = "required" if answer in {"unknown", "invalid", "required_no"} else ""
    attr = 'aria-required="true"' if required else ""
    initial = "true" if answer == "No" else "false"
    html = f'<label>{label}<input id="q" type="checkbox" {required}></label>'
    if widget != "native":
        native = (
            f'<input id="native" type="checkbox" hidden {required}>' if widget == "wrapped" else ""
        )
        identity = 'id="q"' if widget == "aria" else 'id="card"'
        if widget == "wrapped":
            native = native.replace('id="native"', 'id="q"')
        handler = (
            ""
            if answer == "broken"
            else "this.setAttribute('aria-checked',this.getAttribute('aria-checked')==='true'?'false':'true');"
        )
        if widget == "wrapped" and answer != "broken":
            handler += (
                "this.querySelector('input').checked=this.getAttribute('aria-checked')==='true'"
            )
        html = f'<div {identity} role="checkbox" aria-label="{label}" {attr} aria-checked="{initial}" onclick="{handler}">{label}{native}</div>'
    if answer == "No" and widget == "native":
        html = html.replace('type="checkbox"', 'type="checkbox" checked')
    value = "No" if answer == "required_no" else "Yes" if answer == "broken" else answer
    if answer != "unknown":
        profile.answers["question:" + label.casefold()] = value
    calls = []

    def resolve(question):
        calls.append(question)
        return None

    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content("<dialog open>" + html + "</dialog>")
        if answer in {"unknown", "invalid", "required_no"} or (
            answer == "broken" and widget != "native"
        ):
            with pytest.raises(ValueError):
                fill_questions(page, profile, resolver=resolve)
        else:
            progress = []
            fill_questions(
                page,
                profile,
                resolver=resolve,
                progress=lambda stage, detail: progress.append((stage, detail)),
            )
            assert progress[0][0] == "answering_questions"
            assert label in progress[0][1] and "checkbox" in progress[0][1]
            if widget == "aria":
                assert (
                    page.locator("#q").get_attribute("aria-checked")
                    == str(expected or answer == "broken").lower()
                )
            else:
                assert page.locator("#q").is_checked() == (expected or answer == "broken")
        if answer in {"unknown", "invalid"}:
            assert len(calls) == 1
            assert calls[0].label == label and calls[0].choices == ["Yes", "No"]


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "known",
        "input",
        "resolved",
        "resolver_wrong",
        "unknown",
        "wrong",
        "disabled",
        "duplicate",
        "no_choices",
        "no_controls",
        "two_controls",
        "wrong_listbox",
        "duplicate_id",
        "broken",
    ],
)
def test_custom_combobox_reads_scoped_enabled_options_and_verifies_selection(profile, case):
    label = "Sponsorship required"
    controls = (
        ""
        if case == "no_controls"
        else 'aria-controls="options extra"'
        if case == "two_controls"
        else 'aria-controls="options"'
    )
    tag = "input" if case == "input" else 'button type="button"'
    closing = "" if case == "input" else "Choose</button>"
    html = f'<span id="label">{label}*</span><{tag} id="q" role="combobox" aria-labelledby="label" aria-required="true" {controls} onclick="document.getElementById(\'options\').hidden=false">{closing}'
    role = "group" if case == "wrong_listbox" else "listbox"
    handler = (
        ""
        if case == "broken"
        else "document.getElementById('q').setAttribute('aria-valuetext',this.textContent);document.getElementById('options').hidden=true"
    )
    choices = (
        ""
        if case == "no_choices"
        else f'<div role="option" onclick="{handler}">No</div><div role="option" onclick="{handler}" {"aria-disabled=true" if case == "disabled" else ""}>Yes</div>'
    )
    if case == "duplicate":
        choices += '<div role="option">Yes</div>'
    if case == "duplicate_id":
        html += '<button id="q" role="combobox">Duplicate</button>'
    html += (
        f'<section id="options" role="{role}" style="min-height:20px" hidden>{choices}</section>'
    )
    if case not in {"resolved", "resolver_wrong", "unknown"}:
        profile.answers["question:" + label.casefold()] = "Maybe" if case == "wrong" else "Yes"
    calls = []

    def resolve(question):
        calls.append(question)
        return "Yes" if case == "resolved" else "Maybe" if case == "resolver_wrong" else None

    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(
            "<dialog open>"
            + html
            + '</dialog><div role="listbox"><div role="option">Unrelated</div></div>'
        )
        assert form_questions(page)[0]["label"] == label
        if case in {"known", "input", "resolved"}:
            fill_questions(page, profile, resolver=resolve)
            assert page.locator("#q").get_attribute("aria-valuetext") == "Yes"
            assert form_questions(page)[0]["value"] == "Yes"
        else:
            with pytest.raises(ValueError):
                fill_questions(page, profile, resolver=resolve)
        if calls:
            assert calls[0].choices == (["No"] if case == "disabled" else ["No", "Yes"])
            assert calls[0].required


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "select",
        "whitespace",
        "select_disabled",
        "disabled_duplicate",
        "changed_options",
        "changed_duplicate",
        "selected_disabled",
        "option_label",
        "duplicate",
        "select_broken",
        "number",
        "negative",
        "not_numeric",
        "date",
        "pattern",
        "maxlength",
        "custom_invalid",
        "unsupported",
        "multiple",
        "duplicate_id",
    ],
)
def test_native_fields_respect_options_types_constraints_and_identity(profile, case):
    answer = "Yes"
    if case in {
        "select",
        "whitespace",
        "select_disabled",
        "disabled_duplicate",
        "changed_options",
        "changed_duplicate",
        "selected_disabled",
        "option_label",
        "duplicate",
        "select_broken",
    }:
        other = "<option>Yes</option>" if case == "duplicate" else ""
        disabled = "disabled" if case == "select_disabled" else ""
        onchange = 'onchange="this.selectedIndex=1"' if case == "select_broken" else ""
        if case == "selected_disabled":
            onchange = 'onchange="this.selectedOptions[0].disabled=true"'
        control = f'<select id="q" required {onchange}><option value="" disabled>Choose</option><option>No</option><option {disabled}>Yes</option><option disabled>Maybe</option><optgroup disabled><option>Unavailable</option></optgroup>{other}</select>'
        if case == "whitespace":
            control = control.replace(">Yes</option>", "> Yes </option>")
        if case == "disabled_duplicate":
            control = control.replace(
                "<option >Yes</option>",
                '<option disabled value="disabled">Yes</option><option value="enabled">Yes</option>',
            )
        elif case == "option_label":
            control = control.replace(
                "<option >Yes</option>",
                '<option label="Yes" value="visible">Different underlying text</option>',
            )
    elif case == "multiple":
        control = '<select id="q" multiple><option>Yes</option><option>No</option></select>'
    else:
        kind = (
            "number"
            if case in {"number", "negative", "not_numeric"}
            else "date"
            if case == "date"
            else "color"
            if case == "unsupported"
            else "text"
        )
        answer = (
            "3"
            if case == "number"
            else "-1"
            if case == "negative"
            else "2026-10-04"
            if case == "date"
            else "Yes"
        )
        constraint = (
            'min="0"'
            if kind == "number"
            else 'pattern="[0-9]+"'
            if case == "pattern"
            else 'maxlength="2"'
            if case == "maxlength"
            else ""
        )
        invalid = (
            "oninput=\"this.setCustomValidity('Invalid')\"" if case == "custom_invalid" else ""
        )
        control = f'<input id="q" type="{kind}" required {constraint} {invalid}>'
        if case == "duplicate_id":
            control += '<input id="q">'
    profile.answers["question:exact answer"] = answer
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(
            '<dialog open><span id="label">Exact answer</span>'
            + control.replace('id="q"', 'id="q" aria-labelledby="label"')
            + '<input disabled><input aria-disabled="true"></dialog>'
        )
        fields = form_questions(page)
        assert len(fields) == (2 if case == "duplicate_id" else 1)
        if case in {"select", "whitespace", "number", "date", "disabled_duplicate", "option_label"}:
            fill_questions(page, profile)
            assert page.locator("#q").input_value().strip() == (
                "enabled"
                if case == "disabled_duplicate"
                else "visible"
                if case == "option_label"
                else answer
            )
            if case == "disabled_duplicate":
                assert not page.locator("#q").evaluate("el => el.selectedOptions[0].disabled")
        else:
            with pytest.raises(ValueError):
                fill_questions(
                    page,
                    profile,
                    progress=(
                        (
                            lambda *_: page.locator("#q").evaluate(
                                "el => el.options[2].disabled=true"
                            )
                        )
                        if case == "changed_options"
                        else (
                            lambda *_: page.locator("#q").evaluate(
                                "el => el.add(new Option('Yes'))"
                            )
                        )
                        if case == "changed_duplicate"
                        else None
                    ),
                )
        if case == "select":
            assert fields[0]["choices"] == ["No", "Yes"]


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    ["invalid_exact", "inconsistent_native", "already_selected", "zero_box_wrapper", "native_role"],
)
def test_checkbox_rejects_invalid_exact_answers_and_inconsistent_widget_state(profile, case):
    profile.answers["question:consent"] = "Maybe" if case == "invalid_exact" else "Yes"
    html = (
        '<label>Consent<input id="q" type="checkbox" required></label>'
        if case == "invalid_exact"
        else '<div role="checkbox" aria-label="Consent" aria-checked="true">Consent<input id="q" type="checkbox" hidden></div>'
    )
    if case == "already_selected":
        html = html.replace('type="checkbox"', 'type="checkbox" checked')
    elif case == "zero_box_wrapper":
        html = '<div role="checkbox" style="width:0;height:0;overflow:visible" aria-label="Consent" aria-checked="false" onclick="this.setAttribute(\'aria-checked\',\'true\');this.querySelector(\'input\').checked=true">Consent<input id="q" type="checkbox"></div>'
    elif case == "native_role":
        html = '<label>Consent<input id="q" type="checkbox" role="checkbox"></label>'
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content("<dialog open>" + html + "</dialog>")
        if case in {"already_selected", "zero_box_wrapper", "native_role"}:
            fill_questions(page, profile)
            assert page.locator("#q").is_checked()
        else:
            with pytest.raises(ValueError):
                fill_questions(page, profile)


@pytest.mark.browser
def test_unlabelled_optional_checkbox_remains_unchecked_without_blocking_contact_fields(profile):
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(
            '<dialog open><input type="checkbox" id="optional"><label>Email<input id="email" required></label></dialog>'
        )
        fill_questions(page, profile)
        assert not page.locator("#optional").is_checked()
        assert page.locator("#email").input_value() == profile.email
