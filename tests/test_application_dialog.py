"""Native LinkedIn dialogues and grounded contact details without real submissions."""

import json

import pytest
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import sync_playwright
from test_browser import LINKEDIN_HTML

from applicator.browser import (
    LinkedInBrowser,
    ReviewRequired,
    application_dialog,
    browser_options,
    contact_phone_answers,
    fill_questions,
    form_questions,
    upload_resume,
)
from applicator.documents import generate


def contact_fields():
    return [
        {"label": "Phone country code", "choices": ["Ireland (+353)", "United Kingdom (+44)"]},
        {"label": "Mobile phone number", "choices": []},
    ]


@pytest.mark.parametrize(
    "case",
    [
        "unique",
        "formatted",
        "national_approved",
        "national_unknown",
        "ambiguous",
        "explicit_ambiguous",
        "mismatch",
        "unavailable",
        "unsupported_choices",
        "missing_phone",
        "two_phones",
        "two_countries",
        "oversized",
        "extension",
        "unmatched",
        "longest_prefix",
        "no_country",
    ],
)
def test_phone_components_use_approved_facts_and_available_choices(profile, case):
    fields = contact_fields()
    profile.phone = "+3535550100"
    expected = {"Phone country code": "Ireland (+353)", "Mobile phone number": "5550100"}
    failures = {
        "national_unknown",
        "ambiguous",
        "mismatch",
        "unavailable",
        "unsupported_choices",
        "missing_phone",
        "two_phones",
        "two_countries",
        "oversized",
        "extension",
        "unmatched",
    }
    if case == "formatted":
        profile.phone = "+353 (55) 501-00"
    elif case in {"national_approved", "national_unknown"}:
        profile.phone = "555 0100"
        if case == "national_approved":
            profile.answers["question:phone country code"] = "Ireland (+353)"
            expected["Mobile phone number"] = profile.phone
    elif case in {"ambiguous", "explicit_ambiguous"}:
        profile.phone = "+15550100000"
        fields[0]["choices"] = ["United States (+1)", "Canada (+1)"]
        if case == "explicit_ambiguous":
            profile.answers["question:phone country code"] = "Canada (+1)"
            expected = {"Phone country code": "Canada (+1)", "Mobile phone number": "5550100000"}
    elif case == "mismatch":
        profile.answers["question:phone country code"] = "United Kingdom (+44)"
    elif case == "unavailable":
        profile.answers["question:phone country code"] = "France (+33)"
    elif case == "unsupported_choices":
        fields[0]["choices"] = ["Ireland"]
    elif case == "missing_phone":
        profile.phone = ""
    elif case == "two_phones":
        fields.append({"label": "Phone number", "choices": []})
    elif case == "two_countries":
        fields.append(fields[0])
    elif case == "oversized":
        profile.phone = "+353" + "5" * 15
    elif case == "extension":
        profile.phone += " ext 12"
    elif case == "unmatched":
        profile.phone = "+495550100"
    elif case == "longest_prefix":
        profile.phone = "+12425550100"
        fields[0]["choices"] = ["Bahamas (+1242)", "United States (+1)"]
        expected = {"Phone country code": "Bahamas (+1242)", "Mobile phone number": "5550100"}
    elif case == "no_country":
        fields = []
        expected = {}
    if case in failures:
        with pytest.raises(ValueError):
            contact_phone_answers(fields, profile)
    else:
        assert contact_phone_answers(fields, profile) == expected


@pytest.mark.browser
@pytest.mark.parametrize("kind", ["native", "aria", "delayed"])
def test_contact_form_supports_native_dialogs_required_markers_and_delayed_rendering(profile, kind):
    profile.phone = "+3535550100"
    form = """<label>Email address*<select id="email" required><option>wrong@example.test</option><option>alex@example.test</option></select></label>
    <label for="country">Phone country code*</label><select id="country" required><option>United Kingdom (+44)</option><option>Ireland (+353)</option></select>
    <label for="phone">Mobile phone number<span aria-hidden="true">*</span></label><input id="phone" type="tel" required value="unapproved">
    <label for="literal">Optional literal*</label><input id="literal">
    <button>Next</button>"""
    opening, closing = (
        ('<section role="dialog">', "</section>")
        if kind == "aria"
        else ("<dialog open>", "</dialog>")
    )
    outside = '<label>Email<input id="email" value="outside@example.test"></label><section role="dialog" hidden><input aria-label="Hidden salary" required></section>'
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        if kind == "delayed":
            page.set_content(
                outside
                + opening
                + "<button>Close</button>"
                + closing
                + '<script>setTimeout(()=>document.querySelector("dialog").innerHTML='
                + json.dumps(form)
                + ",200)</script>"
            )
        else:
            page.set_content(outside + opening + form + closing)
        questions = form_questions(page)
        assert [q["label"] for q in questions] == [
            "Email address",
            "Phone country code",
            "Mobile phone number",
            "Optional literal*",
        ]
        fill_questions(page, profile)
        dialog = application_dialog(page)
        assert dialog.locator("#email").input_value() == profile.email
        assert dialog.locator("#country").input_value() == "Ireland (+353)"
        assert dialog.locator("#phone").input_value() == "5550100"
        assert page.locator("body > label input").input_value() == "outside@example.test"


