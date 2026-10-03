import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace

from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.models import Settings, State
from applicator.service import Service
from applicator.store import Store


def test_worker_logs_an_error_and_stops_cleanly(data, monkeypatch):
    import applicator.api as module

    class Stop:
        def __init__(self):
            self.calls = 0

        def wait(self, timeout):
            self.calls += 1
            return self.calls > 1

        def set(self):
            pass

        def is_set(self):
            return False

    class Thread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

        def join(self):
            pass

    monkeypatch.setattr(
        module, "threading", SimpleNamespace(Lock=threading.Lock, Event=Stop, Thread=Thread)
    )
    app = create_app(data, "local-test-token", worker=True)
    with TestClient(app):
        assert app.state.store.events()[0]["kind"] == "worker_cycle_failed"


def test_sqlite_backup_restore_preserves_attempt_and_requires_reconciliation(data, profile, job):
    store = Store(data / "original.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id, _ = store.add_job(job)
    Service(store, data).prepare(app_id)
    store.reserve(app_id, 1)
    backup_path = data / "restored.sqlite3"
    with store.connect() as source, closing(sqlite3.connect(backup_path)) as backup:
        source.backup(backup)
    restored = Store(backup_path)
    assert restored.profile()[0].name == profile.name
    assert restored.application(app_id)["state"] == State.SUBMITTING
    assert restored.recover() == 1
    assert restored.application(app_id)["state"] == State.UNCERTAIN
