import pytest

from applicator.browser import LinkedInBrowser, browser_options


@pytest.mark.browser
@pytest.mark.parametrize(
    ("role", "location", "count"),
    [
        ("Technical Recruiter", "Dublin, Ireland", 1),
        ("Engineer", "Dublin, Ireland", 0),
        ("Recruiter", "Brazil", 0),
    ],
)
def test_recruiter_discovery_filters_role_and_europe(
    data, profile, monkeypatch, role, location, count
):
    html = f"""<main><h1>Example Recruiter</h1><a href="https://www.linkedin.com/in/example/">Member</a><div class="text-body-medium break-words">{role}</div><span class="text-body-small inline t-black--light break-words">{location}</span></main>"""

    def fixture_context(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )
        context.route(
            "**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html)
        )
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    contacts = LinkedInBrowser(data, profile).contacts("Ireland")
    assert len(contacts) == count
    if count:
        assert contacts[0]["name"] == "Example Recruiter"
