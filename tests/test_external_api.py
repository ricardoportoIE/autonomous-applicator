"""API routing for two specialised executors, with no external account actions."""

from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from applicator.api import create_app
from applicator.browser import LinkedInBrowser
from applicator.external_browser import ExternalBrowser, SitePlan
from applicator.models import Settings, State

TOKEN = "external-fixture-local-token-01234567890123456789"
URL = "https://jobs.lever.co/example/123"


@pytest.fixture
def api(data, profile, job):
    job.source, job.source_id, job.url = "permitted", "123", URL
    app = create_app(data, TOKEN)
    app.state.store.save_profile(profile)
    app.state.store.set_settings(
        Settings(
            automation_enabled=True, external_applications_enabled=True, linkedin_authorised=True
        )
    )
    with TestClient(app, headers={"Authorization": "Bearer " + TOKEN}) as client:
        yield app, client, job


def test_external_import_is_read_only_and_uses_published_details(api, monkeypatch):
    app, client, job = api
    read = Mock(return_value=job)
    monkeypatch.setattr(ExternalBrowser, "read_opportunity", read)
    assert client.post("/api/jobs/from-url", json={"url": URL}).json() == {"id": 1, "created": True}
    read.assert_called_once_with(URL)
    assert app.state.store.daily_usage().used == 0
    assert client.post("/api/jobs/from-url", json={"url": URL}).json()["created"] is False
    assert len(app.state.store.applications()) == 1


@pytest.mark.parametrize("custom", [False, True])
def test_disabling_external_executor_keeps_independently_configured_integrations(api, custom):
    app, client, _ = api
    store = app.state.store
    store.set_settings(store.settings().model_copy(update={"automation_enabled": False}))
    assert client.post("/api/worker/tick").status_code == 200
    assert isinstance(app.state.service.adapters["manual"], ExternalBrowser)
    provider = Mock()
    if custom:
        app.state.service.adapters["manual"] = provider
    store.set_settings(store.settings().model_copy(update={"external_applications_enabled": False}))
    assert client.post("/api/worker/tick").status_code == 200
    assert (
        app.state.service.adapters.get("manual") is provider
        if custom
        else "manual" not in app.state.service.adapters
    )
    assert (
        "greenhouse" not in app.state.service.adapters
        and "permitted" not in app.state.service.adapters
    )
    provider.submit.assert_not_called()


@pytest.mark.parametrize("case", ["disabled", "unknown", "private", "host_removed"])
def test_external_preflight_or_import_explains_destination_configuration(api, case):
    app, client, job = api
    settings = app.state.store.settings()
    if case == "disabled":
        settings.external_applications_enabled = False
    elif case == "host_removed":
        settings.external_allowed_hosts = ["careers.example.com"]
    else:
        job.url = (
            "https://localhost/private" if case == "private" else "https://careers.example.com/job"
        )
    app.state.store.set_settings(settings)
    assert client.post("/api/jobs/from-url", json={"url": job.url}).status_code == 409
    app_id, _ = app.state.store.add_job(job)
    app.state.service.prepare(app_id)
    report = client.get(f"/api/applications/{app_id}/preflight").json()
    assert not report["can_submit"]
    assert any(
        not check["passed"] and check["code"] in {"adapter", "external_target"}
        for check in report["checks"]
    )


def test_search_includes_external_jobs_only_when_enabled(api, monkeypatch):
    app, client, job = api
    seen = []

    def search(self, *args, **kwargs):
        seen.append(self.include_external_jobs)
        return []

    monkeypatch.setattr(LinkedInBrowser, "search", search)
    assert client.post("/api/discover/linkedin").status_code == 200
    app.state.store.set_settings(
        app.state.store.settings().model_copy(update={"external_applications_enabled": False})
    )
    assert client.post("/api/discover/linkedin").status_code == 200
    assert seen == [True, False]


def test_direct_browser_preflight_explains_disabled_company_permission(api, data):
    app, _, job = api
    store = app.state.store
    app_id, _ = store.add_job(job)
    app.state.service.prepare(app_id)
    app.state.service.adapters["permitted"] = ExternalBrowser(data, settings=store.settings)
    store.set_settings(store.settings().model_copy(update={"external_applications_enabled": False}))
    report = app.state.service.preflight(app_id)
    check = next(item for item in report.checks if item.code == "external_target")
    assert not check.passed and "Enable company-site" in check.detail
    assert not report.can_submit and store.daily_usage().used == 0


def test_preflight_accepts_a_configured_company_destination_without_reserving(api):
    app, client, job = api
    app_id, _ = app.state.store.add_job(job)
    app.state.service.prepare(app_id)
    report = client.get(f"/api/applications/{app_id}/preflight").json()
    check = next(item for item in report["checks"] if item["code"] == "external_target")
    assert check["passed"] and "HTTPS hostname" in check["detail"]
    assert report["can_submit"] and app.state.store.daily_usage().held == 0
    assert app.state.store.daily_usage().used == 0


@pytest.mark.parametrize("mode", ["success", "no_key", "wrong_model", "disabled", "api_failure"])
def test_submission_configures_the_external_interpreter_and_shared_final_gate(
    api, monkeypatch, mode
):
    app, client, job = api
    app_id, _ = app.state.store.add_job(job)
    app.state.service.prepare(app_id)
    calls = []
    planner = Mock(
        return_value=SitePlan(action_id="action_0", action="submit", reason="Observed final action")
    )
    monkeypatch.setattr("applicator.api.plan_site_step", planner)
    if mode == "api_failure":
        planner.side_effect = RuntimeError("fictional-private-provider-detail")
    monkeypatch.setattr("applicator.api.OpenAI", MagicMock())
    if mode != "no_key":
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    if mode == "wrong_model":
        monkeypatch.setenv("OPENAI_MODEL", "other-model")
    if mode == "disabled":
        app.state.store.set_settings(
            app.state.store.settings().model_copy(update={"external_applications_enabled": False})
        )

    def execute(self, vacancy, answers, folder, progress):
        self.planner({"actions": []})
        self.external_sending_url = vacancy.url
        self.before_submit()
        progress["submitted"] = True
        calls.append(vacancy.source_id)
        return "company-site:fixture:confirmed"

    monkeypatch.setattr(ExternalBrowser, "_submit", execute)
    response = client.post(f"/api/applications/{app_id}/submit", headers={"If-Match": "1"})
    if mode == "success":
        assert response.status_code == 200, response.json()
        assert calls == ["123"]
        assert app.state.store.application(app_id)["state"] == State.SUBMITTED
        assert app.state.store.daily_usage().used == 1
        planner.assert_called_once()
    else:
        assert response.status_code == 409 and calls == []
        assert app.state.store.daily_usage().used == 0
        assert "fictional-private-provider-detail" not in response.text
