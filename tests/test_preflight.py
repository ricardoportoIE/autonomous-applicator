"""Read-only diagnostics and accounting never authorise or perform an external action."""

import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.models import Question, Settings, State
from applicator.service import Service
from applicator.store import Store

TOKEN = "test-only-diagnostics-token-01234567890123456789"


def ready(data, profile, job):
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True))
    app_id, _ = store.add_job(job)
    adapter = Mock()
    service = Service(store, data, {job.source: adapter})
    service.prepare(app_id)
    return store, service, app_id, adapter


def blocked(report):
    return {item.code for item in report.checks if not item.passed}


def test_ready_preflight_is_read_only_and_leaves_adapter_unused(data, profile, job):
    store, service, app_id, adapter = ready(data, profile, job)
    before = (store.application(app_id), store.events(), store.daily_usage())
    report = service.preflight(app_id)
    assert report.can_submit and report.evaluation.score == 100
    assert not blocked(report)
    assert report.checked_at.endswith("+00:00")
    assert (store.application(app_id), store.events(), store.daily_usage()) == before
    adapter.submit.assert_not_called()
    assert profile.email not in report.model_dump_json()


def test_preflight_reports_pause_scope_and_manual_hand_off(data, profile, job):
    job.source = "linkedin"
    job.url = "https://www.linkedin.com/jobs/view/123/"
    job.source_id = "123"
    store, service, app_id, _ = ready(data, profile, job)
    store.set_settings(Settings())
    report = service.preflight(app_id, set())
    assert not report.can_submit
    assert blocked(report) == {"automation", "scope", "adapter"}


def test_preflight_reports_missing_unconfirmed_and_stale_profile(data, profile, job):
    store = Store(data / "applicator.sqlite3")
    app_id, _ = store.add_job(job)
    service = Service(store, data)
    assert "profile" in blocked(service.preflight(app_id))
    store.save_profile(profile)
    service.prepare(app_id)
    profile.confirmed = False
    store.save_profile(profile)
    assert {"profile", "policy", "revision", "documents", "state"} <= blocked(
        service.preflight(app_id)
    )


@pytest.mark.parametrize("kind", ["missing", "modified", "outdated", "no_cover"])
def test_preflight_detects_invalid_materials_without_changing_the_record(data, profile, job, kind):
    job.cover_letter_required = True
    store, service, app_id, adapter = ready(data, profile, job)
    row = store.application(app_id)
    cv = data / "documents" / str(app_id) / row["manifest"]["files"]["cv_pdf"]["name"]
    if kind == "missing":
        cv.unlink()
    elif kind == "modified":
        cv.write_bytes(b"changed")
    else:
        manifest = row["manifest"]
        if kind == "outdated":
            manifest["revision"] = 0
        else:
            del manifest["files"]["cover_pdf"]
        with store.connect() as db:
            db.execute(
                "UPDATE applications SET manifest=? WHERE id=?", (json.dumps(manifest), app_id)
            )
    assert "documents" in blocked(service.preflight(app_id))
    assert store.application(app_id)["state"] == State.READY
    with pytest.raises((ValueError, FileNotFoundError)):
        service.submit(app_id)
    assert store.daily_usage().used == 0
    adapter.submit.assert_not_called()


def test_question_and_changed_policy_are_explained(data, profile, job):
    store, service, app_id, _ = ready(data, profile, job)
    job.questions = [Question(id="salary", label="Expected salary?")]
    job.location = "Toronto, Canada"
    store.update_job(app_id, job)
    report = service.preflight(app_id)
    assert {"policy", "questions", "state", "documents", "revision"} <= blocked(report)
    assert "salary" in next(item.detail for item in report.checks if item.code == "questions")
    assert "Location needs candidate confirmation." in report.evaluation.blockers


@pytest.mark.parametrize(
    "url",
    [
        "https://example.test/jobs/view/123/",
        "https://www.linkedin.com:8443/jobs/view/123/",
        "https://www.linkedin.com/jobs/view/456/",
    ],
)
def test_invalid_linkedin_targets_are_blocked_before_reserving(data, profile, job, url):
    job.source, job.source_id, job.url = "linkedin", "123", url
    store, service, app_id, adapter = ready(data, profile, job)
    assert "target" in blocked(service.preflight(app_id))
    with pytest.raises(ValueError, match="LinkedIn"):
        service.submit(app_id)
    assert store.daily_usage().used == 0
    adapter.submit.assert_not_called()


