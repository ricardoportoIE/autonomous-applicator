"""Upgrade real reservation journals without forgetting receipts or uncertain sends."""

import sqlite3
from contextlib import closing

import pytest

from applicator.models import Settings
from applicator.store import Store


def test_failed_legacy_accounting_migration_rolls_back_schema_and_counts(data):
    path = data / "failed-migration.sqlite3"
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE attempts(id INTEGER PRIMARY KEY,application_id INTEGER NOT NULL,
                day TEXT NOT NULL,started TEXT NOT NULL,receipt TEXT);
            INSERT INTO attempts VALUES(1,1,'2026-10-04','fixture','confirmed:receipt');
            CREATE TRIGGER fail_upgrade BEFORE UPDATE ON attempts BEGIN
                SELECT RAISE(ABORT,'fixture migration interruption'); END;
        """)
    with pytest.raises(sqlite3.IntegrityError, match="migration interruption"):
        Store(path)
    with closing(sqlite3.connect(path)) as db, db:
        assert "status" not in {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
        assert db.execute("SELECT receipt FROM attempts").fetchone()[0] == "confirmed:receipt"
        db.execute("DROP TRIGGER fail_upgrade")
    store = Store(path)
    with store.connect() as db:
        assert db.execute("SELECT status FROM attempts").fetchone()[0] == "confirmed"


def test_legacy_attempts_migrate_once_and_preserve_unknown_capacity(data, job, monkeypatch):
    path = data / "legacy.sqlite3"
    path.parent.mkdir(parents=True)
    monkeypatch.setattr("applicator.store.day_key", lambda now=None: "2026-10-04")
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE applications (id INTEGER PRIMARY KEY, source TEXT NOT NULL,
                source_id TEXT NOT NULL, job TEXT NOT NULL, state TEXT NOT NULL,
                evaluation TEXT NOT NULL DEFAULT '{}', revision INTEGER NOT NULL DEFAULT 0,
                manifest TEXT NOT NULL DEFAULT '{}',receipt TEXT,outcome TEXT,
                UNIQUE(source,source_id));
            CREATE TABLE attempts (id INTEGER PRIMARY KEY,application_id INTEGER NOT NULL,
                day TEXT NOT NULL,started TEXT NOT NULL,receipt TEXT);
            CREATE TABLE events (id INTEGER PRIMARY KEY,application_id INTEGER,kind TEXT NOT NULL,
                detail TEXT NOT NULL,created TEXT NOT NULL);
        """)
        for app_id, state, receipt in [
            (1, "review", None),
            (2, "submitted", "old:receipt"),
            (3, "uncertain", None),
            (4, "submitted", "manual:receipt"),
            (5, "submitted", "manual:no-attempt"),
        ]:
            db.execute(
                "INSERT INTO applications(id,source,source_id,job,state,receipt) VALUES(?,?,?,?,?,?)",
                (app_id, "fixture", str(app_id), job.model_dump_json(), state, receipt),
            )
        for app_id, receipt in [(1, None), (2, "old:receipt"), (3, None), (3, None), (4, None)]:
            db.execute(
                "INSERT INTO attempts(application_id,day,started,receipt) VALUES(?,?,?,?)",
                (app_id, "2026-10-04", "2026-10-04T10:00:00+00:00", receipt),
            )
        for app_id in (4, 5):
            db.execute(
                "INSERT INTO events(application_id,kind,detail,created) VALUES(?,?,?,?)",
                (app_id, "manual_receipt", "Checked provider", "2026-10-04T11:00:00+00:00"),
            )
    store = Store(path)
    store.set_settings(Settings(daily_limit=10))
    usage = store.daily_usage()
    assert (usage.used, usage.held, usage.remaining) == (3, 1, 6)
    with store.connect() as db:
        assert [row[0] for row in db.execute("SELECT status FROM attempts ORDER BY id")] == [
            "released",
            "confirmed",
            "released",
            "held",
            "confirmed",
            "confirmed",
        ]
        assert (
            db.execute("SELECT COUNT(*) FROM events WHERE kind='manual_receipt'").fetchone()[0] == 2
        )
    assert Store(path).daily_usage() == usage  # Reopening never repeats the migration.
    monkeypatch.setattr("applicator.store.day_key", lambda now=None: "2026-10-05")
    next_day = store.daily_usage()
    assert (next_day.used, next_day.held, next_day.remaining) == (0, 1, 9)
