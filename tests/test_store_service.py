from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from applicator.documents import validate_manifest
from applicator.models import Settings, State
from applicator.service import Service
from applicator.store import Store, day_key


class Success:
    def submit(self, job, answers, folder):
        return "fixture:receipt"


class Failure:
    def submit(self, job, answers, folder):
        raise TimeoutError("Receipt unknown")


def setup(data, profile, job, adapter=None):
    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id, _ = store.add_job(job)
    service = Service(store, data, {"fixture": adapter or Success()})
    service.prepare(app_id)
    return store, service, app_id


def test_success_deduplication_and_receipt(data, profile, job):
    store, service, app_id = setup(data, profile, job)
    assert store.add_job(job) == (app_id, False)
    other = job.model_copy(
        update={"source": "manual", "source_id": "different", "url": job.url + "?tracking=1"}
    )
    assert store.add_job(other) == (app_id, False)
    assert service.submit(app_id) == "fixture:receipt"
    assert store.application(app_id)["state"] == State.SUBMITTED
    with pytest.raises(ValueError):
        service.submit(app_id)
    with pytest.raises(ValueError):
        service.prepare(app_id)
    store.outcome(app_id, "interview")
    assert store.application(app_id)["outcome"] == "interview"
    assert store.events()


def test_unknown_receipt_cannot_retry(data, profile, job):
    store, service, app_id = setup(data, profile, job, Failure())
    with pytest.raises(TimeoutError):
        service.submit(app_id)
    assert store.application(app_id)["state"] == State.UNCERTAIN
    with pytest.raises(ValueError):
        service.submit(app_id)
    store.reconcile(app_id, "Candidate confirmed external receipt")
    assert store.application(app_id)["state"] == State.SUBMITTED


def test_empty_receipt_is_uncertain(data, profile, job):
    class Empty:
        def submit(self, *args):
            return ""

    store, service, app_id = setup(data, profile, job, Empty())
    with pytest.raises(ValueError, match="receipt"):
        service.submit(app_id)
    assert store.application(app_id)["state"] == State.UNCERTAIN


def test_profile_revision_invalidates_materials(data, profile, job):
    store, service, app_id = setup(data, profile, job)
    store.save_profile(profile)
    assert store.application(app_id)["manifest"] == {}
    with pytest.raises(ValueError):
        service.submit(app_id)
    service.prepare(app_id)
    assert service.submit(app_id)


def test_reservation_recovery_and_limit(data, profile, job):
    store, service, app_id = setup(data, profile, job)
    store.set_settings(Settings(automation_enabled=True, daily_limit=1))
    store.reserve(app_id, 1)
    assert store.recover() == 1
    assert store.recover() == 0
    another = job.model_copy(update={"source_id": "2", "url": "http://127.0.0.1:9999/another"})
    second, _ = store.add_job(another)
    service.prepare(second)
    with pytest.raises(ValueError, match="Daily"):
        store.reserve(second, 1)


def test_parallel_reservation_has_one_winner(data, profile, job):
    store, _, app_id = setup(data, profile, job)

    def reserve():
        try:
            return store.reserve(app_id, 1)
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: reserve(), range(4)))
    assert sum(result is not None for result in results) == 1


def test_pause_unsupported_provider_and_tick(data, profile, job):
    store, service, app_id = setup(data, profile, job)
    store.set_settings(Settings())
    assert service.tick() == {}
    with pytest.raises(ValueError, match="paused"):
        service.submit(app_id)
    store.set_settings(Settings(automation_enabled=True))
    service.adapters = {}
    with pytest.raises(ValueError, match="adapter"):
        service.submit(app_id)
    assert service.tick() == {str(app_id): "ValueError"}


def test_tampered_missing_and_traversal_documents(data, profile, job):
    store, service, app_id = setup(data, profile, job)
    row = store.application(app_id)
    folder = data / "documents" / str(app_id)
    validate_manifest(row["manifest"], folder, 1)
    with pytest.raises(ValueError):
        validate_manifest(row["manifest"], folder, 2)
    item = row["manifest"]["files"]["cv_pdf"]
    (folder / item["name"]).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        service.submit(app_id)
    item["name"] = "../escape.pdf"
    with pytest.raises(ValueError):
        validate_manifest(row["manifest"], folder, 1)


def test_store_error_branches(data, profile, job):
    store = Store(data / "db.sqlite3")
    with pytest.raises(ValueError):
        store.profile()
    with pytest.raises(KeyError):
        store.application(999)
    store.save_profile(profile)
    app_id, _ = store.add_job(job)
    with pytest.raises(KeyError):
        store.prepare(999, 1, "{}", State.READY, {})
    with pytest.raises(ValueError):
        store.prepare(app_id, 2, "{}", State.READY, {})
    with pytest.raises(ValueError):
        store.outcome(app_id, "offer")
    with pytest.raises(ValueError):
        store.reconcile(999, "receipt")
    store.reconcile(app_id, "manual")
    with pytest.raises(ValueError):
        store.prepare(app_id, 1, "{}", State.READY, {})
    with pytest.raises(ValueError):
        store.reconcile(app_id, "receipt")


def test_prepare_without_evidence_and_sponsorship(data, profile, job):
    profile.confirmed = False
    store, service, app_id = setup(data, profile, job)
    assert store.application(app_id)["manifest"] == {}
    profile.confirmed = True
    store.save_profile(profile)
    job.source = "linkedin"
    job.url = "https://www.linkedin.com/jobs/view/123/"
    job.source_id = "123"
    linkedin_id, _ = store.add_job(job)
    service.adapters["linkedin"] = Success()
    service.prepare(linkedin_id)
    with pytest.raises(ValueError, match="authorisation"):
        service.submit(linkedin_id)


def test_reserve_rechecks_current_threshold(data, profile, job):
    job.requirements = ["Python", "FastAPI", "PostgreSQL", "Azure"]
    store, _, app_id = setup(data, profile, job)
    store.set_settings(Settings(automation_enabled=True, auto_threshold=100))
    with pytest.raises(ValueError, match="Current policy"):
        store.reserve(app_id, 1)


def test_london_daily_boundary():
    assert day_key(datetime(2026, 7, 1, 23, 30, tzinfo=UTC)) == "2026-07-02"
    assert day_key(datetime(2026, 1, 1, 23, 30, tzinfo=UTC)) == "2026-01-01"
