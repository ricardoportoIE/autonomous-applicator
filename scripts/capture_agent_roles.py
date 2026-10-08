"""Capture the packaged role monitor using a clearly labelled fictional journal."""

import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from capture_screenshots import candidate, local_server
from playwright.sync_api import expect, sync_playwright

from applicator.api import create_app
from applicator.browser import browser_options
from applicator.models import Job


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "docs/assets/specialised-agents.png"
    with TemporaryDirectory(prefix="applicator-agents-demo-") as folder:
        token = secrets.token_urlsafe(32)
        app = create_app(Path(folder), token)
        store = app.state.store
        store.save_profile(candidate())
        app_id, _ = store.add_job(
            Job(
                source="manual",
                source_id="role-demo",
                title="Backend Engineer",
                company="Example Employer",
                location="Dublin, Ireland",
                url="https://example.test/careers/backend",
                description="Build Python APIs using FastAPI and PostgreSQL.",
                requirements=["Python", "FastAPI", "PostgreSQL"],
            )
        )
        # This journal demonstrates presentation only; it never invokes an adapter.
        with app.state.service.operations.run("prepare", app_id) as operation:
            operation.progress(
                "retrying_application",
                "Bridge · Fictional demonstration: recovery 1/2 reopens the reviewed company form and reuses verified documents and approved answers.",
            )
            operation.result("review")
        with local_server(app) as origin, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, **browser_options())
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            errors: list[str] = []
            external: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def guard(route):
                if urlsplit(route.request.url).netloc != urlsplit(origin).netloc:
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", guard)
            page.goto(origin)
            page.get_by_label("Access token", exact=True).fill(token)
            page.get_by_role("button", name="Unlock workspace", exact=True).click()
            panel = page.get_by_role("region", name="One opportunity at a time")
            expect(panel.get_by_role("status")).to_contain_text("Agent: Bridge")
            expect(panel.get_by_role("status")).to_contain_text("Application #1")
            expect(panel.get_by_role("status")).to_contain_text("retrying application")
            panel.screenshot(path=output)
            assert not errors and not external
            assert not store.settings().automation_enabled
            assert store.daily_usage().attempts == 0
            browser.close()
    print("Captured fictional role monitor; no provider, submission or model requests.")


if __name__ == "__main__":
    main()
