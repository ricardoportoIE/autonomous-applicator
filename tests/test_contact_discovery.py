import pytest
from playwright.sync_api import sync_playwright

from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options, member_details


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


def modern_profile(
    *,
    depth=2,
    heading="Example Recruiter",
    role="Technical Recruiter",
    location="Dublin, Ireland",
    overlay="example",
    extra_location="",
    extra_heading="",
):
    name = "<div>" * depth + f'<h2 style="min-height:1px">{heading}</h2>' + "</div>" * depth
    return f"""<!doctype html><meta charset="utf-8"><main><article><div class="generated-classes-change-per-request">{name}{extra_heading}<p>{role}</p><p>Current employer</p><div><p>{location}</p>{extra_location}<p>·</p><p><a href="https://www.linkedin.com/in/{overlay}/overlay/contact-info/">Contact info</a></p></div></div></article><aside><h2>Recommended member</h2><p>Unrelated recruiter</p><p>Germany</p></aside></main>"""


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "modern",
        "deep_wrappers",
        "legacy",
        "missing_location",
        "wrong_overlay",
        "two_locations",
        "two_names",
        "empty_name",
        "oversized_role",
        "ambiguous_legacy",
        "incomplete_legacy",
        "not_profile_url",
    ],
)
def test_profile_identity_uses_a_complete_primary_card(data, case):
    html = modern_profile()
    if case == "deep_wrappers":
        html = modern_profile(depth=7)
    elif case == "missing_location":
        html = modern_profile(location="")
    elif case == "wrong_overlay":
        html = modern_profile(overlay="different-member")
    elif case == "two_locations":
        html = modern_profile(extra_location="<p>Berlin, Germany</p>")
    elif case == "two_names":
        html = modern_profile(extra_heading="<h2>Another person</h2>")
    elif case == "empty_name":
        html = modern_profile(heading=" ")
    elif case == "oversized_role":
        html = modern_profile(role="R" * 301)
    elif case in {"legacy", "ambiguous_legacy", "incomplete_legacy"}:
        role = (
            ""
            if case == "incomplete_legacy"
            else '<div class="text-body-medium break-words">Technical Recruiter</div>'
        )
        location = (
            '<span class="text-body-small inline t-black--light break-words">Dublin, Ireland</span>'
        )
        html = f"<main><h1>Example Recruiter</h1>{role}{location}{location if case == 'ambiguous_legacy' else ''}</main>"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        page.goto(
            "https://www.linkedin.com/feed/"
            if case == "not_profile_url"
            else "https://www.linkedin.com/in/example/"
        )
        if case in {"modern", "deep_wrappers", "legacy"}:
            assert member_details(page) == {
                "name": "Example Recruiter",
                "role": "Technical Recruiter",
                "location": "Dublin, Ireland",
            }
        else:
            match = (
                "Expected a LinkedIn member profile"
                if case == "not_profile_url"
                else "unavailable or the layout is unsupported"
            )
            with pytest.raises(ReviewRequired, match=match):
                member_details(page)
        browser.close()


@pytest.mark.browser
def test_discovery_deduplicates_valid_results_and_ignores_navigation_and_related_links(
    data, profile, monkeypatch
):
    visited = []
    search = """<nav><a href="https://www.linkedin.com/in/navigation/">Navigation</a></nav><main><a href="https://www.linkedin.com/in/suggestion/">Suggested contact</a><div role="listitem"><a href="https://www.linkedin.com/in/example/?tracking=1">Result</a><a href="https://www.linkedin.com/in/example/?tracking=2">Duplicate</a><a href="https://www.linkedin.com/in/mutual/">Mutual connection</a></div><div role="listitem"><a href="https://www.linkedin.com/in/example/?tracking=3">Repeated card</a></div><div role="listitem"><a href="https://www.linkedin.com/in/example/overlay/contact-info/">Overlay</a></div><div role="listitem"><a href="https://www.linkedin.com:8443/in/port/">Unapproved authority</a></div><div role="listitem"><a href="https://example.test/in/external/">External</a></div><div role="listitem"><a href="https://www.linkedin.com/in/second/">Second result</a></div></main>"""

    def fixture_context(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )

        def serve(route):
            url = route.request.url
            visited.append(url)
            body = (
                search
                if "/search/" in url
                else modern_profile(overlay="second" if "/second/" in url else "example")
            )
            route.fulfill(content_type="text/html", body=body)

        context.route("**/*", serve)
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    contacts = LinkedInBrowser(data, profile).contacts("Ireland", limit=2)
    assert [item["url"] for item in contacts] == [
        "https://www.linkedin.com/in/example/",
        "https://www.linkedin.com/in/second/",
    ]
    assert len(visited) == 3
    assert all(
        "navigation" not in url and "suggestion" not in url and "mutual" not in url
        for url in visited
    )


@pytest.mark.parametrize("limit", [0, 11])
def test_recruiter_discovery_rejects_unbounded_limits_before_launch(data, profile, limit):
    with pytest.raises(ValueError, match="between 1 and 10"):
        LinkedInBrowser(data, profile).contacts("Ireland", limit=limit)


@pytest.mark.browser
@pytest.mark.parametrize(("limit", "expected", "reviewed"), [(5, 5, 7), (10, 8, 10)])
def test_discovery_fills_saved_target_after_filters_and_skips_known_profiles(
    data, profile, monkeypatch, limit, expected, reviewed
):
    visited = []
    search = (
        "<main>"
        + "".join(
            f'<div role="listitem"><a href="https://www.linkedin.com/in/member-{index}/">Result</a></div>'
            for index in range(15)
        )
        + "</main>"
    )

    def fixture_context(self, playwright, **kwargs):
        context = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )

        def serve(route):
            url = route.request.url
            visited.append(url)
            if "/search/" in url:
                body = search
            else:
                slug = url.rstrip("/").rsplit("/", 1)[-1]
                body = modern_profile(
                    heading="Example Recruiter",
                    overlay=slug,
                    role="Engineer" if slug == "member-1" else "Technical Recruiter",
                    location="Brazil" if slug == "member-2" else "Ireland",
                )
            route.fulfill(content_type="text/html", body=body)

        context.route("**/*", serve)
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    contacts = LinkedInBrowser(data, profile).contacts(
        "Ireland", limit, exclude_urls={"https://www.linkedin.com/in/member-0/"}
    )
    assert len(contacts) == expected
    assert [item["url"] for item in contacts] == [
        f"https://www.linkedin.com/in/member-{index}/" for index in range(3, 3 + expected)
    ]
    assert len(visited) == reviewed + 1
    assert not any("/member-0/" in url for url in visited)
