from unittest.mock import Mock

from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.browser import ReviewRequired
from applicator.models import Settings, State
from applicator.service import Service
from applicator.store import Store


def test_unknown_provider_question_becomes_review_and_can_resume(data, profile, job):
    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id, _ = store.add_job(job)
    adapter = Mock()
    adapter.submit.side_effect = ReviewRequired("Approve an exact answer for: Expected salary?")
    service = Service(store, data, {"fixture": adapter})
    service.prepare(app_id)
    try:
        service.submit(app_id)
    except ReviewRequired:
        pass
    row = store.application(app_id)
    assert row["state"] == State.REVIEW
    assert row["job"]["questions"][0]["answer_key"] == "question:expected salary?"
    profile.answers["question:expected salary?"] = "To be discussed"
    store.save_profile(profile)
    service.prepare(app_id)
    adapter.submit.side_effect = None
    adapter.submit.return_value = "fixture:confirmed"
    assert service.submit(app_id) == "fixture:confirmed"


def test_worker_discovers_prepares_and_holds(data, profile, job, monkeypatch):
    import applicator.api as module

    token = "test-worker-local-token-01234567890123456789"
    app = create_app(data, token)
    store = app.state.store
    store.save_profile(profile)
    store.set_settings(
        Settings(automation_enabled=True, linkedin_authorised=True, discovery_enabled=True)
    )
    monkeypatch.setattr(module.LinkedInBrowser, "search", Mock(return_value=[job]))
    session = TestClient(app, headers={"Authorization": "Bearer " + token})
    response = session.post("/api/worker/tick")
    assert response.status_code == 200
    assert store.applications()[0]["state"] == State.READY
    store.set_settings(
        Settings(automation_enabled=True, connections_enabled=True, linkedin_authorised=True)
    )
    app.state.network.add("https://www.linkedin.com/in/example/", "Example", "Recruiter", "Ireland")
    monkeypatch.setattr(app.state.network, "send", Mock(side_effect=ValueError("review")))
    assert session.post("/api/worker/tick").json()["connection:1"] == "ValueError"


def test_networking_discovery_is_separately_controlled(data, profile, monkeypatch):
    import applicator.api as module

    token = "test-networking-cycle-token-01234567890123456789"
    app = create_app(data, token)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(
        Settings(
            automation_enabled=True,
            linkedin_authorised=True,
            connections_enabled=True,
            discovery_enabled=True,
        )
    )
    monkeypatch.setattr(module.LinkedInBrowser, "search", Mock(return_value=[]))
    contact = {
        "url": "https://www.linkedin.com/in/example/",
        "name": "Example",
        "role": "Recruiter",
        "location": "Ireland",
    }
    monkeypatch.setattr(module.LinkedInBrowser, "contacts", Mock(return_value=[contact]))
    monkeypatch.setattr(app.state.network, "send", Mock(return_value="confirmed"))
    session = TestClient(app, headers={"Authorization": "Bearer " + token})
    assert session.post("/api/worker/tick").json()["connection:1"] == "confirmed"
    assert app.state.network.list()[0]["name"] == "Example"
