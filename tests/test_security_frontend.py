"""Real Chromium verifies the private-fetch policy in the packaged dashboard."""

import pytest
from playwright.sync_api import expect
from test_frontend import dashboard as dashboard


@pytest.mark.browser
def test_private_mutation_never_follows_a_redirect_or_sends_cookies(dashboard):
    page, app, origin = dashboard
    before = app.state.store.profile()[1]
    page.context.add_cookies([{"name": "unrelated-session", "value": "fixture", "url": origin}])
    followed = []
    commands = []
    page.route("**/__test/redirect-target", lambda route: followed.append(route.request))

    def redirect(route):
        commands.append(route.request)
        route.fulfill(status=307, headers={"Location": origin + "/__test/redirect-target"})

    page.route("**/api/profile", redirect)
    page.get_by_role("button", name="Candidate profile", exact=True).click()
    page.get_by_role("button", name="Edit candidate profile", exact=True).click()
    page.get_by_label("Professional summary (approved wording)", exact=True).fill(
        "A fictional draft for review."
    )
    page.get_by_role("button", name="Save candidate profile", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Failed to fetch")
    assert len(commands) == 1
    assert "cookie" not in commands[0].all_headers()
    assert not followed
    assert app.state.store.profile()[1] == before
    assert app.state.store.daily_usage().attempts == 0
