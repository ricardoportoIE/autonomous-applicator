"""Real DOM regressions for bounded traversal, provider identity and verified receipts."""

import base64
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from playwright.sync_api import Page, sync_playwright
from test_application_dialog import SCREENING, resume_html
from test_browser import LINKEDIN_HTML, server
from test_contact_discovery import modern_profile
from test_contact_photos import URL, example_photo
from test_manual_networking import network_fixture

from applicator.browser import (
    FixtureBrowser,
    LinkedInBrowser,
    ReviewRequired,
    application_dialog,
    browser_options,
    capture_member_photo,
    fill_questions,
    member_action_scope,
    upload_resume,
)
from applicator.documents import generate
from applicator.models import Settings
from applicator.photos import stored_photo

DETAILS = {
    "name": "Example Recruiter",
    "role": "Technical Recruiter",
    "location": "Dublin, Ireland",
}


@pytest.mark.parametrize("installed", [False, True])
def test_automatic_browser_selection_is_portable_without_an_explicit_channel(
    monkeypatch, installed
):
    monkeypatch.delenv("APPLICATOR_BROWSER_CHANNEL", raising=False)
    inspected = []
    edge = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")

    def installed_browser(path):
        inspected.append(path)
        return path == edge and installed

    monkeypatch.setattr(Path, "is_file", installed_browser)
    assert browser_options() == ({"channel": "msedge"} if installed else {})
    assert inspected == [edge]


@pytest.mark.parametrize("headless", [True, False])
def test_dedicated_browser_launch_keeps_sessions_local_and_downloads_disabled(
    data, profile, headless
):
    playwright = Mock()
    browser = LinkedInBrowser(data, profile)
    result = browser.context(playwright, headless=headless)
    assert result is playwright.chromium.launch_persistent_context.return_value
    playwright.chromium.launch_persistent_context.assert_called_once_with(
        str(data / "browser" / "linkedin"),
        headless=headless,
        accept_downloads=False,
        viewport={"width": 1365, "height": 900},
        **browser_options(),
    )


@pytest.mark.browser
@pytest.mark.parametrize("case", ["depth", "multiple_headings"])
def test_primary_controls_and_portraits_cannot_escape_the_identity_boundary(data, case):
    if case == "depth":
        html = (
            "<main>"
            + "<div>" * 14
            + "<h2>Example Recruiter</h2>"
            + "</div>" * 14
            + "<button>Connect</button></main>"
        )
    else:
        html = "<main><article><div><h2>Example Recruiter</h2></div><h2>Another member</h2><p>Technical Recruiter</p><p>Dublin, Ireland</p><button>Connect</button></article></main>"
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        page.goto(URL)
        with pytest.raises(ReviewRequired, match="primary member"):
            member_action_scope(page, DETAILS)
        assert not capture_member_photo(page, data, URL, DETAILS)
        assert stored_photo(data, URL) is None


@pytest.mark.browser
def test_incomplete_portrait_is_waited_for_before_it_is_cached(data, monkeypatch):
    encoded = base64.b64encode(example_photo()).decode()
    html = modern_profile().replace(
        "</article>",
        '<img id="portrait" style="width:152px;height:152px" src="https://www.linkedin.com/__fixture/pending.png"></article>',
    )
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        page.route("**/pending.png", lambda route: None)
        page.goto(URL, wait_until="domcontentloaded")
        assert not page.locator("#portrait").evaluate("el=>el.complete")
        waited = []
        original_wait = Page.wait_for_function

        def complete_when_observed(page, expression, **kwargs):
            waited.append(expression)
            # Release the fixture image only when the adapter waits for it. No
            # wall-clock race can hide the incomplete-image branch on slow CI.
            page.locator("#portrait").evaluate(
                "(image, src)=>image.src=src", f"data:image/png;base64,{encoded}"
            )
            return original_wait(page, expression, **kwargs)

        monkeypatch.setattr(Page, "wait_for_function", complete_when_observed)
        assert capture_member_photo(page, data, URL, DETAILS)
        assert waited == ["image => image.complete"]
        assert stored_photo(data, URL).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.browser
