"""Private immutable submission materials and provider confirmation evidence."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Page

from .documents import validate_manifest
from .models import Job, Profile, State
from .store import Store

MAX_SCREENSHOT_BYTES = 20_000_000


def capture_confirmation(page: Page, folder: Path | None) -> dict[str, Any]:
    """A screenshot failure must never turn a confirmed send into an uncertain send."""
    if folder is None:
        return {}
    evidence: dict[str, Any] = {}
    try:
        parsed = urlsplit(page.url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Unsupported confirmation URL")
        evidence["url"] = page.url
        folder.mkdir(parents=True, exist_ok=True)
        content = page.screenshot(type="png", full_page=True, timeout=10000)
        if not content.startswith(b"\x89PNG\r\n\x1a\n") or len(content) > MAX_SCREENSHOT_BYTES:
            raise ValueError("Unsupported screenshot")
        target = folder / "confirmation.png"
        if (
            target.exists()
            or target.is_symlink()
            or not target.resolve().is_relative_to(folder.resolve())
        ):
            raise ValueError("Unsupported evidence path")
        target.write_bytes(content)
        return {
            "url": page.url,
            "captured_at": datetime.now(UTC).isoformat(),
            "name": target.name,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    except Exception as exc:
        return {**evidence, "capture_error": type(exc).__name__}


class SubmissionRecords:
    def __init__(self, store: Store, data: Path):
        self.store, self.data = store, data

    def folder(self, app_id: int, attempt: int) -> Path:
        if app_id < 1 or attempt < 1:
            raise ValueError("Invalid submission identifier")
        folder = self.data / "submissions" / str(app_id) / str(attempt)
        if folder.is_symlink() or not folder.resolve().is_relative_to(self.data.resolve()):
            raise ValueError("Unsupported submission folder")
        return folder

    def begin(
        self,
        app_id: int,
        attempt: int,
        profile: Profile,
        revision: int,
        job: Job,
        manifest: dict[str, Any],
        answers: dict[str, str],
    ) -> None:
        original = self.data / "documents" / str(app_id)
        validate_manifest(manifest, original, revision)
        archive = self.folder(app_id, attempt) / "documents"
        if not archive.resolve().is_relative_to(self.data.resolve()):
            raise ValueError("Unsupported document archive")
        archive.mkdir(parents=True, exist_ok=True)
        for item in manifest["files"].values():
            content = (original / item["name"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("Document changed while archiving")
            destination = archive / item["name"]
            if destination.exists() or destination.is_symlink():
                raise ValueError("Archived materials cannot be replaced")
            destination.write_bytes(content)
        snapshot = {
            "job": job.model_dump(),
            "profile_revision": revision,
            "candidate": {
                key: getattr(profile, key)
                for key in (
                    "name",
                    "email",
                    "phone",
                    "location",
                    "links",
                    "summary",
                    "sponsorship_required",
                )
            },
            "manifest": manifest,
            "selected_evidence": [
                item.model_dump()
                for item in profile.evidence
                if item.id in manifest.get("evidence_ids", [])
            ],
            "provided_answers": [
                {"id": q.id, "label": q.label, "answer": answers[q.id]}
                for q in job.questions
                if q.id in answers
            ],
        }
        with self.store.connect(True) as db:
            if not db.execute(
                "SELECT 1 FROM attempts t JOIN applications a ON a.id=t.application_id WHERE t.id=? AND a.id=? AND a.state=? AND t.status='held'",
                (attempt, app_id, State.SUBMITTING),
            ).fetchone():
                raise ValueError("Only a reserved submission can be archived")
            db.execute(
                "INSERT INTO submission_records(attempt_id,application_id,created,snapshot) VALUES(?,?,?,?)",
                (attempt, app_id, datetime.now(UTC).isoformat(), json.dumps(snapshot)),
            )

    def observe(self, app_id: int, attempt: int, fields: list[dict[str, Any]]) -> None:
        with self.store.connect(True) as db:
            row = db.execute(
                "SELECT r.fields FROM submission_records r JOIN attempts t ON t.id=r.attempt_id JOIN applications a ON a.id=r.application_id WHERE r.attempt_id=? AND r.application_id=? AND a.state='submitting' AND t.status='held'",
                (attempt, app_id),
            ).fetchone()
            if not row:
                raise ValueError("This submission no longer accepts form observations")
            observations = {
                (item.get("step"), item["label"], item["type"]): item for item in json.loads(row[0])
            }
            for field in fields:
                if field["type"] == "radio":
                    if not field.get("checked"):
                        continue
                    label, value = field.get("group") or field["label"], field["label"]
                else:
                    label, value = field["label"], field.get("value", "")
                observations[(field.get("step"), label, field["type"])] = {
                    "step": field.get("step"),
                    "label": label,
                    "type": field["type"],
                    "value": value,
                    "checked": field.get("checked")
                    if field["type"] in {"checkbox", "radio"}
                    else None,
                    "observed_at": datetime.now(UTC).isoformat(),
                }
            db.execute(
                "UPDATE submission_records SET fields=? WHERE attempt_id=?",
                (json.dumps(list(observations.values())), attempt),
            )

    def confirmation(self, app_id: int, attempt: int, evidence: dict[str, Any]) -> None:
        with self.store.connect(True) as db:
            if not db.execute(
                "SELECT 1 FROM submission_records r JOIN attempts t ON t.id=r.attempt_id WHERE r.attempt_id=? AND r.application_id=? AND t.status='confirmed'",
                (attempt, app_id),
            ).fetchone():
                raise ValueError("Confirmation evidence requires a confirmed receipt")
            db.execute(
                "UPDATE submission_records SET confirmation=? WHERE attempt_id=?",
                (json.dumps(evidence), attempt),
            )

    def read(self, app_id: int, before: int | None = None) -> dict[str, Any]:
        application = self.store.application(app_id)
        with self.store.connect() as db:
            attempts = []
            for row in db.execute(
                "SELECT t.*,r.created AS recorded_at,r.sent_at,r.confirmed_at,r.snapshot,r.fields,r.confirmation FROM attempts t LEFT JOIN submission_records r ON r.attempt_id=t.id WHERE t.application_id=? ORDER BY t.id DESC",
                (app_id,),
            ):
                item = dict(row)
                for key in ("snapshot", "fields", "confirmation"):
                    item[key] = json.loads(item[key]) if item[key] else None
                attempts.append(item)
            dates = dict(
                db.execute(
                    "SELECT MIN(created) AS imported_at,MAX(created) AS last_activity_at,COUNT(*) AS event_count,MAX(CASE WHEN kind='materials_prepared' THEN created END) AS prepared_at,MAX(CASE WHEN (kind='submission_finished' AND detail='submitted') OR kind='manual_receipt' THEN created END) AS submitted_at FROM events WHERE application_id=?",
                    (app_id,),
                ).fetchone()
            )
            events = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM events WHERE application_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT 201",
                    (app_id, before, before),
                )
            ]
        return {
            "application": application,
            "dates": dates,
            "attempts": attempts,
            "events": events[:200],
            "next_event": events[199]["id"] if len(events) > 200 else None,
        }

    def artifact(self, app_id: int, attempt: int, key: str) -> Path:
        record = next(
            (item for item in self.read(app_id)["attempts"] if item["id"] == attempt), None
        )
        if not record or not record["snapshot"]:
            raise KeyError(attempt)
        if key == "confirmation":
            item = record["confirmation"] or {}
            if record["status"] != "confirmed" or item.get("name") != "confirmation.png":
                raise KeyError(key)
            path = self.folder(app_id, attempt) / "confirmation.png"
            maximum = MAX_SCREENSHOT_BYTES
        else:
            item = record["snapshot"]["manifest"]["files"].get(key)
            if not item or Path(item["name"]).name != item["name"]:
                raise KeyError(key)
            path = self.folder(app_id, attempt) / "documents" / item["name"]
            maximum = 10_000_000
        if path.is_symlink() or not path.resolve().is_relative_to(self.data.resolve()):
            raise ValueError("Unsupported artifact path")
        try:
            if (
                path.stat().st_size > maximum
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]
            ):
                raise ValueError("The submission artifact no longer matches its recorded hash")
        except OSError as exc:
            raise KeyError(key) from exc
        return path
