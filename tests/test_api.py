from unittest.mock import MagicMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Error as BrowserError

from applicator.api import create_app, local_token
from applicator.browser import LinkedInBrowser
from applicator.models import Advice, Settings, State

TOKEN = "test-only-local-token-01234567890123456789"


def client(data):
    app = create_app(data, TOKEN)
    return app, TestClient(app, headers={"Authorization": "Bearer " + TOKEN})


@pytest.mark.parametrize("limit", [1, 5, 10])
def test_contact_discovery_uses_saved_limit_and_excludes_existing_contacts(
    data, profile, monkeypatch, limit
):
    app, session = client(data)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(Settings(linkedin_authorised=True, daily_connection_limit=limit))
    for slug, receipt in [("queued", "queued"), ("sent", "fixture:pending"), ("uncertain", None)]:
        app.state.network.add(f"https://www.linkedin.com/in/{slug}/", slug, "Recruiter", "Ireland")
        if receipt != "queued":
            app.state.network.finish(app.state.network.list()[0]["id"], receipt)
    before = app.state.network.list()
    discover = Mock(return_value=[])
    monkeypatch.setattr(LinkedInBrowser, "contacts", discover)
    assert session.post("/api/discover/contacts").json() == {"reviewed": 0}
    discover.assert_called_once_with("Ireland", limit, exclude_urls={row["url"] for row in before})
    assert app.state.network.list() == before


def test_background_contact_discovery_uses_remaining_quota_without_three_contact_cap(
    data, profile, monkeypatch
):
    app, session = client(data)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(
        Settings(
            linkedin_authorised=True,
            automation_enabled=True,
            connections_enabled=True,
            discovery_enabled=True,
            daily_connection_limit=5,
        )
    )
    app.state.network.add("https://www.linkedin.com/in/sent/", "Sent", "Recruiter", "Ireland")
    row = app.state.network.reserve(1)
    app.state.network.finish(1, "fixture:pending", run_id=row["run_id"])
    discover = Mock(return_value=[])
    monkeypatch.setattr(LinkedInBrowser, "contacts", discover)
    monkeypatch.setattr(LinkedInBrowser, "search", Mock(return_value=[]))
    monkeypatch.setattr(app.state.service, "tick", Mock(return_value={}))
    assert session.post("/api/worker/tick").status_code == 200
    discover.assert_called_once_with(
        "Ireland", 4, exclude_urls={"https://www.linkedin.com/in/sent/"}
    )


def test_auth_host_origin_and_security_headers(data):
    _, session = client(data)
    assert session.get("/api/health").status_code == 200
    assert session.get("/api/settings", headers={"Authorization": "invalid"}).status_code == 401
    assert session.get("/api/settings", headers={"Host": "evil.test"}).status_code == 403
    assert (
        session.put("/api/settings", headers={"Origin": "https://evil.test"}, json={}).status_code
        == 403
    )
    assert session.get("/api/settings", headers={"Origin": "http://testserver"}).status_code == 200
    assert session.post("/api/jobs", content="x" * 500_001).status_code == 413
    response = session.get("/")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert '<html lang="en-GB">' in response.text
    assert session.get("/api/profile").status_code == 409


def test_profile_evidence_and_settings_crud(data, profile):
    _, session = client(data)
    assert session.put("/api/profile", json=profile.model_dump()).json()["revision"] == 1
    assert session.get("/api/profile").json()["profile"]["name"] == profile.name
    evidence = profile.evidence[0].model_copy(
        update={"id": "qualification", "category": "education"}
    )
    assert session.post("/api/evidence", json=evidence.model_dump()).status_code == 200
    assert session.post("/api/evidence", json=evidence.model_dump()).status_code == 409
    assert session.delete("/api/evidence/qualification").status_code == 200
    assert session.delete("/api/evidence/missing").status_code == 404
    settings = session.get("/api/settings").json()
    settings["daily_limit"] = 10
    assert session.put("/api/settings", json=settings).status_code == 200
    settings["auto_threshold"] = 1
    assert session.put("/api/settings", json=settings).status_code == 422


def test_application_documents_and_manual_outcome(data, profile, job):
    _, session = client(data)
    session.put("/api/profile", json=profile.model_dump())
    app_id = session.post("/api/jobs", json=job.model_dump()).json()["id"]
    assert session.post("/api/jobs", json=job.model_dump()).json()["created"] is False
    assert session.get("/api/applications/999").status_code == 404
    assert session.get("/api/applications").json()[0]["id"] == app_id
    assert session.post(f"/api/applications/{app_id}/prepare", json={}).status_code == 200
    assert session.get(f"/api/applications/{app_id}/documents/cv_pdf").content.startswith(b"%PDF")
    assert session.get(f"/api/applications/{app_id}/documents/missing").status_code == 404
    assert session.post(f"/api/applications/{app_id}/submit").status_code == 409
    assert (
        session.post(
            f"/api/applications/{app_id}/receipt", json={"receipt": "manual-receipt"}
        ).status_code
        == 200
    )
    assert (
        session.post(
            f"/api/applications/{app_id}/outcome", json={"outcome": "interview"}
        ).status_code
        == 200
    )
    assert session.get("/api/insights").json()["outcomes"]["interview"] == 1
    assert session.get("/api/events").json()
    profile.phone = "+353 00 111 1111"
    session.put("/api/profile", json=profile.model_dump())
    assert session.get(f"/api/applications/{app_id}/documents/cv_pdf").content.startswith(b"%PDF")
    assert session.post("/api/worker/tick").json() == {}


