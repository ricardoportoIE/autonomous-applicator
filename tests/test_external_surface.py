"""Native company surfaces remain isolated from LinkedIn dialogues and other pages."""

import pytest
from test_external_applications import chromium as chromium_fixture

from applicator.browser import (
    application_dialog,
    capture_form_diagnostic,
    field_locator,
    form_questions,
    native_form_surface,
)

chromium = chromium_fixture


@pytest.mark.parametrize("html", ["", "<form></form><form></form>", "<div></div>"])
def test_native_surface_requires_a_unique_form(chromium, html):
    page = chromium.new_page()
    page.set_content(html)
    with (
        pytest.raises(ValueError, match="native application form"),
        native_form_surface(page, page.locator("form,div")),
    ):
        pytest.fail("An invalid surface must not be entered")
    page.close()


def test_form_scope_does_not_leak_across_pages_or_exception_cleanup(chromium, data):
    company = chromium.new_page()
    linkedin = chromium.new_page()
    company.set_content("<form><label>Company question<input id=company></label></form>")
    linkedin.set_content(
        "<div role=dialog><label>LinkedIn question<input id=linkedin></label></div>"
    )
    with pytest.raises(RuntimeError), native_form_surface(company, company.locator("form")):
        assert form_questions(company)[0]["label"] == "Company question"
        assert form_questions(linkedin)[0]["label"] == "LinkedIn question"
        assert application_dialog(linkedin).get_attribute("role") == "dialog"
        assert capture_form_diagnostic(linkedin, data, "123", 1, "answering_questions").get("path")
        raise RuntimeError("Cleanup after a company-form error")
    assert application_dialog(linkedin).get_attribute("role") == "dialog"
    company.close()
    linkedin.close()


@pytest.mark.parametrize(
    "html",
    [
        "<form><select></select></form>",
        "<form><label>Choice<select><option>A</option></select></label><label>Choice<select><option>B</option></select></label></form>",
    ],
)
def test_idless_select_fallback_rejects_missing_or_duplicate_labels(chromium, html):
    page = chromium.new_page()
    page.set_content(html)
    with pytest.raises(ValueError, match="Ambiguous form control"):
        field_locator(page.locator("form"), {"id": "", "tag": "select", "label": "Choice"})
    page.close()