@pytest.mark.browser
def test_multiple_visible_dialogs_cannot_select_an_arbitrary_application():
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(
            '<dialog open><input id="one"></dialog><section role="dialog"><input id="two"></section>'
        )
        with pytest.raises(BrowserError, match="strict mode"):
            form_questions(page)


@pytest.mark.browser
def test_unknown_prefilled_question_in_native_dialog_still_requires_approval(profile):
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(
            '<dialog open><label>Expected salary*<input id="salary" required value="100000"></label></dialog>'
        )
        with pytest.raises(ValueError, match="Approve an exact answer for: Expected salary"):
            fill_questions(page, profile)


@pytest.mark.browser
def test_native_dialog_full_submission_against_an_intercepted_provider(
    data, profile, job, tmp_path, monkeypatch
):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    job.description = "Python FastAPI PostgreSQL"
    profile.phone = "+3535550100"
    generate(profile, job, ["python"], tmp_path, 1)
    html = LINKEDIN_HTML.replace('<section role="dialog" hidden>', "<dialog>").replace(
        "</section>", "</dialog>"
    )
    html = html.replace(
        "document.querySelector('section').hidden=false",
        "document.querySelector('dialog').showModal()",
    )
    html = html.replace(
        "document.querySelector('section').hidden=true", "document.querySelector('dialog').close()"
    )
    html = html.replace(
        '<label>Email<input id="email" required></label>',
        '<label>Email address*<input id="email" required></label><label>Phone country code*<select id="country" required><option>United Kingdom (+44)</option><option>Ireland (+353)</option></select></label><label>Mobile phone number*<input id="phone" type="tel" required></label>',
    )
    submitted = []

    def fixture_context(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        context.expose_binding("recordSubmission", lambda source, record: submitted.append(record))
        context.add_init_script(
            "document.addEventListener('click',event=>{if(event.target.id==='submit') window.recordSubmission({email:document.querySelector('#email').value,country:document.querySelector('#country').value,phone:document.querySelector('#phone').value,files:document.querySelector('input[type=file]').files.length});},true)"
        )
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    adapter = LinkedInBrowser(data, profile)
    stages = []
    adapter.progress = lambda stage, detail: stages.append((stage, detail))
    assert adapter.submit(job, {}, tmp_path) == "linkedin:123:confirmed"
    assert [stage for stage, _ in stages] == [
        "opening_opportunity",
        "verifying_opportunity",
        "opening_application",
        "uploading_documents",
        "answering_questions",
        "uploading_documents",
        "advancing_form",
        "uploading_documents",
        "answering_questions",
        "uploading_documents",
        "submitting",
        "awaiting_confirmation",
    ]
    assert submitted == [
        {"email": profile.email, "country": "Ireland (+353)", "phone": "5550100", "files": 1}
    ]


SCREENING = """<dialog open><section><p>Are you legally authorised to work here?*</p>
<fieldset role="radiogroup"><div role="radio" aria-label="Are you legally authorised to work here?" aria-checked="true">
<label><input style="display:none" type="radio" name="legal" id="yes" checked></label>Yes</div>
<div role="radio" aria-label="Are you legally authorised to work here?" aria-checked="false">
<label><input style="display:none" type="radio" name="legal" id="no"></label>No</div></fieldset></section>
<button>Next</button></dialog><script>
document.querySelectorAll('[role=radio]').forEach(card=>card.onclick=()=>{
document.querySelectorAll('[role=radio]').forEach(other=>{other.setAttribute('aria-checked',String(other===card));other.querySelector('input').checked=other===card;});});
</script>"""


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "approved",
        "prefilled",
        "invalid_choice",
        "two_labels",
        "inconsistent_cards",
        "broken_selection",
    ],
)
def test_custom_screening_radios_require_exact_approved_answers(profile, case):
    html = SCREENING
    if case == "two_labels":
        html = html.replace("<section>", "<section><p>Another question</p>")
    if case == "inconsistent_cards":
        html = html.replace(
            'aria-label="Are you legally authorised to work here?"', 'aria-label="Unrelated"', 1
        )
    if case == "broken_selection":
        html = html.split("<script>")[0]
    if case != "prefilled":
        profile.answers["question:are you legally authorised to work here?"] = (
            "Maybe" if case == "invalid_choice" else "No"
        )
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(html)
        if case in {"approved", "prefilled", "invalid_choice", "broken_selection"}:
            questions = form_questions(page)
            assert [q["label"] for q in questions] == ["Yes", "No"]
            assert all(q["required"] and q["group_choices"] == ["Yes", "No"] for q in questions)
        if case == "approved":
            fill_questions(page, profile)
            assert page.locator("#no").is_checked()
            assert not page.locator("#yes").is_checked()
            assert page.get_by_role("radio").nth(1).get_attribute("aria-checked") == "true"
        else:
            with pytest.raises(ValueError):
                fill_questions(page, profile)
            assert page.locator("#yes").is_checked()


