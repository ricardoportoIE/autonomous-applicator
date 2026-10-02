import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.models import State


def test_job_update_invalidates_and_preserves_identity(data, profile, job):
    token = "test-job-update-local-token-01234567890123456789"
    app = create_app(data, token)
    store = app.state.store
    store.save_profile(profile)
    app_id, _ = store.add_job(job)
    app.state.service.prepare(app_id)
    job.description += " Updated responsibilities."
    session = TestClient(app, headers={"Authorization": "Bearer " + token})
    assert session.put(f"/api/applications/{app_id}/job", json=job.model_dump()).status_code == 200
    row = store.application(app_id)
    assert row["evaluation"] == {} and row["manifest"] == {} and row["state"] == State.REVIEW
    other = job.model_copy(update={"source_id": "new-job"})
    with pytest.raises(ValueError):
        store.update_job(app_id, other)
    with pytest.raises(KeyError):
        store.update_job(999, job)
    store.reconcile(app_id, "manual-confirmation")
    assert session.put(f"/api/applications/{app_id}/job", json=job.model_dump()).status_code == 409