def test_ai_prepare_no_key_mock_success_and_failure(data, profile, job, monkeypatch):
    import applicator.api as module

    _, session = client(data)
    session.put("/api/profile", json=profile.model_dump())
    app_id = session.post("/api/jobs", json=job.model_dump()).json()["id"]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert (
        session.post(f"/api/applications/{app_id}/prepare", json={"use_ai": True}).status_code
        == 503
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.setattr(module, "OpenAI", MagicMock())

    def selected(_client, _profile, _job, _model, *, metadata):
        metadata.update(
            method="openai",
            requested_model="gpt-6.1-sol",
            model="gpt-6.1-sol",
            response_id="resp_fixture",
        )
        return Advice(evidence_ids=["python"], explanation="Relevant")

    monkeypatch.setattr(module, "advise", Mock(side_effect=selected))
    assert (
        session.post(f"/api/applications/{app_id}/prepare", json={"use_ai": True}).status_code
        == 200
    )
    monkeypatch.setattr(module, "advise", Mock(side_effect=ValueError("refused")))
    assert (
        session.post(f"/api/applications/{app_id}/prepare", json={"use_ai": True}).status_code
        == 502
    )


def test_discovery_and_network_queue(data, profile, job, monkeypatch):
    import applicator.api as module

    app, session = client(data)
    session.put("/api/profile", json=profile.model_dump())
    monkeypatch.setattr(module, "greenhouse", Mock(return_value=[job]))
    assert (
        session.post("/api/discover/greenhouse", json={"board": "sample"}).json()["imported"] == 1
    )
    monkeypatch.setattr(module, "greenhouse", Mock(side_effect=httpx.ConnectError("offline")))
    assert session.post("/api/discover/greenhouse", json={"board": "sample"}).status_code == 502
    assert session.post("/api/discover/linkedin").status_code == 409
    assert session.post("/api/discover/contacts").status_code == 409
    settings = session.get("/api/settings").json()
    settings["linkedin_authorised"] = True
    session.put("/api/settings", json=settings)
    monkeypatch.setattr(module.LinkedInBrowser, "search", Mock(return_value=[job]))
    assert session.post("/api/discover/linkedin").status_code == 200
    target = {
        "url": "https://www.linkedin.com/in/example-recruiter/",
        "name": "Example Recruiter",
        "role": "Technical Recruiter",
        "location": "Dublin, Ireland",
    }
    monkeypatch.setattr(module.LinkedInBrowser, "contacts", Mock(return_value=[target]))
    assert session.post("/api/discover/contacts").json()["reviewed"] == 1
    assert session.post("/api/connections", json=target).status_code == 200
    assert len(session.get("/api/connections").json()) == 1
    manual_send = Mock(return_value="fixture:manual-invitation")
    monkeypatch.setattr(app.state.network, "send", manual_send)
    assert session.post("/api/connections/1/send").json()["receipt"] == "fixture:manual-invitation"
    manual_send.assert_called_once_with(1, manual=True)


def test_local_token_persisted_env_and_short_rejected(data, monkeypatch):
    monkeypatch.delenv("APPLICATOR_TOKEN", raising=False)
    first = local_token(data)
    assert len(first) >= 32 and local_token(data) == first
    monkeypatch.setenv("APPLICATOR_TOKEN", TOKEN)
    assert local_token(data) == TOKEN
    monkeypatch.setenv("APPLICATOR_TOKEN", "short")
    with pytest.raises(ValueError):
        local_token(data)


def test_lifespan_recovers_crash(data, profile, job):
    app, session = client(data)
    store = app.state.store
    store.save_profile(profile)
    from applicator.models import Settings

    store.set_settings(Settings(automation_enabled=True))
    app_id, _ = store.add_job(job)
    app.state.service.prepare(app_id)
    store.reserve(app_id, 1)
    with session:
        assert store.application(app_id)["state"] == State.UNCERTAIN


@pytest.mark.parametrize("operation", ["contacts", "jobs", "invitation"])
def test_browser_errors_are_actionable_json_without_raw_provider_details(
    data, profile, monkeypatch, operation
):
    import applicator.api as module

    app, session = client(data)
    session.put("/api/profile", json=profile.model_dump())
    settings = session.get("/api/settings").json()
    settings["linkedin_authorised"] = True
    session.put("/api/settings", json=settings)
    failure = Mock(side_effect=BrowserError("private-provider-diagnostic-cookie-and-member-url"))
    if operation == "contacts":
        monkeypatch.setattr(module.LinkedInBrowser, "contacts", failure)
        path = "/api/discover/contacts"
    elif operation == "jobs":
        monkeypatch.setattr(module.LinkedInBrowser, "search", failure)
        path = "/api/discover/linkedin"
    else:
        monkeypatch.setattr(app.state.network, "send", failure)
        path = "/api/connections/1/send"
    response = session.post(path)
    assert response.status_code == 502
    assert "browser could not" in response.json()["detail"]
    if operation == "jobs":
        assert "No opportunities were imported or applications sent" in response.json()["detail"]
    else:
        assert "uncertain applications or invitations" in response.json()["detail"]
    assert "private-provider" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert app.state.network.list() == []
    assert app.state.store.daily_usage().used == 0
    assert app.state.store.applications() == []