@pytest.mark.parametrize("case", ["section_depth", "ambiguous_selection"])
def test_unsupported_resume_widget_stops_before_any_submission(tmp_path, case):
    document = tmp_path / "Approved_CV.pdf"
    document.write_bytes(b"%PDF-1.4 fixture")
    html = resume_html("custom")
    if case == "section_depth":
        html = html.replace(
            '<button onclick="document.querySelector',
            "<div>" * 10 + '<button onclick="document.querySelector',
            1,
        ).replace("Upload resume</button>", "Upload resume</button>" + "</div>" * 10, 1)
    else:
        html = html.replace("card.setAttribute('role','radio');", "")
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(html)
        with pytest.raises(ValueError, match="unsupported|ambiguous"):
            upload_resume(page, application_dialog(page), document)
        assert page.get_by_role("button", name="Next", exact=True).is_visible()
        assert page.locator("#picker").evaluate("el=>el.files.length") == (
            0 if case == "section_depth" else 1
        )


@pytest.mark.browser
def test_custom_radio_must_update_the_native_input_as_well_as_its_visual_state(profile):
    profile.answers["question:are you legally authorised to work here?"] = "No"
    html = SCREENING.replace("other.querySelector('input').checked=other===card;", "")
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(html)
        with pytest.raises(ValueError, match="approved radio answer was not selected"):
            fill_questions(page, profile)
        assert page.locator("#yes").is_checked()
        assert not page.locator("#no").is_checked()
        assert page.locator('[role="radio"]').nth(1).get_attribute("aria-checked") == "true"


@pytest.mark.browser
@pytest.mark.parametrize("case", ["resume_observation", "ten_steps"])
def test_easy_apply_records_uploads_progress_and_never_sends_after_the_step_budget(
    data, profile, job, tmp_path, monkeypatch, case
):
    job.source, job.source_id, job.url, job.description = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
        "Python FastAPI PostgreSQL",
    )
    generate(profile, job, ["python"], tmp_path, 1)
    html = LINKEDIN_HTML
    if case == "resume_observation":
        widget = (
            resume_html("custom")
            .split("<dialog open>")[1]
            .split("<button>Next</button></dialog>")[0]
        )
        picker_script = resume_html("custom").split("</dialog>")[1]
        html = html.replace('<label>CV<input type="file" aria-label="CV"></label>', widget)
        html = (
            html.replace(
                '<button id="next">',
                '<label>Follow Example Employer to stay up to date<input type="checkbox" id="follow" checked></label><button id="next">',
            )
            + picker_script
        )
    else:
        html = html.replace(
            '<section role="dialog" hidden>',
            '<section role="dialog" hidden><h2 id="stage">Stage 0</h2>',
        )
        html = html.replace(
            "document.querySelector('#next').hidden=true;document.querySelector('#submit').hidden=false;",
            "const field=document.querySelector('input:not([type=file])');field.id='step-'+(++window.formStep);document.querySelector('#stage').textContent='Stage '+window.formStep;",
        ).replace("<script>", "<script>window.formStep=0;", 1)
    actions = []

    def context(self, playwright, **kwargs):
        result = playwright.chromium.launch_persistent_context(
            str(data / "bounded-browser"), headless=True, **browser_options()
        )
        result.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        result.expose_binding("record", lambda source, action: actions.append(action))
        result.add_init_script(
            "document.addEventListener('click',e=>{if(e.target.id==='submit')window.record({action:'submit',follow:document.querySelector('#follow')?.checked});if(e.target.id==='next')window.record({action:'next'});},true)"
        )
        return result

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    adapter = LinkedInBrowser(data, profile)
    stages, observations = [], []
    adapter.progress = lambda stage, detail: stages.append(stage)
    adapter.observe_fields = lambda fields: observations.extend(fields)
    if case == "ten_steps":
        with pytest.raises(ReviewRequired, match="ten-step limit"):
            adapter.submit(job, {}, tmp_path)
        assert actions == [{"action": "next"}] * 10
        assert stages.count("advancing_form") == 10
        assert "submitting" not in stages
    else:
        assert adapter.submit(job, {}, tmp_path) == "linkedin:123:confirmed"
        assert actions[-1] == {"action": "submit", "follow": False}
        uploads = [field for field in observations if field["type"] == "file"]
        assert len(uploads) == 2 and [field["step"] for field in uploads] == [1, 2]
        assert all(field["value"].endswith("_CV.pdf") for field in uploads)
        assert stages[-1] == "awaiting_confirmation"


