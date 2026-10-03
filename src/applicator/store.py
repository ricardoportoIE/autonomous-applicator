"""SQLite journal with durable reservations and versioned candidate data."""

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .models import DailyUsage, Evidence, Job, Profile, Question, Settings, State


def day_key(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(ZoneInfo("Europe/London")).date().isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
                    job TEXT NOT NULL, state TEXT NOT NULL, evaluation TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 0, manifest TEXT NOT NULL DEFAULT '{}',
                    receipt TEXT, outcome TEXT, UNIQUE(source, source_id));
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL,
                    day TEXT NOT NULL, started TEXT NOT NULL, receipt TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, application_id INTEGER, kind TEXT NOT NULL,
                    detail TEXT NOT NULL, created TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_application ON events(application_id, id DESC);
                CREATE INDEX IF NOT EXISTS attempts_day ON attempts(day);
            """)
            db.execute(
                "INSERT OR IGNORE INTO config VALUES ('settings', ?)",
                (Settings().model_dump_json(),),
            )
            db.execute("INSERT OR IGNORE INTO config VALUES ('revision', '0')")

    @contextmanager
    def connect(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            if immediate:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def event(db: sqlite3.Connection, kind: str, detail: str, app_id: int | None = None) -> None:
        db.execute(
            "INSERT INTO events(application_id,kind,detail,created) VALUES(?,?,?,?)",
            (app_id, kind, detail, datetime.now(UTC).isoformat()),
        )

    def get_config(self, key: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
            return str(row[0]) if row else None

    def settings(self) -> Settings:
        return Settings.model_validate_json(self.get_config("settings") or "{}")

    def set_settings(self, settings: Settings) -> None:
        with self.connect(True) as db:
            previous = Settings.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='settings'").fetchone()[0]
            )
            if settings.ai_document_preparation and not previous.ai_document_preparation:
                count = db.execute(
                    "UPDATE applications SET state=?,evaluation='{}',revision=0,manifest='{}' "
                    "WHERE state IN (?,?) AND COALESCE(json_extract(manifest,'$.generation.method'),'') != ?",
                    (State.REVIEW, State.REVIEW, State.READY, "openai"),
                ).rowcount
                self.event(
                    db, "ai_preparation_enabled", f"{count} pending records require AI preparation."
                )
            db.execute(
                "UPDATE config SET value=? WHERE key='settings'", (settings.model_dump_json(),)
            )
            self.event(db, "settings_updated", settings.model_dump_json())

    def profile(self) -> tuple[Profile, int]:
        with self.connect() as db:
            row = db.execute("SELECT value FROM config WHERE key='profile'").fetchone()
            if not row:
                raise ValueError("Configure a candidate profile first")
            revision = int(
                db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0]
            )
            return Profile.model_validate_json(row[0]), revision

    def save_profile(self, profile: Profile, expected_revision: int | None = None) -> int:
        with self.connect(True) as db:
            return self._save_profile(db, profile, expected_revision)

    def _save_profile(
        self, db: sqlite3.Connection, profile: Profile, expected_revision: int | None = None
    ) -> int:
        profile = Profile.model_validate(profile.model_dump())
        current = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
        if expected_revision is not None and current != expected_revision:
            raise ValueError("Candidate profile changed. Reload before saving your edits.")
        revision = current + 1
        db.execute(
            "INSERT OR REPLACE INTO config VALUES ('profile', ?)", (profile.model_dump_json(),)
        )
        db.execute("UPDATE config SET value=? WHERE key='revision'", (str(revision),))
        db.execute(
            "UPDATE applications SET state=?, manifest='{}' WHERE state IN (?, ?, ?)",
            (State.REVIEW, State.READY, State.REVIEW, State.SKIPPED),
        )
        self.event(db, "profile_updated", f"Revision {revision}; previous materials invalidated.")
        return revision

    def edit_evidence(
        self, evidence: Evidence | None, evidence_id: str, *, create_only: bool = False
    ) -> int:
        with self.connect(True) as db:
            row = db.execute("SELECT value FROM config WHERE key='profile'").fetchone()
            if not row:
                raise ValueError("Configure a candidate profile first")
            profile = Profile.model_validate_json(row[0])
            exists = any(item.id == evidence_id for item in profile.evidence)
            if create_only and exists:
                raise ValueError("Evidence identifier already exists")
            if evidence is None and not exists:
                raise KeyError(evidence_id)
            profile.evidence = [item for item in profile.evidence if item.id != evidence_id]
            if evidence is not None:
                profile.evidence.append(evidence)
            return self._save_profile(db, profile)

    def add_job(self, job: Job) -> tuple[int, bool]:
        with self.connect(True) as db:
            row = db.execute(
                "SELECT id FROM applications WHERE source=? AND source_id=?",
                (job.source, job.source_id),
            ).fetchone()
            if row:
                return int(row[0]), False
            parsed = urlsplit(job.url)
            canonical = (parsed.hostname, parsed.path.rstrip("/"))
            for existing in db.execute("SELECT id,job FROM applications"):
                old = urlsplit(json.loads(existing["job"])["url"])
                if (old.hostname, old.path.rstrip("/")) == canonical:
                    return int(existing["id"]), False
            cursor = db.execute(
                "INSERT INTO applications(source,source_id,job,state) VALUES(?,?,?,?)",
                (job.source, job.source_id, job.model_dump_json(), State.REVIEW),
            )
            app_id = int(cursor.lastrowid or 0)
            self.event(db, "job_added", f"Imported {job.source} job.", app_id)
            return app_id, True

    def application(self, app_id: int) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
            if not row:
                raise KeyError(app_id)
            result = dict(row)
            for key in ("job", "evaluation", "manifest"):
                result[key] = json.loads(result[key])
            return result

    def update_job(self, app_id: int, job: Job) -> None:
        with self.connect(True) as db:
            row = db.execute("SELECT job,state FROM applications WHERE id=?", (app_id,)).fetchone()
            if not row:
                raise KeyError(app_id)
            old = Job.model_validate_json(row["job"])
            if row["state"] in {State.SUBMITTED, State.SUBMITTING, State.UNCERTAIN}:
                raise ValueError("Submitted or uncertain job records are immutable")
            if (
                (old.source, old.source_id) != (job.source, job.source_id)
                or urlsplit(old.url).path.rstrip("/") != urlsplit(job.url).path.rstrip("/")
                or urlsplit(old.url).netloc != urlsplit(job.url).netloc
            ):
                raise ValueError("Import a different job as a new opportunity")
            db.execute(
                "UPDATE applications SET job=?,state=?,evaluation='{}',revision=0,manifest='{}' WHERE id=?",
                (job.model_dump_json(), State.REVIEW, app_id),
            )
            self.event(
                db,
                "job_updated",
                "Job details changed; re-evaluation and fresh materials required.",
                app_id,
            )

    def applications(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM applications ORDER BY id DESC")]
        for row in rows:
            for key in ("job", "evaluation", "manifest"):
                row[key] = json.loads(row[key])
        return rows

    def daily_usage(self) -> DailyUsage:
        # Read the limit and reservations in one SQLite statement/snapshot.
        day = day_key()
        with self.connect() as db:
            row = db.execute(
                "SELECT value, (SELECT COUNT(*) FROM attempts WHERE day=?) AS used FROM config WHERE key='settings'",
                (day,),
            ).fetchone()
        limit = Settings.model_validate_json(row["value"]).daily_limit
        used = int(row["used"])
        return DailyUsage(day=day, used=used, limit=limit, remaining=max(0, limit - used))

    def prepare(
        self,
        app_id: int,
        revision: int,
        evaluation: str,
        state: State,
        manifest: dict[str, Any],
        *,
        expected_job: Job | None = None,
    ) -> None:
        with self.connect(True) as db:
            current_revision = int(
                db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0]
            )
            row = db.execute("SELECT state,job FROM applications WHERE id=?", (app_id,)).fetchone()
            if not row:
                raise KeyError(app_id)
            if current_revision != revision:
                raise ValueError("Profile changed while preparing materials")
            if expected_job is not None and json.loads(row[1]) != expected_job.model_dump(
                mode="json"
            ):
                raise ValueError("Opportunity changed while preparing materials")
            if row[0] in {State.SUBMITTED, State.SUBMITTING, State.UNCERTAIN}:
                raise ValueError("This application cannot be prepared in its current state")
            db.execute(
                "UPDATE applications SET revision=?,evaluation=?,state=?,manifest=? WHERE id=?",
                (revision, evaluation, state, json.dumps(manifest), app_id),
            )
            self.event(db, "materials_prepared", f"Profile revision {revision}.", app_id)

    def reserve(self, app_id: int, revision: int) -> int:
        with self.connect(True) as db:
            settings = Settings.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='settings'").fetchone()[0]
            )
            actual_revision = int(
                db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0]
            )
            row = db.execute(
                "SELECT state,revision FROM applications WHERE id=?", (app_id,)
            ).fetchone()
            count = int(
                db.execute("SELECT COUNT(*) FROM attempts WHERE day=?", (day_key(),)).fetchone()[0]
            )
            if not settings.automation_enabled:
                raise ValueError("Automation is paused")
            if (
                not row
                or row[0] != State.READY
                or row[1] != revision
                or revision != actual_revision
            ):
                raise ValueError("Application is not ready or its profile revision is stale")
            from .policy import evaluate

            application = db.execute(
                "SELECT job,manifest FROM applications WHERE id=?", (app_id,)
            ).fetchone()
            profile = Profile.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='profile'").fetchone()[0]
            )
            evaluation = evaluate(Job.model_validate_json(application["job"]), profile, settings)
            if (
                Job.model_validate_json(application["job"]).source == "linkedin"
                and not settings.linkedin_authorised
            ):
                raise ValueError("LinkedIn authorisation scope must be configured")
            if evaluation.state != State.READY or not json.loads(application["manifest"]).get(
                "files"
            ):
                raise ValueError("Current policy or documents do not allow submission")
            if count >= settings.daily_limit:
                raise ValueError("Daily attempt limit reached")
            cursor = db.execute(
                "INSERT INTO attempts(application_id,day,started) VALUES(?,?,?)",
                (app_id, day_key(), datetime.now(UTC).isoformat()),
            )
            db.execute("UPDATE applications SET state=? WHERE id=?", (State.SUBMITTING, app_id))
            self.event(
                db,
                "submission_reserved",
                "External action may follow; do not retry blindly.",
                app_id,
            )
            return int(cursor.lastrowid or 0)

    def finish(self, app_id: int, attempt: int, receipt: str | None) -> None:
        with self.connect(True) as db:
            row = db.execute(
                "SELECT a.state FROM applications a JOIN attempts t ON t.application_id=a.id WHERE a.id=? AND t.id=? AND t.id=(SELECT MAX(id) FROM attempts WHERE application_id=a.id)",
                (app_id, attempt),
            ).fetchone()
            if not row or row[0] != State.SUBMITTING:
                raise ValueError("Only the reserved submission attempt can be finished")
            state = State.SUBMITTED if receipt else State.UNCERTAIN
            db.execute(
                "UPDATE attempts SET receipt=? WHERE id=? AND application_id=?",
                (receipt, attempt, app_id),
            )
            db.execute(
                "UPDATE applications SET state=?, receipt=? WHERE id=?", (state, receipt, app_id)
            )
            self.event(db, "submission_finished", str(state), app_id)

    def recover(self) -> int:
        with self.connect(True) as db:
            count = db.execute(
                "UPDATE applications SET state=? WHERE state=?", (State.UNCERTAIN, State.SUBMITTING)
            ).rowcount
            if count:
                self.event(db, "recovery", f"{count} interrupted attempts require reconciliation.")
            return count

    def hold(self, app_id: int, detail: str) -> None:
        with self.connect(True) as db:
            row = db.execute("SELECT job FROM applications WHERE id=?", (app_id,)).fetchone()
            if not row:
                raise KeyError(app_id)
            job = Job.model_validate_json(row[0])
            prefix = "Approve an exact answer for: "
            if detail.startswith(prefix):
                label = detail[len(prefix) :].strip()[:500]
                key = "question:" + " ".join(label.casefold().split())
                question_id = "q_" + hashlib.sha256(key.encode()).hexdigest()[:16]
                if not any(q.id == question_id for q in job.questions):
                    job.questions.append(Question(id=question_id, label=label, answer_key=key))
            db.execute(
                "UPDATE applications SET state=?,job=? WHERE id=?",
                (State.REVIEW, job.model_dump_json(), app_id),
            )
            self.event(db, "provider_review_required", detail[:2000], app_id)

    def reconcile(self, app_id: int, receipt: str) -> None:
        with self.connect(True) as db:
            row = db.execute("SELECT state FROM applications WHERE id=?", (app_id,)).fetchone()
            if not row or row[0] not in {State.UNCERTAIN, State.REVIEW, State.READY}:
                raise ValueError("Only pending or uncertain applications can be reconciled")
            db.execute(
                "UPDATE applications SET state=?,receipt=? WHERE id=?",
                (State.SUBMITTED, receipt, app_id),
            )
            self.event(db, "manual_receipt", "Candidate recorded a submission receipt.", app_id)

    def outcome(self, app_id: int, outcome: str) -> None:
        with self.connect(True) as db:
            row = db.execute("SELECT state FROM applications WHERE id=?", (app_id,)).fetchone()
            if not row or row[0] != State.SUBMITTED:
                raise ValueError("Record outcomes only for confirmed submitted applications")
            db.execute("UPDATE applications SET outcome=? WHERE id=?", (outcome, app_id))
            self.event(db, "outcome_recorded", outcome, app_id)

    def events(self, app_id: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if app_id is not None:
                if not db.execute("SELECT 1 FROM applications WHERE id=?", (app_id,)).fetchone():
                    raise KeyError(app_id)
                return [
                    dict(row)
                    for row in db.execute(
                        "SELECT * FROM events WHERE application_id=? ORDER BY id DESC LIMIT 200",
                        (app_id,),
                    )
                ]
            return [
                dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 200")
            ]
