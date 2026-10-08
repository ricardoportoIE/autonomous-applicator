"""Capture only the company-executor controls using an isolated fictional workspace."""

import secrets
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from capture_screenshots import candidate, local_server
from playwright.sync_api import expect, sync_playwright

from applicator.api import create_app
from applicator.browser import browser_options
from applicator.models import Settings


def main() -> None:
    output = Path(__file__).resolve().parents[1] / "docs/assets/company-executors.png"
    with TemporaryDirectory(prefix="applicator-company-demo-") as folder:
        token = secrets.token_urlsafe(32)
        app = create_app(Path(folder), token)
        app.state.store.save_profile(candidate())
        app.state.store.set_settings(Settings(external_applications_enabled=True))
        with local_server(app) as origin, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, **browser_options())
            page = browser.new_page(viewport={"width": 1440, "height": 1180})
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
            page.get_by_role("button", name="Agent settings", exact=True).click()
            expect(page.get_by_role("heading", name="Application executors")).to_be_visible()
            page.locator("#settings-form").screenshot(path=output)
            assert not errors and not external
            assert not app.state.store.settings().automation_enabled
            assert not app.state.store.applications()
            browser.close()
    print("Captured company executor settings with fictional data; no provider or model requests.")


if __name__ == "__main__":
    main()
