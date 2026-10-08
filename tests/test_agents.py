"""Specialised roles keep the shared policy, FIFO and operation ownership intact."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import TimeoutError as BrowserTimeout

from applicator.agents import AGENTS, BridgeAgent, LinkAgent, ScoutAgent, agent_detail
from applicator.api import create_app
from applicator.browser import LinkedInBrowser
from applicator.external_browser import ExternalBrowser
from applicator.models import Settings
from applicator.runtime_recovery import RecoveryPlan
from applicator.service import Service
from applicator.store import Store


def test_roles_are_specialised_and_progress_preserves_handoffs(data, profile, job):
    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    service = Service(store, data)
    scout = service.scout
    assert set(AGENTS) == {"Scout", "Link", "Bridge"}
    assert isinstance(LinkAgent(data), LinkedInBrowser)
    assert isinstance(BridgeAgent(data, settings=store.settings), ExternalBrowser)
    service.prepare = Mock()
    service.screen_discovery = Mock(return_value={"imported": 1})
    progress = Mock()
    scout.prepare(17, ["python"], use_ai=True, progress=progress)
    call = service.prepare.call_args
    assert call.args == (17, ["python"]) and call.kwargs["use_ai"]
    call.kwargs["progress"]("generating_documents", "Preparing the reviewed CV")
    assert progress.call_args.args == ("generating_documents", "Scout · Preparing the reviewed CV")
    assert scout.screen([job]) == {"imported": 1}
    assert service.screen_discovery.call_args.args == ([job], None)
    scout.screen([job], progress)
    service.screen_discovery.call_args.args[1]("screening_jobs", "Assessing evidence")
    assert progress.call_args.args[1] == "Scout · Assessing evidence"
    for name in AGENTS:
        assert agent_detail("Scout", name + " · Stage") == name + " · Stage"
    assert not service.adapters
    assert scout.stopping() is False


@pytest.mark.parametrize(
    "automatic,paused,stopping",
    [(True, False, False), (True, True, False), (False, True, False), (False, False, True)],
)
def test_scout_search_uses_current_settings_exclusions_and_pause(
    data, profile, job, automatic, paused, stopping
):
    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=not paused, external_applications_enabled=True))
    service = Service(store, data)
    adapter = Mock(spec=LinkedInBrowser)
    adapter.search.return_value = [job]
    factory = Mock(return_value=adapter)
    scout = ScoutAgent(service, stopping=lambda: stopping, browser_factory=factory)
    scout.memory = Mock()
    scout.memory.excluded_ids.return_value = {"old"}
    operation = SimpleNamespace(progress=Mock())
    assert scout.search(operation, automatic=automatic) == [job]
    factory.assert_called_once_with(data, profile)
    assert adapter.agent_name == "Scout" and adapter.include_external_jobs
    adapter.search.assert_called_once_with(
        store.settings().search_keywords, store.settings().search_location, excluded_ids={"old"}
    )
    scout.memory.excluded_ids.assert_called_once_with(known=automatic)
    assert adapter.discovery_stopping() == (stopping or (automatic and paused))
    assert adapter.discovery_failure == scout.memory.defer
    assert adapter.progress == operation.progress
    assert scout.memory.resolved.call_args_list[0].args == ("search",)
    assert scout.memory.resolved.call_args_list[1].args == (job.source_id,)


@pytest.mark.parametrize(
    "error", [BrowserTimeout("private-provider-detail"), ValueError("private-provider-detail")]
)
def test_scout_read_failure_is_deferred_without_sending_or_secret_logs(data, profile, error):
    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    adapter = Mock(spec=LinkedInBrowser)
    adapter.form_stage = "reading_job_results"
    adapter.search.side_effect = error
    scout = ScoutAgent(Service(store, data), browser_factory=lambda *args: adapter)
    operation = SimpleNamespace(progress=Mock())
    with pytest.raises(type(error)):
        scout.search(operation, automatic=True)
    assert scout.memory.waiting_until("search")
    detail = operation.progress.call_args.args[1]
    assert detail.startswith("Scout · ") and "private-provider-detail" not in detail
    assert not store.applications() and store.daily_usage().attempts == 0


@pytest.mark.parametrize("mode", ["missing", "wrong_model", "valid", "provider_error"])
def test_api_runtime_diagnoser_and_adapter_composition(data, profile, monkeypatch, mode):
    app = create_app(data, "fictional-agent-test-token")
    app.state.store.save_profile(profile)
    app.state.store.set_settings(Settings(external_applications_enabled=True))
    client = TestClient(app, headers={"Authorization": "Bearer fictional-agent-test-token"})
    # A paused tick configures adapters without searching or applying.
    assert client.post("/api/worker/tick").status_code == 200
    service = app.state.service
    assert isinstance(service.adapters["linkedin"], LinkAgent)
    assert isinstance(service.adapters["manual"], BridgeAgent)
    assert service.adapters["linkedin"].external_executor is service.adapters["manual"]
    assert not service.runtime_stopping()
    ai = Mock()
    ai.__enter__ = Mock(return_value=ai)
    ai.__exit__ = Mock(return_value=False)
    constructor = Mock(return_value=ai)
    diagnosis = Mock(return_value=RecoveryPlan(strategy="reopen", reason="Transient control"))
    monkeypatch.setattr("applicator.api.OpenAI", constructor)
    monkeypatch.setattr("applicator.api.diagnose_runtime", diagnosis)
    if mode != "missing":
        monkeypatch.setenv("OPENAI_API_KEY", "fictional-key")
    if mode == "wrong_model":
        monkeypatch.setenv("OPENAI_MODEL", "unsupported")
    if mode == "provider_error":
        diagnosis.side_effect = RuntimeError("fictional-provider-detail")
    if mode == "valid":
        assert service.runtime_diagnoser({"stage": "advancing_form"}).strategy == "reopen"
        constructor.assert_called_once_with(timeout=180, max_retries=0)
        diagnosis.assert_called_once_with(ai, {"stage": "advancing_form"})
    else:
        with pytest.raises(ValueError if mode in {"missing", "wrong_model"} else RuntimeError):
            service.runtime_diagnoser({})
        if mode != "provider_error":
            constructor.assert_not_called()