def test_daily_usage_separates_uncertain_capacity_from_confirmed_sends(
    data, profile, job, monkeypatch
):
    import applicator.store as module

    monkeypatch.setattr(module, "day_key", lambda: "2026-10-02")
    store, service, app_id, _ = ready(data, profile, job)
    store.set_settings(Settings(automation_enabled=True, daily_limit=1))
    attempt = store.reserve(app_id, 1)
    store.finish(app_id, attempt, None)
    usage = store.daily_usage()
    assert (usage.used, usage.held, usage.limit, usage.remaining, usage.timezone) == (
        0,
        1,
        1,
        0,
        "Europe/London",
    )
    assert {"quota", "state"} <= blocked(service.preflight(app_id))
    monkeypatch.setattr(module, "day_key", lambda: "2026-10-03")
    assert store.daily_usage().remaining == 0 and store.daily_usage().used == 0
    assert store.daily_usage().held == 1


def test_daily_usage_handles_lowered_limit_and_submission_rechecks_snapshot(data, profile, job):
    store, service, app_id, adapter = ready(data, profile, job)
    assert service.preflight(app_id).can_submit
    store.set_settings(Settings())
    with pytest.raises(ValueError, match="paused"):
        service.submit(app_id)
    adapter.submit.assert_not_called()
    with store.connect() as db:
        db.executemany(
            "INSERT INTO attempts(application_id,day,started) VALUES(?,?,?)",
            [(app_id, store.daily_usage().day, "test")] * 12,
        )
    assert store.daily_usage().remaining == 0
    assert store.daily_usage().used == 0 and store.daily_usage().held == 12


def test_application_events_include_older_entries_and_exclude_other_records(data, profile, job):
    store, _, app_id, _ = ready(data, profile, job)
    second = job.model_copy(update={"source_id": "second", "url": "https://example.test/second"})
    other, _ = store.add_job(second)
    with store.connect() as db:
        for _ in range(205):
            store.event(db, "other_event", "Unrelated activity", other)
    timeline = store.events(app_id)
    assert [row["kind"] for row in timeline] == [
        "application_run_finished",
        "application_processing_result",
        "materials_prepared",
        "application_stage",
        "application_stage",
        "application_stage",
        "application_run_started",
        "job_added",
    ]
    assert all(row["application_id"] == app_id for row in timeline)
    assert len(store.events()) == len(store.events(other)) == 200
    with pytest.raises(KeyError):
        store.events(999)


def test_application_listing_uses_one_database_connection(data, profile, job, monkeypatch):
    store, _, app_id, _ = ready(data, profile, job)
    original = store.connect
    connections = []

    @contextmanager
    def counted():
        connections.append(True)
        with original() as db:
            yield db

    monkeypatch.setattr(store, "connect", counted)
    rows = store.applications()
    assert len(connections) == 1
    assert rows[0]["id"] == app_id and isinstance(rows[0]["job"], dict)


def test_diagnostic_endpoints_require_auth_and_do_not_mutate(data, profile, job):
    app = create_app(data, TOKEN)
    store = app.state.store
    store.save_profile(profile)
    app_id, _ = store.add_job(job)
    with TestClient(app) as client:
        for path in [
            "/api/usage",
            f"/api/applications/{app_id}/preflight",
            f"/api/applications/{app_id}/events",
        ]:
            assert client.get(path).status_code == 401
        client.headers["Authorization"] = "Bearer " + TOKEN
        before = store.events()
        assert client.get("/api/usage").json()["used"] == 0
        assert not client.get(f"/api/applications/{app_id}/preflight").json()["can_submit"]
        assert client.get(f"/api/applications/{app_id}/events").json()[0]["kind"] == "job_added"
        assert store.events() == before
        assert client.get("/api/applications/999/preflight").status_code == 404
        assert client.get("/api/applications/999/events").status_code == 404
