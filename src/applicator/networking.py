"""Explicit networking queue; no public profile modification capability."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as BrowserError
from playwright.sync_api import TimeoutError as BrowserTimeout
from playwright.sync_api import sync_playwright

from .browser import LinkedInBrowser, ensure_linkedin, member_action_scope, member_details
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
            columns = {row[1] for row in db.execute("PRAGMA table_info(connections)")}
            for name, definition in (
                ("run_id", "TEXT"),
                ("run_status", "TEXT NOT NULL DEFAULT 'idle'"),
                ("run_message", "TEXT NOT NULL DEFAULT ''"),
                ("updated_at", "TEXT"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE connections ADD COLUMN {name} {definition}")
            db.execute(
                "UPDATE connections SET run_status='uncertain', "
                "run_message='Interrupted invitation. Check LinkedIn before trying again.' "
                "WHERE state='sending'"
            )
            db.execute(
                "UPDATE connections SET run_status='uncertain',run_message='An earlier invitation has an unconfirmed outcome. Check LinkedIn before trying again.' WHERE state='uncertain' AND run_status='idle'"
            )
            db.execute(
                "UPDATE connections SET run_status='done',run_message='Previously recorded invitation confirmation.' WHERE state='sent' AND run_status='idle'"
            )
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

    def status(self, connection_id: int) -> dict[str, Any]:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM connections WHERE id=?", (connection_id,)).fetchone()
            if row is None:
                raise KeyError(connection_id)
            return dict(row)

    def progress(self, connection_id: int, run_id: str, message: str) -> None:
        with self.store.connect(True) as db:
            changed = db.execute(
                "UPDATE connections SET run_status='running',run_message=?,updated_at=? "
                "WHERE id=? AND run_id=? AND state='sending'",
                (message, datetime.now(UTC).isoformat(), connection_id, run_id),
            ).rowcount
            if changed != 1:
                raise ValueError("The invitation run changed. Review its current status.")

    def reserve(self, connection_id: int, *, manual: bool = False) -> dict[str, Any]:
        with self.store.connect(True) as db:
            from .models import Settings

            settings = Settings.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='settings'").fetchone()[0]
            )
            row = db.execute("SELECT * FROM connections WHERE id=?", (connection_id,)).fetchone()
            count = db.execute(
                "SELECT COUNT(*) FROM connections WHERE day=?", (day_key(),)
            ).fetchone()[0]
            if not settings.linkedin_authorised:
                raise ValueError("Configure the declared LinkedIn authorisation scope first")
            if not manual and (not settings.automation_enabled or not settings.connections_enabled):
                raise ValueError("Networking is paused or LinkedIn scope is not configured")
            if not row or row["state"] != "queued" or count >= settings.daily_connection_limit:
                raise ValueError("Connection is not queued or the daily limit has been reached")
            run_id = uuid.uuid4().hex
            db.execute(
                "UPDATE connections SET state='sending',day=?,run_id=?,run_status='started',"
                "run_message='Starting the selected invitation.',updated_at=? WHERE id=?",
                (day_key(), run_id, datetime.now(UTC).isoformat(), connection_id),
            )
            self.store.event(
                db, "connection_reserved", "An invitation may be sent; do not retry blindly."
            )
            return {**dict(row), "run_id": run_id}

    def finish(self, connection_id: int, receipt: str | None, *, run_id: str | None = None) -> None:
        with self.store.connect(True) as db:
            if run_id is not None:
                row = db.execute(
                    "SELECT state,run_id FROM connections WHERE id=?", (connection_id,)
                ).fetchone()
                if row is None or row["state"] != "sending" or row["run_id"] != run_id:
                    raise ValueError("The invitation run changed. Review its current status.")
            db.execute(
                "UPDATE connections SET state=?,receipt=?,run_status=?,run_message=?,updated_at=? WHERE id=?",
                (
                    "sent" if receipt else "uncertain",
                    receipt,
                    "done" if receipt else "uncertain",
                    "Invitation confirmed as pending on LinkedIn."
                    if receipt
                    else "The invitation may have been sent. Check LinkedIn before trying again.",
                    datetime.now(UTC).isoformat(),
                    connection_id,
                ),
            )
            self.store.event(db, "connection_finished", "sent" if receipt else "uncertain")

    def send(self, connection_id: int, *, manual: bool = False) -> str:
        profile = None
        if not manual:
            profile, _ = self.store.profile()
            if not profile.confirmed:
                raise ValueError("Confirm the candidate profile first")
        row = self.reserve(connection_id, manual=manual)
        attempted = False
        try:
            self.progress(connection_id, row["run_id"], "Opening the dedicated LinkedIn browser.")
            with (
                sync_playwright() as playwright,
                LinkedInBrowser(self.data, profile).context(
                    playwright, headless=not manual
                ) as context,
            ):
                page = context.new_page()
                self.progress(
                    connection_id, row["run_id"], "Opening the selected member's profile."
                )
                page.goto(row["url"], wait_until="domcontentloaded")
                ensure_linkedin(page)
                if target_url(page.url) != row["url"]:
                    raise ValueError("Member identity changed; review the target")
                self.progress(
                    connection_id,
                    row["run_id"],
                    "Checking the member's identity, role and location.",
                )
                details = member_details(page)
                if details["name"] != row["name"]:
                    raise ValueError("Member identity changed; review the target")
                if (
                    details["role"].casefold() != row["role"].casefold()
                    or details["location"].casefold() != row["location"].casefold()
                ):
                    raise ValueError("Member role or location did not match the reviewed target")
                card = member_action_scope(page, details)
                button = card.get_by_role(
                    "button", name=re.compile(r"^Connect$|^Invite .+ to connect$")
                ).filter(visible=True)
                if button.count() == 0:
                    button = card.get_by_role(
                        "link", name=re.compile(r"^Connect$|^Invite .+ to connect$")
                    ).filter(visible=True)
                if button.count() == 0:
                    more = card.get_by_role(
                        "button", name=re.compile(r"^More(?: options| actions(?: for .+)?)?$")
                    ).filter(visible=True)
                    if more.count() == 1:
                        popup_connect = (
                            page.get_by_role("button", name="Connect", exact=True)
                            .or_(page.get_by_role("link", name="Connect", exact=True))
                            .filter(visible=True)
                        )
                        baseline = popup_connect.count()
                        more.click(timeout=10000)
                        button = (
                            page.get_by_role("menu")
                            .get_by_role(
                                "menuitem", name=re.compile(r"^Connect$|^Invite .+ to connect$")
                            )
                            .filter(visible=True)
                        )
                        if baseline == 0:
                            button = button.or_(popup_connect)
                        try:
                            button.first.wait_for(state="visible", timeout=10000)
                        except BrowserTimeout as exc:
                            raise ValueError(
                                "Connect is unavailable in this member's menu. Review the profile and any existing connection or pending invitation."
                            ) from exc
                if button.count() != 1:
                    raise ValueError("Connect action is ambiguous, unavailable or already pending")
                self.progress(
                    connection_id, row["run_id"], "Opening Connect. No follow action is used."
                )
                if not self.store.settings().linkedin_authorised:
                    raise ValueError("The declared LinkedIn scope was revoked before connecting.")
                ensure_linkedin(page)
                if target_url(page.url) != row["url"]:
                    raise ValueError("Member identity changed before connecting; review the target")
                attempted = True
                button.click(timeout=10000)
                send = page.get_by_role("dialog").get_by_role(
                    "button", name="Send without a note", exact=True
                )
                send.wait_for(state="visible", timeout=10000)
                self.progress(
                    connection_id, row["run_id"], "Sending this invitation without a note."
                )
                if not self.store.settings().linkedin_authorised:
                    raise ValueError("The declared LinkedIn scope was revoked before sending.")
                ensure_linkedin(page)
                send.click(timeout=10000)
                self.progress(
                    connection_id, row["run_id"], "Waiting for LinkedIn to confirm the invitation."
                )
                card.get_by_role(
                    "button", name=re.compile(r"^Pending$|^Invitation pending")
                ).first.wait_for(timeout=10000)
                receipt = "linkedin:invitation-pending"
        except Exception as exc:
            if attempted:
                self.finish(connection_id, None, run_id=row["run_id"])
            else:
                detail = (
                    str(exc)[:500]
                    if isinstance(exc, ValueError)
                    else (
                        "The browser could not complete this step. Check login or verification using browser-login."
                        if isinstance(exc, BrowserError)
                        else "The invitation stopped before sending. Review the browser session."
                    )
                )
                with self.store.connect(True) as db:
                    db.execute(
                        "UPDATE connections SET state='failed',run_status='failed',run_message=?,updated_at=? "
                        "WHERE id=? AND run_id=? AND state='sending'",
                        (detail, datetime.now(UTC).isoformat(), connection_id, row["run_id"]),
                    )
                    self.store.event(db, "connection_failed", detail)
            raise
        self.finish(connection_id, receipt, run_id=row["run_id"])
        return receipt
