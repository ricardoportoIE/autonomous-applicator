"""Packaged UI review/Trash journeys against a real isolated API, with no provider sends."""

import hashlib
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from test_browser import TOKEN, server

from applicator.api import create_app
from applicator.browser import browser_options
from applicator.models import Question
from applicator.question_adviser import question_key


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize(
    "requirement",
    [
        "Minimum 5 years of work experience with Python",
        "5+ years of commercial software development experience",
    ],
)
def test_review_decision_trash_restore_preserves_facts_and_artifacts(
    data, profile, job, width, requirement
):
    app = create_app(data, TOKEN)
    store, service = app.state.store, app.state.service
    profile.answers[
        question_key(
            Question(id="years", label="How many years of work experience do you have with Python?")
        )
    ] = "3"
    store.save_profile(profile)
    job.description += "\n" + requirement
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    original = store.application(app_id)
    errors, external = [], []
    with (
        server(app) as origin,
        sync_playwright() as p,
        p.chromium.launch(headless=True, **browser_options()) as browser,
    ):
        page = browser.new_page(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
        page.on("pageerror", lambda error: errors.append(type(error).__name__))

        def route(request):
            if request.request.url.startswith(origin + "/"):
                request.continue_()
            else:
                external.append(request.request.url)
                request.abort()

        page.route("**/*", route)
        page.goto(origin)
        page.get_by_label("Access token").fill(TOKEN)
        page.get_by_role("button", name="Unlock workspace").click()
        expect(page.get_by_text("Local workspace unlocked.")).to_be_visible()
        page.get_by_role("navigation", name="Main navigation").get_by_role(
            "button", name="Applications", exact=True
        ).click()
        page.get_by_role(
            "button", name="Open Backend Engineer at Example Employer", exact=True
        ).click()
        panel = page.locator("#application-detail")
        expect(
            panel.get_by_role("heading", name="Why this application needs review")
        ).to_be_visible()
        expect(
            panel.get_by_role("heading", name="Experience requirement needs your decision")
        ).to_be_visible()
        approval = panel.get_by_role("button", name="Approve this opportunity for the queue")
        expect(approval).to_be_disabled()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        if width == 1440:
            page.screenshot(
                path=str(Path(__file__).resolve().parents[1] / "tmp/review-management-desktop.png"),
                full_page=True,
            )
            panel.locator(".review-guidance").screenshot(
                path=str(Path(__file__).resolve().parents[1] / "tmp/review-decision.png")
            )
        panel.get_by_role(
            "checkbox",
            name="I have reviewed this opportunity and want to apply with my truthful profile.",
        ).check()
        approval.click()
        expect(panel.locator(".detail-meta").get_by_text("Ready", exact=True)).to_be_visible()
        assert store.profile()[0] == profile
        assert store.application(app_id)["manifest"] == original["manifest"]
        assert store.daily_usage().attempts == 0
        page.get_by_role(
            "button", name="Move Backend Engineer at Example Employer to Trash", exact=True
        ).click()
        dialog = page.get_by_role("dialog", name="Move opportunity to Trash")
        dialog.get_by_label("Reason for removal (optional)").fill("Not my current priority")
        dialog.get_by_role("button", name="Move to Trash", exact=True).click()
        expect(dialog).not_to_be_visible()
        page.get_by_role("tab", name="Trash (1)", exact=True).click()
        trash = page.get_by_role("tabpanel", name="Trash (1)")
        expect(trash.get_by_text("Backend Engineer", exact=True)).to_be_visible()
        assert store.application(app_id)["trashed"] and not service.queue_pending()
        expect(
            trash.get_by_role("link", name="Full record for Backend Engineer at Example Employer")
        ).to_have_attribute("href", f"#/applications/{app_id}")
        trash.get_by_role(
            "button", name="Restore Backend Engineer at Example Employer", exact=True
        ).click()
        expect(page.get_by_role("tab", name="Trash (0)", exact=True)).to_be_visible()
        page.get_by_role("tab", name="Active (1)", exact=True).click()
        expect(
            page.get_by_role("tabpanel", name="Active (1)").get_by_text(
                "Queued for preparation", exact=True
            )
        ).to_be_visible()
        assert not store.application(app_id)["trashed"] and service.queue_pending()
        assert store.profile()[0] == profile and store.daily_usage().attempts == 0
        for item in original["manifest"]["files"].values():
            assert (
                hashlib.sha256(
                    (data / "documents" / str(app_id) / item["name"]).read_bytes()
                ).hexdigest()
                == item["sha256"]
            )
        assert not errors and not external
