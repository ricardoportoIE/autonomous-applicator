"""Submission snapshots preserve sent materials without inventing historical evidence."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_api import client
from test_store_service import setup

from applicator.browser import FixtureBrowser, LinkedInBrowser, ReviewRequired
from applicator.models import Question, Settings, State
from applicator.submission_records import capture_confirmation

PNG = b"\x89PNG\r\n\x1a\nfixture-confirmation"


def test_confirmed_snapshot_survives_changed_profile_and_source_documents(data, profile, job):
    job.questions = [
        Question(id="sponsorship", label="Sponsorship required?", answer_key="sponsorship")
    ]
    store, service, app_id = setup(data, profile, job)
    assert service.submit(app_id)
    record = service.records.read(app_id)
    attempt = record["attempts"][0]
    assert attempt["status"] == "confirmed" and attempt["confirmed_at"]
    assert record["dates"]["submitted_at"] and record["dates"]["prepared_at"]
    assert attempt["snapshot"]["provided_answers"][0]["answer"] == "Yes"
    assert attempt["snapshot"]["selected_evidence"][0]["text"] == profile.evidence[0].text
    archived = service.records.artifact(app_id, attempt["id"], "cv_pdf")
    content = archived.read_bytes()
    original = data / "documents" / str(app_id) / archived.name
    original.write_bytes(b"a later CV")
    profile.email = "changed@example.test"
    profile.evidence[0].text = "A later candidate fact"
    store.save_profile(profile)
    assert service.records.artifact(app_id, attempt["id"], "cv_pdf").read_bytes() == content
    after = service.records.read(app_id)["attempts"][0]
    assert after["snapshot"] == attempt["snapshot"]
    assert after["snapshot"]["candidate"]["email"] == "alex@example.test"
    assert after["fields"] == [] and after["confirmation"] == {}
    with pytest.raises(KeyError):
        service.records.artifact(app_id, attempt["id"], "confirmation")


def test_adapter_uses_archived_materials_and_preserves_both_retry_snapshots(data, profile, job):
    folders = []

    class Provider:
        def submit(self, vacancy, answers, folder):
            folders.append(folder)
            cv = next(folder.glob("*_CV.pdf"))
            (data / "documents" / "1" / cv.name).write_bytes(b"changed source")
            assert cv.read_bytes().startswith(b"%PDF")
            if len(folders) == 1:
                raise ReviewRequired("Approve the new provider question")
            return "fixture:retry-confirmed"

    store, service, app_id = setup(data, profile, job, Provider())
    with pytest.raises(ReviewRequired):
        service.submit(app_id)
    first = service.records.read(app_id)["attempts"][0]
    assert first["status"] == "released" and first["confirmed_at"] is None
    service.prepare(app_id)
    assert service.submit(app_id) == "fixture:retry-confirmed"
    attempts = service.records.read(app_id)["attempts"]
    assert [item["status"] for item in attempts] == ["confirmed", "released"]
    assert folders[0] != folders[1] and "submissions" in folders[0].parts
    assert service.records.artifact(app_id, first["id"], "cv_pdf").read_bytes().startswith(b"%PDF")


def test_observed_values_are_actual_choices_per_step_and_immutable_after_confirmation(
    data, profile, job
):
    store, service, app_id = setup(data, profile, job)
    row = store.application(app_id)
    attempt = store.reserve(app_id, 1)
    service.records.begin(app_id, attempt, profile, 1, job, row["manifest"], {})
    service.records.observe(
        app_id,
        attempt,
        [
            {
                "step": 1,
                "label": "No",
                "group": "Need sponsorship?",
                "type": "radio",
                "checked": False,
            },
            {
                "step": 1,
                "label": "Yes",
                "group": "Need sponsorship?",
                "type": "radio",
                "checked": True,
            },
            {"step": 1, "label": "Email", "type": "text", "value": "corrected@example.test"},
            {"step": 2, "label": "Email", "type": "text", "value": "second@example.test"},
            {"step": 2, "label": "Follow employer", "type": "checkbox", "checked": False},
        ],
    )
    service.records.observe(
        app_id,
        attempt,
        [{"step": 1, "label": "Email", "type": "text", "value": "final@example.test"}],
    )
    store.mark_sending(app_id, attempt, 1, job)
    store.finish(app_id, attempt, "fixture:observed")
    observed = service.records.read(app_id)["attempts"][0]
    assert observed["sent_at"] and observed["confirmed_at"]
    fields = observed["fields"]
    assert len(fields) == 4
    assert fields[0]["label"] == "Need sponsorship?" and fields[0]["value"] == "Yes"
    assert fields[1]["value"] == "final@example.test" and fields[2]["step"] == 2
    assert fields[3]["checked"] is False
    with pytest.raises(ValueError, match="no longer"):
        service.records.observe(app_id, attempt, [])


def test_uncertain_record_reconciles_without_fabricating_a_screenshot(data, profile, job):
    class Uncertain:
        def submit(self, *args):
            raise TimeoutError("No confirmation")

    store, service, app_id = setup(data, profile, job, Uncertain())
    with pytest.raises(TimeoutError):
        service.submit(app_id)
    attempt = service.records.read(app_id)["attempts"][0]
    assert attempt["status"] == "held" and attempt["confirmed_at"] is None
    with pytest.raises(ValueError, match="confirmed receipt"):
        service.records.confirmation(app_id, attempt["id"], {"name": "confirmation.png"})
    store.reconcile(app_id, "Candidate checked the actual provider receipt")
    reconciled = service.records.read(app_id)["attempts"][0]
    assert reconciled["confirmed_at"] and reconciled["confirmation"] == {}
    assert service.records.read(app_id)["dates"]["submitted_at"]


def test_historical_attempt_and_complete_paginated_journal(data, profile, job):
    store, service, app_id = setup(data, profile, job)
    attempt = store.reserve(app_id, 1)
    store.finish(app_id, attempt, "historical:receipt")
    for index in range(220):
        with store.connect() as db:
            store.event(db, "fixture_history", str(index), app_id)
    first = service.records.read(app_id)
    assert first["attempts"][0]["snapshot"] is None
    assert first["attempts"][0]["confirmation"] is None
    assert first["attempts"][0]["receipt"] == "historical:receipt"
    assert len(first["events"]) == 200 and first["next_event"]
    second = service.records.read(app_id, first["next_event"])
    assert not second["next_event"]
    assert len(first["events"] + second["events"]) == first["dates"]["event_count"]
    assert (
        len({item["id"] for item in first["events"] + second["events"]})
        == first["dates"]["event_count"]
    )
    assert not service.records.read(app_id, 1)["events"]
    with pytest.raises(KeyError):
        service.records.read(999)


@pytest.mark.parametrize("failure", ["archive", "begin"])
def test_archive_failure_stops_before_provider_action(data, profile, job, monkeypatch, failure):
    adapter = Mock()
    store, service, app_id = setup(data, profile, job, adapter)
    if failure == "archive":
        monkeypatch.setattr(
            service.records, "folder", Mock(side_effect=OSError("Disk unavailable"))
        )
    else:
        monkeypatch.setattr(
            service.records, "begin", Mock(side_effect=ValueError("Invalid materials"))
        )
    with pytest.raises((OSError, ValueError)):
        service.submit(app_id)
    adapter.submit.assert_not_called()
    assert store.application(app_id)["state"] == State.REVIEW
    assert store.daily_usage().held == 0


@pytest.mark.parametrize("tamper", ["hash", "missing", "oversize", "path", "foreign", "unknown"])
def test_authenticated_archived_artifacts_reject_corruption_and_cross_application_access(
    data, profile, job, tamper
):
    app, session = client(data)
    store, service = app.state.store, app.state.service
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id, _ = store.add_job(job)
    service.adapters["fixture"] = SimpleNamespace(submit=lambda *args: "fixture:receipt")
    service.prepare(app_id)
    service.submit(app_id)
    attempt = service.records.read(app_id)["attempts"][0]
    target = service.records.artifact(app_id, attempt["id"], "cv_pdf")
    key = "cv_pdf"
    if tamper == "hash":
        target.write_bytes(b"tampered")
    elif tamper == "missing":
        target.unlink()
    elif tamper == "oversize":
        target.write_bytes(b"x" * 10_000_001)
    elif tamper == "path":
        snapshot = attempt["snapshot"]
        snapshot["manifest"]["files"][key]["name"] = "../escape.pdf"
        with store.connect() as db:
            db.execute(
                "UPDATE submission_records SET snapshot=? WHERE attempt_id=?",
                (json.dumps(snapshot), attempt["id"]),
            )
    elif tamper == "foreign":
        other = job.model_copy(update={"source_id": "other", "url": job.url + "/other"})
        app_id, _ = store.add_job(other)
    else:
        key = "unknown"
    url = f"/api/applications/{app_id}/submissions/{attempt['id']}/artifacts/{key}"
    assert session.get(url, headers={"Authorization": "invalid"}).status_code == 401
    assert session.get(url).status_code in {404, 409}
    assert session.get(f"/api/applications/{app_id}/record?before=0").status_code == 422
    assert (
        session.get(
            f"/api/applications/{app_id}/record", headers={"Authorization": "invalid"}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "mode", ["success", "exception", "invalid_png", "oversize", "unsafe_url", "existing", "none"]
)
def test_capture_is_bounded_private_and_never_raises(tmp_path, monkeypatch, mode):
    page = Mock(url="https://www.linkedin.com/jobs/view/123/")
    page.screenshot.return_value = PNG
    folder = tmp_path / "evidence"
    if mode == "exception":
        page.screenshot.side_effect = OSError("private diagnostic")
    elif mode == "invalid_png":
        page.screenshot.return_value = b"not a PNG"
    elif mode == "oversize":
        monkeypatch.setattr("applicator.submission_records.MAX_SCREENSHOT_BYTES", 8)
    elif mode == "unsafe_url":
        page.url = "https://secret:password@example.test/"
    elif mode == "existing":
        folder.mkdir()
        (folder / "confirmation.png").write_bytes(b"existing evidence")
    evidence = capture_confirmation(page, None if mode == "none" else folder)
    if mode == "success":
        assert evidence["sha256"] == hashlib.sha256(PNG).hexdigest()
        assert evidence["url"] == page.url and evidence["captured_at"]
        assert (folder / "confirmation.png").read_bytes() == PNG
    elif mode == "none":
        assert evidence == {}
        page.screenshot.assert_not_called()
    else:
        assert set(evidence) == (
            {"capture_error"} if mode == "unsafe_url" else {"url", "capture_error"}
        )
        assert "private" not in json.dumps(evidence)
        if mode == "existing":
            assert (folder / "confirmation.png").read_bytes() == b"existing evidence"


@pytest.mark.parametrize("failure", [False, True])
def test_confirmation_persistence_failure_does_not_change_success_or_retry(
    data, profile, job, monkeypatch, failure
):
    adapter = FixtureBrowser()
    store, service, app_id = setup(data, profile, job, adapter)

    def submit(vacancy, answers, folder):
        assert adapter.confirmation_folder == folder.parent
        adapter.observe_fields([{"label": "Email", "type": "text", "value": profile.email}])
        adapter.confirmation_evidence = {"capture_error": "TimeoutError"}
        return "fixture:confirmed"

    monkeypatch.setattr(adapter, "submit", submit)
    if failure:
        monkeypatch.setattr(
            service.records, "confirmation", Mock(side_effect=OSError("Disk unavailable"))
        )
    assert service.submit(app_id) == "fixture:confirmed"
    assert store.application(app_id)["state"] == State.SUBMITTED and store.daily_usage().used == 1
    assert adapter.confirmation_folder is None and adapter.observe_fields is None
    assert adapter.confirmation_evidence == {}
    record = service.records.read(app_id)["attempts"][0]
    assert record["fields"][0]["value"] == profile.email
    assert record["confirmation"] == ({} if failure else {"capture_error": "TimeoutError"})
    with pytest.raises(ValueError):
        service.submit(app_id)


def test_last_moment_archive_tampering_stops_before_submit_click(data, profile, job, monkeypatch):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    store, service, app_id = setup(data, profile, job)
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True))
    adapter = LinkedInBrowser(data, profile)
    service.adapters["linkedin"] = adapter
    clicks = []

    def form(vacancy, answers, folder, progress):
        next(folder.glob("*_CV.pdf")).write_bytes(b"corrupt archive")
        adapter.before_submit()
        clicks.append("submit")
        return "fixture:confirmed"

    monkeypatch.setattr(adapter, "_submit", form)
    with pytest.raises(ReviewRequired):
        service.submit(app_id)
    assert not clicks and store.daily_usage().held == 0
    assert store.application(app_id)["state"] == State.REVIEW


def test_confirmation_artifact_is_authenticated_and_hash_verified(data, profile, job):
    app, session = client(data)
    store, service = app.state.store, app.state.service
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id, _ = store.add_job(job)
    service.adapters["fixture"] = SimpleNamespace(submit=lambda *args: "fixture:confirmed")
    service.prepare(app_id)
    service.submit(app_id)
    attempt = service.records.read(app_id)["attempts"][0]["id"]
    evidence = capture_confirmation(
        Mock(url=job.url, screenshot=Mock(return_value=PNG)),
        service.records.folder(app_id, attempt),
    )
    service.records.confirmation(app_id, attempt, evidence)
    url = f"/api/applications/{app_id}/submissions/{attempt}/artifacts/confirmation"
    response = session.get(url)
    assert response.status_code == 200 and response.content == PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert session.get(url, headers={"Authorization": "invalid"}).status_code == 401
    assert session.get("/data/submissions/1/1/confirmation.png").status_code == 404
    assert (
        session.get(f"/api/applications/{app_id}/record").json()["attempts"][0]["confirmation"]
        == evidence
    )
    service.records.artifact(app_id, attempt, "confirmation").write_bytes(b"tampered")
    assert session.get(url).status_code == 409


def test_submission_folder_rejects_invalid_identifiers_and_external_symlink(
    data, profile, job, tmp_path
):
    _, service, _ = setup(data, profile, job)
    with pytest.raises(ValueError, match="identifier"):
        service.records.folder(0, 1)
    outside = tmp_path / "outside"
    outside.mkdir()
    submissions = data / "submissions"
    try:
        submissions.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks require an enabled Windows developer mode")
    with pytest.raises(ValueError, match="folder"):
        service.records.folder(1, 1)
