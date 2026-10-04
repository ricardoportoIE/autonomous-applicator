"""Production-bundle regressions for route, session and obsolete-response ownership."""

import pytest
from playwright.sync_api import expect
from test_browser import TOKEN
from test_frontend import dashboard as dashboard
from test_react_frontend import check_accessibility


@pytest.mark.browser
@pytest.mark.parametrize(
    "label,route",
    [
        ("Overview", "overview"),
        ("Applications", "applications"),
        ("Candidate profile", "profile"),
        ("Networking", "networking"),
        ("Agent settings", "settings"),
        ("Activity log", "activity"),
    ],
)
def test_reload_restores_each_saved_workspace_area(dashboard, label, route):
    page, app, _ = dashboard
    page.get_by_role("button", name=label, exact=True).click()
    assert page.url.endswith("#" + route)
    page.reload()
    expect(page.get_by_role("heading", level=1)).to_have_text(label)
    expect(page.locator("#workspace")).to_be_visible()
    assert app.state.store.daily_usage().attempts == 0
    check_accessibility(page)


@pytest.mark.browser
@pytest.mark.parametrize("failure", [False, True])
def test_old_record_response_does_not_replace_a_newer_view_or_notice(dashboard, failure):
    page, app, origin = dashboard
    app_id = app.state.store.applications()[0]["id"]
    held = []
    page.route("**/api/applications/*/record", lambda route: held.append(route))
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("link", name="Full record for Backend Engineer at Example Employer").click()
    expect(page.get_by_text("Loading application record…", exact=True)).to_be_visible()
    assert len(held) == 1
    page.get_by_role("button", name="Agent settings", exact=True).click()
    if failure:
        held[0].fulfill(status=404, json={"detail": "Obsolete record error"})
    else:
        response = page.request.get(
            origin + f"/api/applications/{app_id}/record",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        held[0].fulfill(status=200, json=response.json())
    expect(page.locator("#workspace")).not_to_be_disabled()
    expect(page.get_by_role("heading", level=1)).to_have_text("Agent settings")
    expect(page.locator("#notice")).not_to_contain_text("Obsolete record error")
    assert app.state.store.daily_usage().attempts == 0


@pytest.mark.browser
def test_focus_anchor_does_not_cancel_record_and_refresh_is_read_only(dashboard):
    page, app, origin = dashboard
    app_id = app.state.store.applications()[0]["id"]
    record = page.request.get(
        origin + f"/api/applications/{app_id}/record",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ).json()
    held = []
    page.route("**/api/applications/*/record", lambda route: held.append(route))
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("link", name="Full record for Backend Engineer at Example Employer").click()
    expect(page.get_by_text("Loading application record…", exact=True)).to_be_visible()
    page.locator(".brand").click()
    assert page.url.endswith("#main-content")
    held[0].fulfill(status=200, json=record)
    expect(page.get_by_role("button", name="Refresh record", exact=True)).to_be_visible()
    page.unroute("**/api/applications/*/record")
    methods = []
    page.on("request", lambda request: methods.append(request.method))
    page.get_by_role("button", name="Refresh record", exact=True).click()
    expect(page.get_by_role("heading", name="Submission history", exact=True)).to_be_visible()
    assert methods and set(methods) == {"GET"}
    assert app.state.store.daily_usage().attempts == 0
    check_accessibility(page)


@pytest.mark.browser
def test_blocked_session_storage_keeps_local_login_and_lock_operational(dashboard):
    page, _, _ = dashboard
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    page.add_init_script(
        "for (const method of ['getItem','setItem','removeItem']) "
        "Storage.prototype[method] = () => { throw new DOMException('Blocked', 'SecurityError'); };"
    )
    page.reload()
    expect(page.get_by_role("button", name="Unlock workspace")).to_be_visible()
    page.get_by_label("Access token", exact=True).fill(TOKEN)
    page.get_by_role("button", name="Unlock workspace").click()
    expect(page.locator("#notice")).to_contain_text("Browser storage is unavailable")
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    expect(page.get_by_text("Alex Example", exact=True)).to_be_visible()
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    expect(page.get_by_role("button", name="Unlock workspace")).to_be_visible()
    expect(page.get_by_text("Alex Example", exact=True)).to_have_count(0)
