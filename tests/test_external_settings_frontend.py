"""Packaged React settings expose both executors without enabling the global worker."""

import pytest
from playwright.sync_api import expect
from test_frontend import dashboard as dashboard  # noqa: F401
from test_react_frontend import check_accessibility


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_company_executor_controls_save_and_fit_mobile(dashboard, width):
    page, app, _ = dashboard
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": width, "height": 1000})
    page.get_by_role("button", name="Agent settings", exact=True).click()
    toggle = page.get_by_label(
        "Enable company-site applications and include external Apply opportunities in LinkedIn search"
    )
    expect(toggle).not_to_be_checked()
    toggle.check()
    page.get_by_label("External application hosts, comma-separated", exact=True).fill(
        "jobs.lever.co, careers.example.com"
    )
    page.get_by_role("button", name="Save agent settings", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Agent settings saved.")).to_be_visible()
    saved = app.state.store.settings()
    assert saved.external_applications_enabled and saved.external_allowed_hosts == [
        "jobs.lever.co",
        "careers.example.com",
    ]
    assert not saved.automation_enabled
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    check_accessibility(page)
    assert not errors
