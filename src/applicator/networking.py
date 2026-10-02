"""Explicit networking queue; no public profile modification capability."""

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from .browser import LinkedInBrowser, ensure_linkedin
from .store import Store, day_key

EUROPE = (
    "ireland",
    "united kingdom",
    "england",
    "scotland",
    "wales",
    "germany",
    "france",
    "netherlands",
    "belgium",
    "spain",
    "portugal",
    "italy",
    "sweden",
    "norway",
    "denmark",
    "finland",
    "poland",
    "austria",
    "switzerland",
    "luxembourg",
    "czechia",
)


def target_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.linkedin.com"
        or parsed.username
        or parsed.password
        or not re.fullmatch(r"/in/[a-zA-Z0-9%_-]+/?", parsed.path)
    ):
        raise ValueError("Expected a LinkedIn member profile URL")
    return "https://www.linkedin.com" + parsed.path.rstrip("/") + "/"


def european_location(location: str) -> bool:
    text = location.casefold()
    if re.search(
        r"\b(?:australia|new south wales|united states|canada|new zealand|papua new guinea)\b", text
    ):
        return False
    return any(re.search(rf"\b{re.escape(country)}\b", text) for country in EUROPE)


class Networking:
    def __init__(self, store: Store, data: Path):
        self.store, self.data = store, data
        with store.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS connections (
                id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                role TEXT NOT NULL, location TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
                day TEXT, receipt TEXT)""")
            db.execute("UPDATE connections SET state='uncertain' WHERE state='sending'")

    def add(self, url: str, name: str, role: str, location: str) -> None:
        url = target_url(url)
        if not any(term in role.casefold() for term in ("recruit", "talent", "hiring")):
            raise ValueError("Initial networking scope prioritises recruiters and hiring contacts")
        if not european_location(location):
            raise ValueError("Confirm a supported European location")
        with self.store.connect(True) as db:
            db.execute(
                "INSERT OR IGNORE INTO connections(url,name,role,location) VALUES(?,?,?,?)",
                (url, name, role, location),
            )
            self.store.event(
                db, "connection_queued", "Candidate selected a European hiring contact."
            )

    def list(self) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM connections ORDER BY id DESC")]

    def remaining(self) -> int:
        with self.store.connect() as db:
            count = int(
                db.execute("SELECT COUNT(*) FROM connections WHERE day=?", (day_key(),)).fetchone()[
                    0
                ]
            )
        return max(0, self.store.settings().daily_connection_limit - count)

    def reserve(self, connection_id: int) -> dict[str, Any]:
        with self.store.connect(True) as db:
            from .models import Settings

            settings = Settings.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='settings'").fetchone()[0]
            )
            row = db.execute("SELECT * FROM connections WHERE id=?", (connection_id,)).fetchone()
            count = db.execute(
                "SELECT COUNT(*) FROM connections WHERE day=?", (day_key(),)
            ).fetchone()[0]
            if (
                not settings.automation_enabled
                or not settings.connections_enabled
                or not settings.linkedin_authorised
            ):
                raise ValueError("Networking is paused or LinkedIn scope is not configured")
            if not row or row["state"] != "queued" or count >= settings.daily_connection_limit:
                raise ValueError("Connection is not queued or the daily limit has been reached")
            db.execute(
                "UPDATE connections SET state='sending',day=? WHERE id=?",
                (day_key(), connection_id),
            )
            self.store.event(
                db, "connection_reserved", "An invitation may be sent; do not retry blindly."
            )
            return dict(row)

    def finish(self, connection_id: int, receipt: str | None) -> None:
        with self.store.connect(True) as db:
            db.execute(
                "UPDATE connections SET state=?,receipt=? WHERE id=?",
                ("sent" if receipt else "uncertain", receipt, connection_id),
            )
            self.store.event(db, "connection_finished", "sent" if receipt else "uncertain")

    def send(self, connection_id: int) -> str:
        profile, _ = self.store.profile()
        if not profile.confirmed:
            raise ValueError("Confirm the candidate profile first")
        row = self.reserve(connection_id)
        try:
            with (
                sync_playwright() as playwright,
                LinkedInBrowser(self.data, profile).context(playwright) as context,
            ):
                page = context.new_page()
                page.goto(row["url"], wait_until="domcontentloaded")
                ensure_linkedin(page)
                main = page.get_by_role("main")
                if main.locator("h1").first.inner_text(timeout=10000).strip() != row["name"]:
                    raise ValueError("Member identity changed; review the target")
                text = main.inner_text(timeout=10000).casefold()
                if row["role"].casefold() not in text or row["location"].casefold() not in text:
                    raise ValueError("Member role or location did not match the reviewed target")
                button = main.get_by_role(
                    "button", name=re.compile(r"^Connect$|^Invite .+ to connect$")
                )
                if button.count() != 1:
                    raise ValueError("Connect action is ambiguous, unavailable or already pending")
                button.click()
                page.get_by_role("button", name="Send without a note", exact=True).click(
                    timeout=10000
                )
                main.get_by_role(
                    "button", name=re.compile(r"^Pending$|^Invitation pending")
                ).first.wait_for(timeout=10000)
                receipt = "linkedin:invitation-pending"
        except Exception:
            self.finish(connection_id, None)
            raise
        self.finish(connection_id, receipt)
        return receipt
