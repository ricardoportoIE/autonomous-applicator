"""Local server, explicit profile import and interactive browser sign-in."""

import argparse
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from playwright.sync_api import Error, sync_playwright

from .api import create_app, local_token
from .browser import LinkedInBrowser
from .models import Profile
from .store import Store


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Local evidence-led application workbench")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    sub.add_parser("browser-login")
    importer = sub.add_parser("import-profile")
    importer.add_argument("path", type=Path)
    args = parser.parse_args()
    data = Path(os.getenv("APPLICATOR_DATA_DIR", "data")).resolve()
    store = Store(data / "applicator.sqlite3")
    if args.command == "import-profile":
        revision = store.save_profile(
            Profile.model_validate_json(args.path.read_text(encoding="utf-8"))
        )
        print(
            f"Imported local profile revision {revision}. Review and confirm it in the dashboard."
        )
    elif args.command == "browser-login":
        profile, _ = store.profile()
        confirmed = False
        try:
            with (
                sync_playwright() as playwright,
                LinkedInBrowser(data, profile).context(playwright, headless=False) as context,
            ):
                page = context.new_page()
                page.goto("https://www.linkedin.com/login")
                input(
                    "Sign in and complete verification in the browser, then press Enter here to save the local session: "
                )
                confirmed = True
        except Error as exc:
            # Closing the visible window before pressing Enter is normal. Suppress only
            # this cleanup error after manual confirmation; preserve all setup failures.
            if (
                not confirmed
                or "Target page, context or browser has been closed" not in exc.message
            ):
                raise
        print("Sign-in step finished. The dedicated local browser profile has been retained.")
    else:
        host = os.getenv("APPLICATOR_HOST", "127.0.0.1")
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("This server must bind to loopback")
        token = local_token(data)
        print(f"Local dashboard access token: {token}")
        uvicorn.run(
            create_app(data, token, worker=True),
            host=host,
            port=int(os.getenv("APPLICATOR_PORT", "8765")),
            proxy_headers=False,
        )


if __name__ == "__main__":
    main()
