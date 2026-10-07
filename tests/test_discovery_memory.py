"""Read failures survive restart without discarding opportunities or blocking queued work."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import TimeoutError as BrowserTimeout

from applicator.api import create_app
from applicator.browser import LinkedInBrowser
from applicator.discovery_memory import DiscoveryMemory
from applicator.models import Settings
from applicator.store import Store


def test_read_memory_is_private_durable_bounded_and_expires(data, profile, job):
    store = Store(data / "db.sqlite3")
    memory = DiscoveryMemory(store)
    now = datetime(2026, 10, 7, tzinfo=UTC)
    assert memory.holds() == {} and memory.waiting_until("search", now=now) is None
    assert memory.excluded_ids(now=now) == set()
    assert (
        memory.defer("123", "private-provider-token", now=now)
        == (now + timedelta(minutes=5)).isoformat()
    )
    assert memory.holds()["123"]["error_code"] == "ReadError"
    restarted = DiscoveryMemory(Store(store.path))
    assert restarted.excluded_ids(now=now) == {"123"}
    assert restarted.waiting_until("123", now=now)
    assert restarted.waiting_until("123", now=now + timedelta(minutes=5)) is None
    assert restarted.excluded_ids(now=now + timedelta(minutes=5)) == set()
    for index, minutes in enumerate([10, 20, 40, 60, 60], start=2):
        assert (
            restarted.defer("123", "TimeoutError", now=now)
            == (now + timedelta(minutes=minutes)).isoformat()
        )
        assert restarted.holds()["123"]["failures"] == min(index, 5)
    restarted.defer("search", "ValueError", now=now)
    assert restarted.excluded_ids(now=now) == {"123"}
    store.save_profile(profile)
    known_job = job.model_copy(
        update={
            "source": "linkedin",
            "source_id": "456",
            "url": "https://www.linkedin.com/jobs/view/456/",
        }
    )
    store.add_job(known_job)
    store.add_job(job)
    assert restarted.excluded_ids(now=now, known=True) == {"123", "456"}
    assert restarted.excluded_ids(now=now, known=False) == {"123"}
    assert not store.discovery_discards() and store.daily_usage().attempts == 0
    restarted.resolved("123")
    restarted.resolved("absent")
    assert restarted.excluded_ids(now=now) == set()
    assert "private-provider-token" not in json.dumps(store.events())
    with pytest.raises(ValueError, match="identifier"):
        restarted.defer("https://external.test/", "TimeoutError")
    # Default clock and clearing an empty journal are both supported.
    other = DiscoveryMemory(Store(data / "empty.sqlite3"))
    other.resolved("search")
    other.defer("321", "Error")
    assert other.waiting_until("321") and other.excluded_ids() == {"321"}


def client(data, profile):
    app = create_app(data, "local-read-test-token")
    store = app.state.store
    store.save_profile(profile)
    store.set_settings(
        Settings(automation_enabled=True, linkedin_authorised=True, discovery_enabled=True)
    )
    return app, TestClient(app, headers={"Authorization": "Bearer local-read-test-token"})


def test_global_failure_waits_without_reopening_and_manual_search_can_retry(
    data, profile, job, monkeypatch
):
    app, session = client(data, profile)
    search = Mock(side_effect=BrowserTimeout("private-provider-token"))
    monkeypatch.setattr(LinkedInBrowser, "search", search)
    assert session.post("/api/worker/tick").status_code == 502
    memory = DiscoveryMemory(app.state.store)
    assert memory.waiting_until("search")
    assert session.post("/api/worker/tick").status_code == 200
    assert search.call_count == 1
    assert session.get("/api/worker/status").json()["run"]["stage"] == "waiting_for_discovery"
    search.side_effect = None
    search.return_value = [job]
    assert session.post("/api/discover/linkedin").json()["imported"] == 1
    assert search.call_count == 2 and memory.waiting_until("search") is None
    assert "private-provider-token" not in json.dumps(app.state.store.events())
    assert app.state.store.daily_usage().attempts == 0


def test_read_backoff_does_not_block_preparation_of_existing_work(data, profile, job, monkeypatch):
    app, session = client(data, profile)
    store = app.state.store
    memory = DiscoveryMemory(store)
    memory.defer("search", "TimeoutError")
    app_id, _ = store.add_job(job)
    search = Mock()
    monkeypatch.setattr(LinkedInBrowser, "search", search)
    assert session.post("/api/worker/tick").status_code == 200
    search.assert_not_called()
    assert store.application(app_id)["manifest"]["files"]
    assert memory.waiting_until("search")
    assert store.daily_usage().attempts == 0


def test_shared_search_filters_known_only_for_worker_and_resets_successful_read(
    data, profile, job, monkeypatch
):
    app, session = client(data, profile)
    store = app.state.store
    known = job.model_copy(
        update={
            "source": "linkedin",
            "source_id": "456",
            "url": "https://www.linkedin.com/jobs/view/456/",
        }
    )
    app_id, _ = store.add_job(known)
    # A current review hold is ineligible for automatic queue processing.
    app.state.service.prepare(app_id)
    with store.connect(True) as db:
        db.execute("UPDATE applications SET state='review' WHERE id=?", (app_id,))
    memory = DiscoveryMemory(store)
    past = datetime.now(UTC) - timedelta(hours=2)
    memory.defer("123", "ReviewRequired", now=past)
    discovered = known.model_copy(
        update={"source_id": "123", "url": "https://www.linkedin.com/jobs/view/123/"}
    )
    seen = []

    def search(self, keywords, location, *, excluded_ids):
        seen.append(excluded_ids)
        assert self.discovery_failure and self.discovery_stopping
        assert not self.discovery_stopping()
        return [discovered]

    monkeypatch.setattr(LinkedInBrowser, "search", search)
    # Keep the synthetic new result in review without opening a submission browser.
    monkeypatch.setattr(app.state.service, "tick", lambda *args, **kwargs: {})
    assert session.post("/api/worker/tick").status_code == 200
    assert seen == [{"456"}] and "123" not in memory.holds()
    assert session.post("/api/discover/linkedin").status_code == 200
    assert seen[-1] == set()
    store.set_settings(store.settings().model_copy(update={"automation_enabled": False}))
    assert session.post("/api/discover/linkedin").status_code == 200


def test_worker_pause_callback_observes_live_settings(data, profile, monkeypatch):
    app, session = client(data, profile)
    store = app.state.store

    def search(self, *args, **kwargs):
        assert not self.discovery_stopping()
        store.set_settings(store.settings().model_copy(update={"automation_enabled": False}))
        assert self.discovery_stopping()
        return []

    monkeypatch.setattr(LinkedInBrowser, "search", search)
    assert session.post("/api/worker/tick").status_code == 200
    assert session.get("/api/worker/status").json()["run"]["status"] == "paused"


def test_idle_search_explains_current_review_holds_instead_of_claiming_processing(
    data, profile, job, monkeypatch
):
    app, session = client(data, profile)
    store = app.state.store
    app_id, _ = store.add_job(job)
    app.state.service.prepare(app_id)
    with store.connect(True) as db:
        db.execute("UPDATE applications SET state='review' WHERE id=?", (app_id,))
    monkeypatch.setattr(LinkedInBrowser, "search", Mock(return_value=[]))
    assert session.post("/api/worker/tick").status_code == 200
    record = session.get("/api/worker/status").json()
    assert record["run"]["status"] == "completed"
    assert record["run"]["stage"] == "waiting_for_review"
    assert record["run"]["application_id"] is None
    assert "1 applications await review; 0 are prepared" in record["run"]["detail"]
    assert "Next scheduled search in" in record["run"]["detail"]
    assert store.daily_usage().attempts == 0


def test_discovery_callback_stops_after_server_lifespan_shutdown(data, profile, monkeypatch):
    app, session = client(data, profile)
    observed = []

    def search(self, *args, **kwargs):
        observed.append(self.discovery_stopping)
        assert not self.discovery_stopping()
        return []

    monkeypatch.setattr(LinkedInBrowser, "search", search)
    with session:
        assert session.post("/api/discover/linkedin").status_code == 200
    assert observed[0]()
