"""Production React archive tabs on desktop/mobile, using only fictional local data."""

import pytest
from playwright.sync_api import expect, sync_playwright
from test_browser import TOKEN, server

from applicator.api import create_app
from applicator.browser import browser_options


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_packaged_archive_keeps_records_accessible_without_mutations(data, profile, job, width):
    app = create_app(data, TOKEN)
    store = app.state.store
    store.save_profile(profile)
    active_id, _ = store.add_job(job)
    archived = job.model_copy(
        update={
            "source_id": "archive",
            "title": "Archived Python Engineer",
            "url": "https://example.test/jobs/archive",
        },
        deep=True,
    )
    archive_id, _ = store.add_job(archived)
    store.reconcile(archive_id, "fixture:confirmed:archive")
    baseline = store.applications()
    mutations, errors, external = [], [], []
    with (
        server(app) as origin,
        sync_playwright() as p,
        p.chromium.launch(headless=True, **browser_options()) as browser,
    ):
        page = browser.new_page(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(type(error).__name__))
        page.on(
            "request",
            lambda request: mutations.append(request.method) if request.method != "GET" else None,
        )
        page.on(
            "request",
            lambda request: (
                external.append(request.url) if not request.url.startswith(origin) else None
            ),
        )
        page.goto(origin)
        page.get_by_label("Access token", exact=True).fill(TOKEN)
        page.get_by_role("button", name="Unlock workspace", exact=True).click()
        expect(page.locator("#notice")).to_have_text("Local workspace unlocked.", timeout=15000)
        page.get_by_role("navigation", name="Main navigation").get_by_role(
            "button", name="Applications", exact=True
        ).click()
        active = page.get_by_role("tabpanel", name="Active (1)")
        expect(active.get_by_text(job.title, exact=True)).to_be_visible()
        expect(active.get_by_text(archived.title, exact=True)).to_have_count(0)
        page.get_by_role("tab", name="Archive (1)").click()
        archive = page.get_by_role("tabpanel", name="Archive (1)")
        expect(archive.get_by_text(archived.title, exact=True)).to_be_visible()
        archive.get_by_role(
            "link", name=f"Full record for {archived.title} at {archived.company}"
        ).click()
        expect(page.get_by_role("heading", name=archived.title, exact=True)).to_be_visible(
            timeout=15000
        )
        expect(page.get_by_text("fixture:confirmed:archive", exact=False).first).to_be_visible()
        assert not mutations and not external and not errors
        assert (
            store.applications() == baseline and store.application(active_id)["state"] == "review"
        )
