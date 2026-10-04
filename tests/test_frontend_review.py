"""Production-bundle regressions for route, session and obsolete-response ownership."""

import pytest
from playwright.sync_api import expect
from test_browser import TOKEN
from test_frontend import dashboard as dashboard
from test_react_frontend import check_accessibility

from applicator.models import Settings, State


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


@pytest.mark.browser
@pytest.mark.parametrize("operation", ["prepare", "not-sent"])
def test_slow_operation_completion_is_observed_without_repeating_the_command(dashboard, operation):
    page, app, _ = dashboard
    store = app.state.store
    row = store.applications()[0]
    if operation == "not-sent":
        store.set_settings(Settings(automation_enabled=True))
        attempt = store.reserve(row["id"], row["revision"])
        store.finish(row["id"], attempt, None)
        page.reload()
    page.get_by_role("button", name="Applications", exact=True).click()
    page.get_by_role("button", name="Open Backend Engineer at Example Employer", exact=True).click()
    endpoint = f"/api/applications/{row['id']}/{operation}"
    # Delay delivery to the controller after the real local response. The browser
    # keeps rendering and polling whilst the one command remains in flight.
    page.evaluate(
        "endpoint => { const original = window.fetch; window.fetch = async (...args) => {"
        "const response = await original(...args);"
        "if (args[0] === endpoint) await new Promise(resolve => setTimeout(resolve, 6000));"
        "return response; }; }",
        endpoint,
    )
    commands = []
    page.on(
        "request",
        lambda request: (
            commands.append(request.url)
            if request.method == "POST" and request.url.endswith(endpoint)
            else None
        ),
    )
    if operation == "prepare":
        page.get_by_role("button", name="Prepare documents", exact=True).click()
        notice = "Documents prepared from approved evidence."
    else:
        page.get_by_role("tab", name="Activity & outcome", exact=True).click()
        page.get_by_label(
            "I checked the provider and this application was not sent", exact=True
        ).check()
        page.get_by_role("button", name="Confirm application was not sent", exact=True).click()
        notice = "Confirmed as not sent. Capacity released; prepare again manually before retrying."
    expect(page.locator("#workspace")).to_have_attribute("aria-busy", "true")
    expect(page.locator("#notice")).to_have_text(notice)
    expect(page.locator("#workspace")).not_to_have_attribute("aria-busy", "true")
    assert len(commands) == 1
    assert store.daily_usage().used == 0
    if operation == "not-sent":
        assert store.daily_usage().held == 0
        assert store.application(row["id"])["state"] == State.REVIEW
    else:
        assert store.application(row["id"])["manifest"]["files"]