@pytest.mark.browser
@pytest.mark.parametrize(
    "case", ["unchecked", "checked", "required", "aria_required", "mixed", "unlabelled_required"]
)
def test_optional_preferences_do_not_create_implicit_consent(profile, case):
    checked = "checked" if case == "checked" else ""
    required = "required" if case in {"required", "unlabelled_required"} else ""
    aria_required = 'aria-required="true"' if case == "aria_required" else ""
    aria_checked = "mixed" if case == "mixed" else "false"
    label = "" if case == "unlabelled_required" else 'aria-label="Mark job as a top choice"'
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(
            f'<dialog open><div role="checkbox" {label} {aria_required} aria-checked="{aria_checked}"><input id="preference" type="checkbox" {checked} {required}></div><button>Next</button></dialog>'
        )
        if case == "unchecked":
            fill_questions(page, profile)
            assert not page.locator("#preference").is_checked()
        else:
            with pytest.raises(ValueError):
                fill_questions(page, profile)


def resume_html(case):
    group = '<fieldset role="radiogroup">' if case == "labelled" else "<div>"
    close = "</fieldset>" if case == "labelled" else "</div>"
    extra = '<label>Cover letter<input type="file"></label>' if case == "extra_upload" else ""
    extra += (
        '<label>Legal eligibility<input id="uploaded"></label>' if case == "duplicate_id" else ""
    )
    legal = (
        '<fieldset aria-label="Legal eligibility"><div role="radio"><label><input id="legal" type="radio">Yes</label></div></fieldset>'
        if case == "legal_in_resume"
        else ""
    )
    second = "<button>Upload resume</button>" if case == "two_buttons" else ""
    heading = "Documents" if case == "missing_heading" else "Resume*"
    native_checked = "false" if case == "not_selected" else "true"
    return f"""<dialog open><section><h3>{heading}</h3>{group}<div role="radio" aria-checked="false"><label><input type="radio" id="old" name="cv">Previous.pdf</label></div><div id="new"></div>{close}{legal}
    <button onclick="document.querySelector('#picker').click()">Upload resume</button>{second}</section>{extra}<button>Next</button></dialog>
    <input id="picker" type="file" hidden><script>
    document.querySelector('#picker').onchange=e=>{{
      const card=document.createElement('div');card.setAttribute('role','radio');card.setAttribute('aria-checked','true');
      const label=document.createElement('label');const input=document.createElement('input');input.id='uploaded';input.type='radio';input.name='cv';input.checked={native_checked};
      label.append(input,document.createTextNode(e.target.files[0].name));card.append(label);document.querySelector('#new').append(card);
    }};
    </script>"""


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "custom",
        "labelled",
        "not_selected",
        "extra_upload",
        "legal_in_resume",
        "duplicate_id",
        "two_buttons",
        "missing_heading",
        "missing_file",
        "legacy",
    ],
)
def test_resume_chooser_proves_the_job_cv_selection_and_does_not_skip_legal_fields(
    tmp_path, profile, case
):
    document = tmp_path / "Approved_CV.pdf"
    document.write_bytes(b"%PDF-1.4 fixture")
    if case == "missing_file":
        document.unlink()
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        html = resume_html(case)
        if case == "legacy":
            html = '<dialog open><label>CV<input type="file"></label><button>Next</button></dialog>'
        page.set_content(html)
        dialog = application_dialog(page)
        if case == "legacy":
            assert upload_resume(page, dialog, document) is None
        elif case in {"custom", "labelled"}:
            ids = upload_resume(page, dialog, document)
            assert ids == {"old", "uploaded"}
            assert page.locator("#uploaded").is_checked()
            assert page.locator("#picker").evaluate("el=>el.files[0].name") == document.name
            fill_questions(page, profile, resume_field_ids=ids)
        else:
            with pytest.raises(ValueError):
                upload_resume(page, dialog, document)


@pytest.mark.browser
def test_failed_next_validation_stops_without_duplicate_document_upload(
    data, profile, job, tmp_path, monkeypatch
):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    job.description = "Python FastAPI PostgreSQL"
    generate(profile, job, ["python"], tmp_path, 1)
    html = LINKEDIN_HTML.replace(
        "document.querySelector('#next').onclick=()=>{document.querySelector('#next').hidden=true;document.querySelector('#submit').hidden=false;};",
        "document.querySelector('#next').onclick=()=>{};",
    )
    events = []

    def fixture_context(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "stalled-browser"), headless=True, **browser_options()
        )
        context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        context.expose_binding("recordAction", lambda source, action: events.append(action))
        context.add_init_script(
            "document.addEventListener('change',event=>{if(event.target.type==='file')window.recordAction('upload')});document.addEventListener('click',event=>{if(event.target.id==='next')window.recordAction('next')});"
        )
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    with pytest.raises(ReviewRequired, match="did not advance"):
        LinkedInBrowser(data, profile).submit(job, {}, tmp_path)
    assert events == ["upload", "next"]
