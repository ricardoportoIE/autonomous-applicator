"""SQLite journal with durable reservations and versioned candidate data."""

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .models import DailyUsage, Evaluation, Evidence, Job, Profile, Question, Settings, State


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
                CREATE TABLE IF NOT EXISTS discovery_discards (
                    id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
                    url TEXT NOT NULL, url_key TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
                    company TEXT NOT NULL, location TEXT NOT NULL, score INTEGER NOT NULL CHECK(score<50),
                    evaluation TEXT NOT NULL, profile_revision INTEGER NOT NULL, created TEXT NOT NULL,
                    UNIQUE(source,source_id));
                CREATE TABLE IF NOT EXISTS submission_records (
                    attempt_id INTEGER PRIMARY KEY,application_id INTEGER NOT NULL,
                    created TEXT NOT NULL,sent_at TEXT,confirmed_at TEXT,
                    snapshot TEXT NOT NULL,fields TEXT NOT NULL DEFAULT '[]',
                    confirmation TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS routine_answers (
                    application_id INTEGER NOT NULL, answer_key TEXT NOT NULL,
                    question TEXT NOT NULL, answer TEXT NOT NULL, source TEXT NOT NULL,
                    evidence_ids TEXT NOT NULL, revision INTEGER NOT NULL,
                    job_fingerprint TEXT NOT NULL, created TEXT NOT NULL,
                    PRIMARY KEY(application_id,answer_key));
                CREATE TABLE IF NOT EXISTS approved_answers (
                    application_id INTEGER NOT NULL, answer_key TEXT NOT NULL,
                    answer TEXT NOT NULL, revision INTEGER NOT NULL,
                    job_fingerprint TEXT NOT NULL, created TEXT NOT NULL,
                    PRIMARY KEY(application_id,answer_key));
                CREATE TABLE IF NOT EXISTS location_reviews (
                    application_id INTEGER PRIMARY KEY, revision INTEGER NOT NULL,
                    job_fingerprint TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS application_runs (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL,
                    application_id INTEGER, stage TEXT NOT NULL, detail TEXT NOT NULL,
                    started TEXT NOT NULL, updated TEXT NOT NULL, stage_started TEXT NOT NULL,
                    finished TEXT, error_code TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_application_run
                    ON application_runs(status) WHERE status='running';
                CREATE TABLE IF NOT EXISTS application_run_results (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, application_id INTEGER NOT NULL,
                    outcome TEXT NOT NULL, stage TEXT NOT NULL, error_code TEXT, finished TEXT NOT NULL,
                    UNIQUE(run_id,application_id));
            """)
            db.execute(
                "INSERT OR IGNORE INTO config VALUES ('settings', ?)",
                (Settings().model_dump_json(),),
            )
            db.execute("INSERT OR IGNORE INTO config VALUES ('revision', '0')")
            columns = {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
            if "status" not in columns:
                db.execute("ALTER TABLE attempts ADD COLUMN status TEXT NOT NULL DEFAULT 'held'")
                db.execute(
                    "UPDATE attempts SET status='confirmed' WHERE receipt IS NOT NULL AND receipt!=''"
                )
                # Existing review stops happened before the provider's irreversible click.
                db.execute(
                    "UPDATE attempts SET status='released' WHERE receipt IS NULL AND application_id IN "
                    "(SELECT id FROM applications WHERE state IN ('review','ready','skipped'))"
                )
                db.execute(
                    "UPDATE attempts SET status='released' WHERE receipt IS NULL AND id NOT IN (SELECT MAX(id) FROM attempts GROUP BY application_id)"
                )
            if "confirmed_day" not in columns:
                db.execute("ALTER TABLE attempts ADD COLUMN confirmed_day TEXT")
                db.execute("UPDATE attempts SET confirmed_day=day WHERE status='confirmed'")
                for row in db.execute(
                    "SELECT a.id,a.receipt,MAX(t.id) AS attempt FROM applications a LEFT JOIN attempts t ON t.application_id=a.id WHERE a.state='submitted' AND a.receipt IS NOT NULL GROUP BY a.id"
                ).fetchall():
                    if db.execute(
                        "SELECT 1 FROM attempts WHERE application_id=? AND status='confirmed'",
                        (row[0],),
                    ).fetchone():
                        continue
                    event = db.execute(
                        "SELECT created FROM events WHERE application_id=? AND kind='manual_receipt' ORDER BY id DESC LIMIT 1",
                        (row[0],),
                    ).fetchone()
                    confirmed_day = (
                        day_key(datetime.fromisoformat(event[0])) if event else day_key()
                    )
                    if row[2]:
                        db.execute(
                            "UPDATE attempts SET receipt=?,status='confirmed',confirmed_day=? WHERE id=?",
                            (row[1], confirmed_day, row[2]),
                        )
                    else:
                        db.execute(
                            "INSERT INTO attempts(application_id,day,started,receipt,status,confirmed_day) VALUES(?,?,?,?,?,?)",
                            (
                                row[0],
                                confirmed_day,
                                event[0] if event else datetime.now(UTC).isoformat(),
                                row[1],
                                "confirmed",
                                confirmed_day,
                            ),
                        )
            if "sent_day" not in columns:
                db.execute("ALTER TABLE attempts ADD COLUMN sent_day TEXT")
        from .question_library import QuestionLibrary

        self.question_library = QuestionLibrary(self)
        from .application_management import ApplicationManagement

        self.management = ApplicationManagement(self)

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

    def recovery_strategy(self, shape: str, strategy: str | None = None) -> str | None:
        """Remember a verified interaction method, never an answer or site instruction."""
        methods = (
            {"label", "aria"}
            if shape == "resume-widget"
            else {"settled", "timeout-transition"}
            if shape == "advance-step"
            else {"native", "label", "aria"}
        )
        if not re.fullmatch(r"(?:checkbox|radio)-[01]{3}|resume-widget|advance-step", shape):
            raise ValueError("Unsupported recovery shape")
        if strategy is not None and strategy not in methods:
            raise ValueError("Unsupported recovery strategy")
        key = "browser_recovery:" + shape
        with self.connect(True) as db:
            if strategy is not None:
                db.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (key, strategy))
                return strategy
            row = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
            return row[0] if row and row[0] in methods else None

    def form_recovery_available(self, app_id: int, *, claim: bool = False) -> bool:
        """At most two automatic resumptions of a proven pre-send technical stop."""
        with self.connect(True) as db:
            row = db.execute("SELECT state FROM applications WHERE id=?", (app_id,)).fetchone()
            attempt = db.execute(
                "SELECT status FROM attempts WHERE application_id=? ORDER BY id DESC LIMIT 1",
                (app_id,),
            ).fetchone()
            event = db.execute(
                "SELECT detail FROM events WHERE application_id=? AND kind='provider_review_required' ORDER BY id DESC LIMIT 1",
                (app_id,),
            ).fetchone()
            if (
                not row
                or row[0] != State.REVIEW
                or not attempt
                or attempt[0] != "released"
                or not event
            ):
                return False
            detail = event[0]
            technical = detail.startswith(
                (
                    "Locator.",
                    "Ambiguous phone controls",
                    "Unlabelled form control",
                    "The application did not advance",
                    "The approved checkbox",
                    "The approved radio",
                    "Form control identity",
                    "Ambiguous form control",
                    "Easy Apply control",
                    "The uploaded resume selection is unsupported; review manually",
                    "Approved answer does not match available choices: Will you now or in the future require sponsorship for employment visa status?",
                )
            )
            if not technical or re.search(r"authwall|checkpoint|challenge|login", detail, re.I):
                return False
            # A tested adapter upgrade gets a fresh bounded budget; restart does not.
            key = f"form_recovery:v3:{app_id}"
            saved = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
            value = saved[0] if saved else "0"
            if value not in {"0", "1"}:
                return False
            if claim:
                db.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (key, str(int(value) + 1)))
                self.event(
                    db,
                    "form_recovery_queued",
                    f"Technical recovery {int(value) + 1}/2; no previous submission click.",
                    app_id,
                )
            return True

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
                    "WHERE state IN (?,?) AND COALESCE(json_extract(manifest,'$.generation.method'),'') != ? "
                    "AND id NOT IN (SELECT application_id FROM application_trash)",
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
            "UPDATE applications SET state=?, manifest='{}' WHERE state IN (?, ?, ?) AND id NOT IN (SELECT application_id FROM application_trash)",
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
            return self._add_job(db, job)

    def _add_job(self, db: sqlite3.Connection, job: Job) -> tuple[int, bool]:
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
        for question in job.questions:
            self.question_library.observe(app_id, question, db)
        self.event(db, "job_added", f"Imported {job.source} job.", app_id)
        return app_id, True

    @staticmethod
    def discovery_url_key(url: str) -> str:
        parsed = urlsplit(url)
        return str(parsed.hostname) + parsed.path.rstrip("/")

    def discarded_job_ids(self, source: str) -> set[str]:
        with self.connect() as db:
            return {
                str(row[0])
                for row in db.execute(
                    "SELECT source_id FROM discovery_discards WHERE source=?", (source,)
                )
            }

    def screen_discovery(
        self, jobs: list[tuple[Job, Evaluation]], revision: int, settings: Settings
    ) -> dict[str, int]:
        """Commit a whole assessed batch without creating low-fit application records."""
        counts = {"imported": 0, "discarded": 0, "excluded": 0, "duplicates": 0}
        with self.connect(True) as db:
            current_revision = int(
                db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0]
            )
            current_settings = Settings.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='settings'").fetchone()[0]
            )
            if current_revision != revision or current_settings != settings:
                raise ValueError(
                    "Candidate or settings changed during discovery; repeat the search"
                )
            for job, evaluation in jobs:
                key = self.discovery_url_key(job.url)
                if db.execute(
                    "SELECT 1 FROM discovery_discards WHERE (source=? AND source_id=?) OR url_key=?",
                    (job.source, job.source_id, key),
                ).fetchone():
                    counts["excluded"] += 1
                    continue
                # Preserve an explicit import or previous application regardless of its new score.
                existing = db.execute(
                    "SELECT 1 FROM applications WHERE source=? AND source_id=?",
                    (job.source, job.source_id),
                ).fetchone()
                known_url = any(
                    self.discovery_url_key(json.loads(row[0])["url"]) == key
                    for row in db.execute("SELECT job FROM applications")
                )
                if existing or known_url:
                    counts["duplicates"] += 1
                    continue
                if evaluation.score < 50:
                    db.execute(
                        "INSERT INTO discovery_discards(source,source_id,url,url_key,title,company,location,score,evaluation,profile_revision,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            job.source,
                            job.source_id,
                            job.url,
                            key,
                            job.title,
                            job.company,
                            job.location,
                            evaluation.score,
                            evaluation.model_dump_json(),
                            revision,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                    self.event(
                        db,
                        "discovery_discarded",
                        f"{job.title} at {job.company}: fit {evaluation.score}/100, below 50. Excluded from future automatic discovery.",
                    )
                    counts["discarded"] += 1
                else:
                    counts["imported"] += int(self._add_job(db, job)[1])
            self.event(db, "discovery_screened", json.dumps(counts))
        return counts

    def discovery_discards(
        self, limit: int = 100, before: int | None = None
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 200 or (before is not None and before < 1):
            raise ValueError("Invalid discarded discovery page")
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM discovery_discards WHERE (? IS NULL OR id<?) ORDER BY id DESC LIMIT ?",
                (before, before, limit),
            ).fetchall()
            return [{**dict(row), "evaluation": json.loads(row["evaluation"])} for row in rows]

    def application(self, app_id: int) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM applications WHERE id=?", (app_id,)).fetchone()
            if not row:
                raise KeyError(app_id)
            result = dict(row)
            for key in ("job", "evaluation", "manifest"):
                result[key] = json.loads(result[key])
            result["routine_answers"] = self._routine_answers(
                db, app_id, Job.model_validate(result["job"])
            )
            result["approved_answers"] = self._approved_answers(
                db, app_id, Job.model_validate(result["job"])
            )
            result.update(self.management.metadata(db, app_id))
            return result

    def _approved_answers(self, db: sqlite3.Connection, app_id: int, job: Job) -> dict[str, str]:
        from .documents import fingerprint

        revision = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
        return dict(
            db.execute(
                "SELECT answer_key,answer FROM approved_answers WHERE application_id=? "
                "AND revision=? AND job_fingerprint=?",
                (app_id, revision, fingerprint(job)),
            ).fetchall()
        )

    def approve_answer(
        self, app_id: int, question_id: str, answer: str, revision: int, expected_job: Job
    ) -> None:
        """Approve one application answer without changing candidate facts or other CVs."""
        from .documents import fingerprint
        from .policy import answer_compatible
        from .question_adviser import question_key

        with self.connect(True) as db:
            row = db.execute("SELECT job,state FROM applications WHERE id=?", (app_id,)).fetchone()
            if self.management.trashed(db, app_id):
                raise ValueError("Restore this opportunity from Trash before changing its answers")
            current = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
            if not row:
                raise KeyError(app_id)
            if current != revision or Job.model_validate_json(row[0]) != expected_job:
                raise ValueError(
                    "Candidate or opportunity changed. Reload before approving an answer."
                )
            if row[1] not in {State.REVIEW, State.READY}:
                raise ValueError("Only pending applications can receive an approved answer")
            questions = [
                *expected_job.questions,
                *[
                    Question.model_validate(item["question"])
                    for item in self._routine_answers(db, app_id, expected_job)
                ],
            ]
            question = next((item for item in questions if item.id == question_id), None)
            if question is None:
                raise KeyError(question_id)
            if (
                question.sensitive
                or not answer.strip()
                or len(answer) > 3000
                or not answer_compatible(question, answer)
            ):
                raise ValueError(
                    "Approve a non-sensitive answer that matches the choices; years of experience require a number"
                )
            db.execute(
                "INSERT OR REPLACE INTO approved_answers VALUES(?,?,?,?,?,?)",
                (
                    app_id,
                    question_key(question),
                    answer,
                    revision,
                    fingerprint(expected_job),
                    datetime.now(UTC).isoformat(),
                ),
            )
            # If the subsequent readiness refresh is interrupted, the worker must
            # re-evaluate this application instead of skipping its old review hold.
            db.execute(
                "UPDATE applications SET state=?,evaluation='{}' WHERE id=?", (State.REVIEW, app_id)
            )
            self.event(
                db, "question_answer_approved", json.dumps({"question_id": question_id}), app_id
            )

    def _routine_answers(
        self, db: sqlite3.Connection, app_id: int, job: Job
    ) -> list[dict[str, Any]]:
        from .documents import fingerprint

        revision = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
        rows = []
        for entry in db.execute(
            "SELECT * FROM routine_answers WHERE application_id=? AND revision=? AND job_fingerprint=?",
            (app_id, revision, fingerprint(job)),
        ):
            item = dict(entry)
            item["question"] = json.loads(item["question"])
            item["evidence_ids"] = json.loads(item["evidence_ids"])
            rows.append(item)
        return rows

    def effective_profile(
        self, app_id: int, profile: Profile, job: Job, db: sqlite3.Connection | None = None
    ) -> Profile:
        from .answer_style import experience_target, format_known_answer, numeric_field
        from .documents import fingerprint
        from .location_policy import normalise_location
        from .policy import answer_compatible

        if db is None:
            with self.connect() as connection:
                return self.effective_profile(app_id, profile, job, connection)
        settings = Settings.model_validate_json(
            db.execute("SELECT value FROM config WHERE key='settings'").fetchone()[0]
        )
        routine = self._routine_answers(db, app_id, job) if settings.routine_answers_enabled else []
        answers = {item["answer_key"]: item["answer"] for item in routine}
        confirmed = {**profile.answers, **self._approved_answers(db, app_id, job)}
        for item in routine:
            question = Question.model_validate(item["question"])
            previous = confirmed.get(item["answer_key"])
            if (
                previous
                and not question.sensitive
                and numeric_field(question)
                and experience_target(question) is not None
                and format_known_answer(question, previous) is None
                and answer_compatible(question, item["answer"])
            ):
                # A resolved duration must survive readiness checks, whilst the
                # original narrative remains in the candidate's private profile.
                confirmed[item["answer_key"]] = item["answer"]
        revision = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
        if db.execute(
            "SELECT 1 FROM location_reviews WHERE application_id=? AND revision=? AND job_fingerprint=?",
            (app_id, revision, fingerprint(job)),
        ).fetchone():
            answers["condition:location:" + normalise_location(job.location)] = "Confirmed"
        return profile.model_copy(update={"answers": {**answers, **confirmed}})

    def save_routine_answer(
        self,
        app_id: int,
        question: Question,
        answer: str,
        source: str,
        evidence_ids: list[str],
        revision: int,
        expected_job: Job,
    ) -> None:
        from .documents import fingerprint
        from .question_adviser import question_key

        with self.connect(True) as db:
            self.question_library.validate_current(db, source)
            row = db.execute("SELECT job,state FROM applications WHERE id=?", (app_id,)).fetchone()
            current = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
            if not row or current != revision or Job.model_validate_json(row[0]) != expected_job:
                raise ValueError(
                    "Candidate or opportunity changed while resolving a routine question"
                )
            if row[1] not in {State.REVIEW, State.READY, State.SUBMITTING}:
                raise ValueError("This application cannot receive a routine answer")
            if (
                not answer
                or len(answer) > 3000
                or question.sensitive
                or (question.choices and answer not in question.choices)
            ):
                raise ValueError("The routine answer is not valid for this question")
            db.execute(
                "INSERT OR REPLACE INTO routine_answers VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    app_id,
                    question_key(question),
                    question.model_dump_json(),
                    answer,
                    source,
                    json.dumps(evidence_ids),
                    revision,
                    fingerprint(expected_job),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self.event(
                db,
                "routine_question_answered",
                json.dumps(
                    {"question_id": question.id, "source": source, "evidence_ids": evidence_ids}
                ),
                app_id,
            )

    def confirm_location(self, app_id: int, revision: int, location: str) -> None:
        from .documents import fingerprint

        with self.connect(True) as db:
            row = db.execute("SELECT job,state FROM applications WHERE id=?", (app_id,)).fetchone()
            current = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
            if not row:
                raise KeyError(app_id)
            job = Job.model_validate_json(row[0])
            if (
                current != revision
                or job.location != location
                or row[1] not in {State.REVIEW, State.READY}
            ):
                raise ValueError("Location or candidate changed; review the current opportunity")
            db.execute(
                "INSERT OR REPLACE INTO location_reviews VALUES(?,?,?,?)",
                (app_id, revision, fingerprint(job), datetime.now(UTC).isoformat()),
            )
            db.execute("UPDATE applications SET evaluation='{}' WHERE id=?", (app_id,))
            self.event(
                db,
                "location_confirmed",
                "Candidate accepted the reviewed opportunity's location.",
                app_id,
            )

    def update_job(self, app_id: int, job: Job) -> None:
        with self.connect(True) as db:
            if self.management.trashed(db, app_id):
                raise ValueError("Restore this opportunity from Trash before editing it")
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
            for question in job.questions:
                self.question_library.observe(app_id, question, db)

    def applications(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT a.*,t.moved_at AS trashed_at,t.reason AS trash_reason FROM applications a LEFT JOIN application_trash t ON t.application_id=a.id ORDER BY a.id DESC"
                )
            ]
        for row in rows:
            row["trashed"] = row["trashed_at"] is not None
            for key in ("job", "evaluation", "manifest"):
                row[key] = json.loads(row[key])
        return rows

    def daily_usage(self) -> DailyUsage:
        # Confirmations consume the daily limit; uncertain sends hold capacity separately.
        day = day_key()
        with self.connect() as db:
            row = db.execute(
                "SELECT value, "
                "(SELECT COUNT(*) FROM attempts WHERE status='confirmed' AND confirmed_day=?) AS used, "
                "(SELECT COUNT(*) FROM attempts WHERE status='held') AS held, "
                "(SELECT COUNT(*) FROM attempts WHERE day=?) AS attempts "
                "FROM config WHERE key='settings'",
                (day, day),
            ).fetchone()
        limit = Settings.model_validate_json(row["value"]).daily_limit
        used = int(row["used"])
        held = int(row["held"])
        return DailyUsage(
            day=day,
            used=used,
            held=held,
            attempts=int(row["attempts"]),
            limit=limit,
            remaining=max(0, limit - used - held),
        )

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
            if self.management.trashed(db, app_id):
                raise ValueError("Restore this application from Trash before preparing it")
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
            if self.management.trashed(db, app_id):
                raise ValueError("Applications in Trash cannot be submitted")
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
                db.execute(
                    "SELECT COUNT(*) FROM attempts WHERE status='held' OR (status='confirmed' AND confirmed_day=?)",
                    (day_key(),),
                ).fetchone()[0]
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
            application = db.execute(
                "SELECT job,manifest FROM applications WHERE id=?", (app_id,)
            ).fetchone()
            profile = Profile.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='profile'").fetchone()[0]
            )
            vacancy = Job.model_validate_json(application["job"])
            evaluation = self.management.evaluation(
                app_id, self.effective_profile(app_id, profile, vacancy, db), vacancy, settings, db
            )
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
                raise ValueError("Daily sent-application limit reached; preparation may continue")
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
                "UPDATE attempts SET receipt=?,status=?,confirmed_day=CASE WHEN ? IS NULL THEN NULL ELSE COALESCE(sent_day,?) END WHERE id=? AND application_id=?",
                (
                    receipt,
                    "confirmed" if receipt else "held",
                    receipt,
                    day_key(),
                    attempt,
                    app_id,
                ),
            )
            db.execute(
                "UPDATE applications SET state=?, receipt=? WHERE id=?", (state, receipt, app_id)
            )
            if receipt:
                db.execute(
                    "UPDATE submission_records SET confirmed_at=? WHERE attempt_id=?",
                    (datetime.now(UTC).isoformat(), attempt),
                )
            self.event(db, "submission_finished", str(state), app_id)

    def mark_sending(self, app_id: int, attempt: int, revision: int, job: Job) -> None:
        """Repeat mutable gates immediately before the browser's irreversible click."""
        with self.connect(True) as db:
            settings = Settings.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='settings'").fetchone()[0]
            )
            current = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
            row = db.execute("SELECT state,job FROM applications WHERE id=?", (app_id,)).fetchone()
            held = db.execute(
                "SELECT 1 FROM attempts WHERE id=? AND application_id=? AND status='held'",
                (attempt, app_id),
            ).fetchone()
            count = db.execute(
                "SELECT COUNT(*) FROM attempts WHERE status='held' OR (status='confirmed' AND confirmed_day=?)",
                (day_key(),),
            ).fetchone()[0]
            if not settings.automation_enabled or (
                job.source == "linkedin" and not settings.linkedin_authorised
            ):
                raise ValueError("Submission permission changed before sending")
            if (
                current != revision
                or not row
                or row[0] != State.SUBMITTING
                or not held
                or Job.model_validate_json(row[1]) != job
            ):
                raise ValueError("Candidate or opportunity changed before sending")
            if count > settings.daily_limit:
                raise ValueError("Daily sending capacity changed before sending")
            from .policy import evaluate

            profile = Profile.model_validate_json(
                db.execute("SELECT value FROM config WHERE key='profile'").fetchone()[0]
            )
            if (
                evaluate(job, self.effective_profile(app_id, profile, job, db), settings).state
                != State.READY
            ):
                raise ValueError("Submission policy changed before sending")
            db.execute("UPDATE attempts SET sent_day=? WHERE id=?", (day_key(), attempt))
            db.execute(
                "UPDATE submission_records SET sent_at=? WHERE attempt_id=?",
                (datetime.now(UTC).isoformat(), attempt),
            )

    def confirm_not_sent(self, app_id: int, revision: int) -> None:
        with self.connect(True) as db:
            current = int(db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0])
            row = db.execute("SELECT state FROM applications WHERE id=?", (app_id,)).fetchone()
            attempt = db.execute(
                "SELECT id,status,receipt FROM attempts WHERE application_id=? ORDER BY id DESC LIMIT 1",
                (app_id,),
            ).fetchone()
            if (
                current != revision
                or not row
                or row[0] != State.UNCERTAIN
                or not attempt
                or attempt[1] != "held"
                or attempt[2]
            ):
                raise ValueError("Only a current uncertain submission can be confirmed as not sent")
            db.execute("UPDATE attempts SET status='released' WHERE id=?", (attempt[0],))
            db.execute(
                "UPDATE applications SET state=?,revision=?,evaluation=?,manifest='{}' WHERE id=?",
                (
                    State.REVIEW,
                    current,
                    json.dumps(
                        {
                            "state": "review",
                            "blockers": [
                                "Candidate confirmed no submission; prepare again manually before retrying."
                            ],
                        }
                    ),
                    app_id,
                ),
            )
            self.event(
                db,
                "submission_confirmed_not_sent",
                "Candidate checked the provider; no submission was sent. Fresh preparation is required.",
                app_id,
            )

    def recover(self) -> int:
        with self.connect(True) as db:
            now = datetime.now(UTC).isoformat()
            for run in db.execute(
                "SELECT id,application_id,stage FROM application_runs WHERE status='running'"
            ).fetchall():
                db.execute(
                    "UPDATE application_runs SET status='interrupted',error_code='ProcessInterrupted',updated=?,finished=? WHERE id=?",
                    (now, now, run["id"]),
                )
                self.event(
                    db,
                    "application_run_interrupted",
                    json.dumps(
                        {
                            "run_id": run["id"],
                            "stage": run["stage"],
                            "error_code": "ProcessInterrupted",
                        }
                    ),
                    run["application_id"],
                )
                row = db.execute(
                    "SELECT state,evaluation FROM applications WHERE id=?", (run["application_id"],)
                ).fetchone()
                if row and row["state"] in {State.REVIEW, State.READY}:
                    evaluation = json.loads(row["evaluation"])
                    evaluation["state"] = State.REVIEW
                    evaluation.setdefault("blockers", []).append(
                        "Processing was interrupted; inspect the recorded stage and prepare again manually."
                    )
                    revision = int(
                        db.execute("SELECT value FROM config WHERE key='revision'").fetchone()[0]
                    )
                    db.execute(
                        "UPDATE applications SET state=?,evaluation=?,revision=?,manifest='{}' WHERE id=?",
                        (State.REVIEW, json.dumps(evaluation), revision, run["application_id"]),
                    )
                if row:
                    outcome = (
                        State.UNCERTAIN
                        if row["state"] == State.SUBMITTING
                        else State.REVIEW
                        if row["state"] == State.READY
                        else row["state"]
                    )
                    db.execute(
                        "INSERT OR IGNORE INTO application_run_results(run_id,application_id,outcome,stage,error_code,finished) VALUES(?,?,?,?,?,?)",
                        (
                            run["id"],
                            run["application_id"],
                            outcome,
                            run["stage"],
                            None if outcome == State.SUBMITTED else "ProcessInterrupted",
                            now,
                        ),
                    )
            count = db.execute(
                "UPDATE applications SET state=? WHERE state=?", (State.UNCERTAIN, State.SUBMITTING)
            ).rowcount
            if count:
                self.event(db, "recovery", f"{count} interrupted attempts require reconciliation.")
            return count

    def hold(
        self,
        app_id: int,
        detail: str,
        *,
        attempt: int | None = None,
        question: Question | None = None,
        questions: list[Question] | None = None,
    ) -> None:
        with self.connect(True) as db:
            row = db.execute(
                "SELECT job,state,evaluation FROM applications WHERE id=?", (app_id,)
            ).fetchone()
            if not row:
                raise KeyError(app_id)
            if attempt is not None:
                held = db.execute(
                    "SELECT 1 FROM attempts WHERE id=? AND application_id=? AND status='held' "
                    "AND id=(SELECT MAX(id) FROM attempts WHERE application_id=?)",
                    (attempt, app_id, app_id),
                ).fetchone()
                if row[1] != State.SUBMITTING or not held:
                    raise ValueError("Only the current held submission can stop before sending")
                db.execute("UPDATE attempts SET status='released' WHERE id=?", (attempt,))
                self.event(
                    db, "submission_capacity_released", "No submission click was attempted.", app_id
                )
            job = Job.model_validate_json(row[0])
            prefix = "Approve an exact answer for: "
            if questions:
                from .documents import fingerprint
                from .question_adviser import question_key

                previous_fingerprint = fingerprint(job)
                changed_keys: set[str] = set()
                for observed in questions:
                    key = question_key(observed)
                    existing = next(
                        (item for item in job.questions if question_key(item) == key), None
                    )
                    if existing:
                        observed = observed.model_copy(
                            update={
                                "id": existing.id,
                                "sensitive": existing.sensitive or observed.sensitive,
                            }
                        )
                    if existing is None or existing.model_dump() != observed.model_dump():
                        changed_keys.add(key)
                    job.questions = [item for item in job.questions if question_key(item) != key]
                    job.questions.append(observed)
                # Validate the complete batch before committing either the hold or its reservation.
                job = Job.model_validate(job.model_dump())
                for key in changed_keys:
                    db.execute(
                        "DELETE FROM approved_answers WHERE application_id=? AND job_fingerprint=? AND answer_key=?",
                        (app_id, previous_fingerprint, key),
                    )
                for observed in questions:
                    db.execute(
                        "DELETE FROM routine_answers WHERE application_id=? AND job_fingerprint=? AND answer_key=?",
                        (app_id, previous_fingerprint, question_key(observed)),
                    )
                db.execute(
                    "UPDATE routine_answers SET job_fingerprint=? WHERE application_id=? AND job_fingerprint=?",
                    (fingerprint(job), app_id, previous_fingerprint),
                )
                db.execute(
                    "UPDATE location_reviews SET job_fingerprint=? WHERE application_id=? AND job_fingerprint=?",
                    (fingerprint(job), app_id, previous_fingerprint),
                )
                db.execute(
                    "UPDATE approved_answers SET job_fingerprint=? WHERE application_id=? AND job_fingerprint=?",
                    (fingerprint(job), app_id, previous_fingerprint),
                )
            elif detail.startswith(prefix):
                from .documents import fingerprint
                from .question_adviser import question_key

                previous_fingerprint = fingerprint(job)
                label = detail[len(prefix) :].strip()[:500]
                key = "question:" + " ".join(label.casefold().split())
                question_id = "q_" + hashlib.sha256(key.encode()).hexdigest()[:16]
                if question is not None and question.label == label:
                    key = question_key(question)
                    existing = next(
                        (item for item in job.questions if question_key(item) == key), None
                    )
                    observed = (
                        question.model_copy(update={"id": existing.id}) if existing else question
                    )
                    job.questions = [item for item in job.questions if item.id != observed.id]
                    job.questions.append(observed)
                elif not any(q.id == question_id for q in job.questions):
                    job.questions.append(Question(id=question_id, label=label, answer_key=key))
                # A newly observed question must not erase unrelated approvals.
                # Only matching snapshots move forward; changed question answers expire.
                db.execute(
                    "UPDATE approved_answers SET job_fingerprint=? WHERE application_id=? "
                    "AND job_fingerprint=? AND answer_key!=?",
                    (fingerprint(job), app_id, previous_fingerprint, key),
                )
            evaluation = json.loads(row[2])
            for observed_question in job.questions:
                self.question_library.observe(app_id, observed_question, db)
            state = (
                State.SKIPPED
                if detail == "The LinkedIn opportunity is no longer accepting applications"
                else State.REVIEW
            )
            evaluation["state"] = state
            blockers = evaluation.setdefault("blockers", [])
            if detail not in blockers:
                blockers.append(detail[:2000])
            db.execute(
                "UPDATE applications SET state=?,job=?,evaluation=? WHERE id=?",
                (state, job.model_dump_json(), json.dumps(evaluation), app_id),
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
            latest = db.execute(
                "SELECT id,status FROM attempts WHERE application_id=? ORDER BY id DESC LIMIT 1",
                (app_id,),
            ).fetchone()
            if latest:
                db.execute(
                    "UPDATE attempts SET receipt=?,status='confirmed',confirmed_day=? WHERE id=?",
                    (receipt, day_key(), latest[0]),
                )
            else:
                db.execute(
                    "INSERT INTO attempts(application_id,day,started,receipt,status,confirmed_day) VALUES(?,?,?,?,?,?)",
                    (
                        app_id,
                        day_key(),
                        datetime.now(UTC).isoformat(),
                        receipt,
                        "confirmed",
                        day_key(),
                    ),
                )
            self.event(db, "manual_receipt", "Candidate recorded a submission receipt.", app_id)
            if latest:
                db.execute(
                    "UPDATE submission_records SET confirmed_at=? WHERE attempt_id=?",
                    (datetime.now(UTC).isoformat(), latest[0]),
                )

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