@pytest.mark.browser
def test_contact_discovery_rejects_a_redirect_to_another_member(data, profile, monkeypatch):
    def context(self, playwright, **kwargs):
        result = playwright.chromium.launch_persistent_context(
            str(data / "discovery-browser"), headless=True, **browser_options()
        )

        def route(request):
            url = request.request.url
            if "/search/" in url:
                request.fulfill(
                    content_type="text/html",
                    body=f'<main><a href="{URL}">Example Recruiter</a></main>',
                )
            elif url == URL:
                request.fulfill(
                    status=302, headers={"Location": "https://www.linkedin.com/in/different/"}
                )
            else:
                request.fulfill(content_type="text/html", body=modern_profile(overlay="different"))

        result.route("**/*", route)
        return result

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    with pytest.raises(ReviewRequired, match="identity changed"):
        LinkedInBrowser(data, profile).contacts("Ireland")
    assert stored_photo(data, URL) is None


@pytest.mark.browser
@pytest.mark.parametrize("case", ["redirect", "receipt"])
def test_fixture_provider_cannot_confirm_an_untrusted_origin_or_receipt(job, tmp_path, case):
    (tmp_path / "Approved_CV.pdf").write_bytes(b"%PDF fixture")
    app = FastAPI()

    @app.get("/form")
    def form():
        return HTMLResponse(
            '<label>CV<input type="file"></label><button onclick="document.querySelector(\'#receipt\').textContent=\'not confirmed\'">Submit application</button><p id="receipt"></p>'
        )

    with server(app) as origin:

        @app.get("/redirect")
        def redirect():
            return RedirectResponse(origin.replace("127.0.0.1", "localhost") + "/form")

        job.url = origin + ("/redirect" if case == "redirect" else "/form")
        with pytest.raises(
            ValueError,
            match="Unexpected fixture redirect"
            if case == "redirect"
            else "Missing fixture receipt",
        ):
            FixtureBrowser().submit(job, {}, tmp_path)


@pytest.mark.browser
@pytest.mark.parametrize(
    "case", ["menu_baseline", "missing_menu", "identity_race", "revoked_before_send"]
)
def test_networking_rechecks_target_scope_and_menu_controls_at_the_action_boundary(
    data, monkeypatch, case
):

    store, network = network_fixture(data)
    html = modern_profile()
    controls = "<button id=\"connect\" onclick=\"document.querySelector('#dialog').hidden=false;console.log('action:connect')\">Connect</button>"
    if case in {"menu_baseline", "missing_menu"}:
        controls = '<button onclick="document.querySelector(\'#menu\').hidden=false">More</button><div id="menu" role="menu" hidden><button role="menuitem" onclick="document.querySelector(\'#dialog\').hidden=false;console.log(\'action:connect\')">Connect</button></div>'
        if case == "missing_menu":
            controls = controls.replace('role="menuitem"', 'role="menuitem" hidden')
    html = html.replace("</article>", controls + "</article>")
    if case == "menu_baseline":
        html = html.replace("</aside>", "<button>Connect</button></aside>")
    html += "<div id=\"dialog\" role=\"dialog\" hidden><button onclick=\"console.log('action:send');document.querySelector('#dialog').hidden=true;document.querySelector('article').insertAdjacentHTML('beforeend','<button>Pending</button>')\">Send without a note</button></div>"
    actions, pages = [], []

    def context(self, playwright, **kwargs):
        result = playwright.chromium.launch_persistent_context(
            str(data / "network-boundary"), headless=True, **browser_options()
        )
        result.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))

        def observe(page):
            pages.append(page)
            page.on(
                "console",
                lambda message: (
                    actions.append(message.text) if message.text.startswith("action:") else None
                ),
            )

        result.on("page", observe)
        return result

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    progress = network.progress

    def race(connection_id, run_id, detail):
        progress(connection_id, run_id, detail)
        if case == "identity_race" and detail.startswith("Opening Connect"):
            pages[-1].goto("https://www.linkedin.com/in/other/")
        elif case == "revoked_before_send" and detail.startswith("Sending this invitation"):
            store.set_settings(Settings())

    monkeypatch.setattr(network, "progress", race)
    if case == "menu_baseline":
        assert network.send(1, manual=True) == "linkedin:invitation-pending"
        assert actions == ["action:connect", "action:send"]
    else:
        with pytest.raises(
            ValueError,
            match={
                "missing_menu": "Connect is unavailable",
                "identity_race": "identity changed",
                "revoked_before_send": "revoked before sending",
            }[case],
        ):
            network.send(1, manual=True)
        assert actions == (["action:connect"] if case == "revoked_before_send" else [])
        assert network.status(1)["state"] == (
            "uncertain" if case == "revoked_before_send" else "failed"
        )
    assert network.status(2)["state"] == "queued"
