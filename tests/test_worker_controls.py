"""Immediate, single-threaded worker start/resume and prompt shutdown."""

import threading

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.models import Settings
from applicator.service import Service

TOKEN = "fixture-token-012345678901234567890123456789"


def test_start_without_a_background_worker_has_no_side_effects(data):
    app = create_app(data, TOKEN)
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as client:
        assert client.post("/api/worker/start").status_code == 503
        assert not app.state.store.settings().automation_enabled


@pytest.mark.parametrize("networking", [False, True])
def test_start_wakes_worker_immediately_and_retains_networking_preferences(
    data, profile, monkeypatch, networking
):
    called = threading.Event()
    calls = []

    def process(self, operation, *, stopping):
        calls.append(threading.get_ident())
        called.set()
        return {}

    monkeypatch.setattr(Service, "tick", process)
    app = create_app(data, TOKEN, worker=True)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(Settings(poll_seconds=3600, connections_enabled=networking))
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as client:
        response = client.post("/api/worker/start")
        assert response.status_code == 200
        assert response.json()["automation_enabled"]
        assert response.json()["connections_enabled"] == networking
        assert called.wait(5), "Start must not wait for the hourly polling interval"
    assert len(calls) == 1


def test_repeated_start_serialises_cycles_and_resumes_after_pause(data, profile, monkeypatch):
    entered, release, resumed = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def process(self, operation, *, stopping):
        calls.append(threading.get_ident())
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        else:
            resumed.set()
        return {}

    monkeypatch.setattr(Service, "tick", process)
    app = create_app(data, TOKEN, worker=True)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(Settings(poll_seconds=3600))
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as client:
        assert client.post("/api/worker/start").status_code == 200
        assert entered.wait(5)
        paused = app.state.store.settings().model_copy(update={"automation_enabled": False})
        assert client.put("/api/settings", json=paused.model_dump()).status_code == 200
        assert client.post("/api/worker/start").status_code == 200
        assert client.post("/api/worker/start").status_code == 200
        assert len(calls) == 1
        release.set()
        assert resumed.wait(5)
    assert len(calls) == 2 and len(set(calls)) == 1
