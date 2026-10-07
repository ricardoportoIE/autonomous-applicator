"""Reversible queue removal and narrowly scoped, truthful candidate review decisions."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from .documents import fingerprint
from .models import Evaluation, Job, Profile, Settings, State
from .policy import evaluate

if TYPE_CHECKING:
    from .store import Store


def experience_reviewable(blocker: str) -> bool:
    return blocker.startswith(
        (
            "Required professional experience is below the stated minimum: ",
            "Required professional experience needs review: ",
            "Required production machine learning experience is not met: ",
        )
    )


class ApplicationManagement:
    def __init__(self, store: "Store"):
        self.store = store
        with store.connect(True) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS application_trash (
                    application_id INTEGER PRIMARY KEY, moved_at TEXT NOT NULL, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS application_review_decisions (
                    application_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL,
                    job_fingerprint TEXT NOT NULL, blockers TEXT NOT NULL,
                    accept_fit INTEGER NOT NULL, created TEXT NOT NULL);
            """)

    def trashed(self, db: sqlite3.Connection, app_id: int) -> bool:
        return (
            db.execute(
                "SELECT 1 FROM application_trash WHERE application_id=?", (app_id,)
            ).fetchone()
            is not None
        )

    def metadata(self, db: sqlite3.Connection, app_id: int) -> dict[str, Any]:
        row = db.execute(
            "SELECT moved_at,reason FROM application_trash WHERE application_id=?", (app_id,)
        ).fetchone()
        return {"trashed": row is not None, "trash": dict(row) if row else None}

    def guard(
        self, db: sqlite3.Connection, app_id: int, revision: int, expected_job: Job
    ) -> sqlite3.Row:
        row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
        if row is None:
            raise KeyError(app_id)
        current = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
        if current != revision or fingerprint(Job.model_validate_json(row["job"])) != fingerprint(
            expected_job
        ):
            raise ValueError(
                "Candidate facts or opportunity changed. Refresh the application before deciding."
            )
        if db.execute(
            "SELECT 1 FROM application_runs WHERE status='running' AND kind NOT IN ('trash','restore','review_decision')"
        ).fetchone():
            raise ValueError(
                "Pause the agent and wait for its current operation before managing applications"
            )
        if (
            row["state"] in {State.SUBMITTING, State.UNCERTAIN}
            or db.execute(
                "SELECT 1 FROM attempts WHERE application_id=? AND status='held'", (app_id,)
            ).fetchone()
        ):
            raise ValueError(
                "Reconcile the pending or uncertain submission before managing this application."
            )
        return cast(sqlite3.Row, row)

    def move(self, app_id: int, revision: int, job: Job, reason: str) -> None:
        if len(reason) > 500:
            raise ValueError("Trash reasons must be at most 500 characters")
        with self.store.connect(True) as db:
            self.guard(db, app_id, revision, job)
            if self.trashed(db, app_id):
                return
            db.execute(
                "INSERT INTO application_trash VALUES(?,?,?)",
                (app_id, datetime.now(UTC).isoformat(), reason.strip()),
            )
            self.store.event(
                db,
                "application_moved_to_trash",
                reason.strip() or "Removed from the application queue by the candidate.",
                app_id,
            )

    def restore(self, app_id: int, revision: int, job: Job) -> None:
        with self.store.connect(True) as db:
            row = self.guard(db, app_id, revision, job)
            if not self.trashed(db, app_id):
                raise ValueError("This application is not in Trash")
            db.execute("DELETE FROM application_trash WHERE application_id=?", (app_id,))
            if row["state"] in {State.READY, State.REVIEW}:
                db.execute(
                    "UPDATE applications SET state=?,evaluation='{}',revision=0 WHERE id=?",
                    (State.REVIEW, app_id),
                )
                db.execute(
                    "DELETE FROM application_review_decisions WHERE application_id=?", (app_id,)
                )
            self.store.event(
                db,
                "application_restored",
                "Restored from Trash. Pending work requires a fresh readiness check.",
                app_id,
            )

    def accept(
        self, app_id: int, revision: int, job: Job, blockers: list[str], accept_fit: bool
    ) -> None:
        with self.store.connect(True) as db:
            row = self.guard(db, app_id, revision, job)
            if row["state"] not in {State.READY, State.REVIEW} or self.trashed(db, app_id):
                raise ValueError("Only active pending applications can receive a review decision")
            profile, _ = self.store.profile()
            if not profile.confirmed:
                raise ValueError("Confirm candidate facts before making a review decision")
            settings = self.store.settings()
            result = evaluate(job, self.store.effective_profile(app_id, profile, job, db), settings)
            if not blockers and not accept_fit:
                raise ValueError("Select an experience or fit review decision")
            if len(set(blockers)) != len(blockers) or any(
                not experience_reviewable(value) or value not in result.blockers
                for value in blockers
            ):
                raise ValueError(
                    "Only current professional experience requirements can be accepted"
                )
            if (
                accept_fit
                and not settings.review_threshold <= result.score < settings.auto_threshold
            ):
                raise ValueError("Only the candidate-review fit band can be accepted")
            db.execute(
                "INSERT OR REPLACE INTO application_review_decisions VALUES(?,?,?,?,?,?)",
                (
                    app_id,
                    revision,
                    fingerprint(job),
                    json.dumps(blockers),
                    int(accept_fit),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self.store.event(
                db,
                "application_review_accepted",
                json.dumps(
                    {
                        "blockers": blockers,
                        "accept_fit": accept_fit,
                        "revision": revision,
                        "answers_unchanged": True,
                    }
                ),
                app_id,
            )

    def evaluation(
        self,
        app_id: int,
        profile: Profile,
        job: Job,
        settings: Settings,
        db: sqlite3.Connection | None = None,
    ) -> Evaluation:
        if db is None:
            with self.store.connect() as connection:
                return self.evaluation(app_id, profile, job, settings, connection)
        result = evaluate(job, profile, settings)
        revision = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
        decision = db.execute(
            "SELECT * FROM application_review_decisions WHERE application_id=? AND revision=? AND job_fingerprint=?",
            (app_id, revision, fingerprint(job)),
        ).fetchone()
        if decision is None:
            return result
        accepted = [
            value for value in json.loads(decision["blockers"]) if experience_reviewable(value)
        ]
        removed = [value for value in result.blockers if value in accepted]
        result.blockers = [value for value in result.blockers if value not in accepted]
        fit_accepted = (
            bool(decision["accept_fit"])
            and settings.review_threshold <= result.score < settings.auto_threshold
        )
        if removed or fit_accepted:
            result.reasons.append(
                "Candidate accepted this opportunity's experience/fit review. All answers remain truthful; other submission checks still apply."
            )
        if not result.blockers and (result.score >= settings.auto_threshold or fit_accepted):
            result.state = State.READY
        return result
