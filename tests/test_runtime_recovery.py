"""Bounded runtime recovery uses fictional records and real intercepted Chromium."""

import hashlib
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import TimeoutError as BrowserTimeout
from test_external_applications import FORM
from test_external_applications import chromium as chromium_fixture
from test_external_applications import external as external_fixture

from applicator.agents import LinkAgent
from applicator.browser import LinkedInBrowser, QuestionnaireReview, ReviewRequired
from applicator.models import Question, State
from applicator.runtime_recovery import (
    RecoveryPlan,
    RuntimeRecovery,
    diagnose_runtime,
    technical_failure,
)
from applicator.service import Service
from applicator.store import Store

chromium = chromium_fixture
external = external_fixture


@pytest.fixture
def recovery(data, profile, job):
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    from applicator.models import Settings

    store.set_settings(Settings(automation_enabled=True))
    service = Service(store, data)
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    attempt = store.reserve(app_id, 1)
    diagnose = Mock(return_value=RecoveryPlan(strategy="reopen", reason="Transient form render"))
    controller = RuntimeRecovery(store, data, app_id, attempt, job, diagnose, Mock(), Mock())
    return controller, store, diagnose


def retry(controller, **changes):
    kwargs = {
        "agent": "Link",
        "stage": "answering_questions",
        "evidence": {},
        "sent": False,
        "pending": False,
        "step": 2,
    }
    kwargs.update(changes)
    return controller.retry(BrowserTimeout("Detached field"), **kwargs)


def set_config(store, key, value):
    with store.connect(True) as db:
        db.execute("INSERT OR REPLACE INTO config VALUES (?,?)", (key, value))


@pytest.mark.parametrize(
    "case", ["unknown", "pending", "sent", "authentication", "consent", "changed", "stage"]
)
def test_non_technical_or_unapproved_failures_cannot_retry(recovery, case):
    controller, _, diagnose = recovery
    values = {"stage": "answering_questions", "sent": False, "pending": False}
    error = BrowserTimeout("Transient field")
    if case == "pending":
        values["pending"] = True
    elif case == "sent":
        values["sent"] = True
    elif case == "stage":
        values["stage"] = "submitting"
    elif case == "authentication":
        error = BrowserTimeout("linkedin.com/authwall")
    elif case == "consent":
        error = ValueError("Approve consent before advancing")
    elif case == "changed":
        error = ValueError("Job title changed; re-import and review")
    else:
        error = ValueError("Missing salary")
    assert not technical_failure(error, **values)
    assert not controller.retry(error, agent="Link", evidence={}, step=1, **values)
    diagnose.assert_not_called()
    controller.checkpoint.assert_not_called()


def test_budget_survives_controller_recreation_and_stops_a_loop(recovery, data):
    controller, store, diagnose = recovery
    assert retry(controller) and retry(controller)
    recreated = RuntimeRecovery(
        store, data, controller.app_id, controller.attempt, controller.job, diagnose, Mock(), Mock()
    )
    assert not retry(recreated) and "exhausted" in recreated.stop_reason
    assert diagnose.call_count == 2
    assert controller.budget(claim=True) == 2
    assert store.daily_usage().held == 1 and store.daily_usage().used == 0


@pytest.mark.parametrize(
    "case",
    [
        "review",
        "wrong_type",
        "model_error",
        "checkpoint_before",
        "checkpoint_after",
        "corrupt_budget",
        "not_held",
        "corrupt_memory",
    ],
)
def test_failed_diagnosis_or_checkpoint_never_starts_a_retry(recovery, case):
    controller, store, diagnose = recovery
    if case == "review":
        diagnose.return_value = RecoveryPlan(strategy="review", reason="Unsupported control")
    elif case == "wrong_type":
        diagnose.return_value = {"strategy": "reopen"}
    elif case == "model_error":
        diagnose.side_effect = RuntimeError("fictional-secret-provider-detail")
    elif case == "checkpoint_before":
        controller.checkpoint.side_effect = ValueError("Paused")
    elif case == "checkpoint_after":
        controller.checkpoint.side_effect = [None, ValueError("Changed")]
    elif case == "corrupt_budget":
        set_config(store, f"runtime_budget:v1:{controller.attempt}", "-1")
    elif case == "not_held":
        store.hold(controller.app_id, "Stopped", attempt=controller.attempt)
    else:
        shape = hashlib.sha256(b"answering_questions").hexdigest()
        from urllib.parse import urlsplit

        key = (
            "runtime_method:v1:"
            + hashlib.sha256(
                f"Link:{urlsplit(controller.job.url).hostname}:answering_questions:TimeoutError:{shape}".encode()
            ).hexdigest()
        )
        set_config(store, key, "broken JSON")
    assert not retry(controller)
    assert controller.stop_reason and "fictional-secret" not in controller.stop_reason
    assert not any(
        event["kind"] == "runtime_recovery_attempt" for event in store.events(controller.app_id)
    )


def test_diagnostics_are_inert_hashed_and_minimised_for_the_model(recovery, data):
    controller, store, diagnose = recovery
    folder = data / "questionnaire-diagnostics"
    folder.mkdir()
    file = folder / "form.html"
    content = b"<form><label>Years with Python</label><input type=number></form>"
    file.write_bytes(content)
    evidence = {
        "path": file.relative_to(data).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    assert retry(controller, evidence=evidence, host="jobs.lever.co")
    observed = diagnose.call_args.args[0]
    assert observed["html"] == content.decode() and "profile" not in observed
    assert observed["allowed_strategies"] == ["reopen", "review"]
    event = next(
        e for e in store.events(controller.app_id) if e["kind"] == "runtime_recovery_attempt"
    )
    assert "Years with Python" not in event["detail"] and "sha256" in event["detail"]


@pytest.mark.parametrize(
    "case", ["escape", "bad_type", "hash", "oversized", "missing", "truncated"]
)
def test_diagnostic_integrity_boundaries(recovery, data, case):
    controller, _, diagnose = recovery
    folder = data / "questionnaire-diagnostics"
    folder.mkdir()
    file = folder / "form.html"
    content = b"<form>Native fields</form>"
    if case == "oversized":
        content = b"x" * 256001
    if case == "truncated":
        content = b"x" * 170000
    file.write_bytes(content)
    evidence = {
        "path": file.relative_to(data).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    if case == "escape":
        evidence["path"] = "../outside.html"
    if case == "bad_type":
        evidence["path"] = 12
    if case == "hash":
        evidence["sha256"] = "changed"
    if case == "missing":
        file.unlink()
    if case == "truncated":
        assert retry(controller, evidence=evidence)
        assert len(diagnose.call_args.args[0]["html"]) == 160000
    else:
        assert not retry(controller, evidence=evidence)
        diagnose.assert_not_called()


def test_only_confirmed_recoveries_become_reusable_methods(recovery, data):
    controller, store, diagnose = recovery
    assert retry(controller)
    key = controller.methods[0]
    controller.finish(True)
    assert json.loads(store.get_config(key))["successes"] == 1
    next_controller = RuntimeRecovery(
        store, data, controller.app_id, controller.attempt, controller.job, diagnose, Mock(), Mock()
    )
    diagnose.reset_mock()
    assert retry(next_controller)
    diagnose.assert_not_called()
    next_controller.finish(False)
    assert json.loads(store.get_config(key))["failures"] == 1
    # A failed hint is not eligible to bypass diagnosis for a fresh attempt.
    set_config(store, f"runtime_budget:v1:{controller.attempt}", "0")
    last = RuntimeRecovery(
        store, data, controller.app_id, controller.attempt, controller.job, diagnose, Mock(), Mock()
    )
    assert retry(last)
    diagnose.assert_called_once()


def test_memory_write_failure_cannot_replace_a_confirmed_outcome(recovery, monkeypatch, caplog):
    controller, _, _ = recovery
    assert retry(controller)
    monkeypatch.setattr(controller.store, "connect", Mock(side_effect=OSError("private-path")))
    controller.finish(True)
    assert not controller.methods and "OSError" in caplog.text and "private-path" not in caplog.text


@pytest.mark.parametrize("response", ["valid", "snapshot", "model", "empty"])
def test_runtime_model_contract(response):
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol-2026-10"
        if response == "snapshot"
        else "wrong-model"
        if response == "model"
        else "gpt-6.1-sol",
        output_parsed=None
        if response == "empty"
        else RecoveryPlan(strategy="reopen", reason="Transient page"),
    )
    if response in {"model", "empty"}:
        with pytest.raises(ValueError):
            diagnose_runtime(client, {"html": "<form>untrusted</form>"})
    else:
        assert diagnose_runtime(client, {"html": "<form>untrusted</form>"}).strategy == "reopen"
    kwargs = client.responses.parse.call_args.kwargs
    assert kwargs["model"] == "gpt-6.1-sol" and not kwargs["store"]
    assert (
        kwargs["text_format"] is RecoveryPlan
        and "Never retry a submission click" in kwargs["instructions"]
    )


@pytest.mark.parametrize("provider", ["easy_apply", "company", "handoff"])
def test_real_runtime_recovery_reopens_and_sends_once_with_one_reservation(
    external, data, profile, monkeypatch, provider
):
    external_adapter, context, job, settings = external
    settings.linkedin_authorised = True
    if provider in {"easy_apply", "handoff"}:
        job.source, job.source_id, job.url = (
            "linkedin",
            "123",
            "https://www.linkedin.com/jobs/view/123/",
        )
        adapter = LinkAgent(data, profile)
        monkeypatch.setattr(adapter, "context", external_adapter.context)
        monkeypatch.setattr("applicator.browser.sync_playwright", lambda: nullcontext(None))
        monkeypatch.setattr("applicator.browser.job_details", lambda page, expected_id: job)
    else:
        adapter = external_adapter
    body = FORM
    if provider == "easy_apply":
        body = FORM.replace("<form>", "<dialog open><form>").replace("</form>", "</form></dialog>")
        body = body.replace("Application submitted", "Your application was sent")
        monkeypatch.setattr("applicator.browser.open_easy_apply", lambda page, report: None)
    if provider == "handoff":
        adapter.external_executor = external_adapter
        landing = '<main><a href="https://jobs.lever.co/example/123">Apply</a></main>'
    else:
        landing = body
    context.unroute("**/*")
    context.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="text/html", body=landing if "linkedin.com" in route.request.url else body
        ),
    )
    module = "applicator.browser" if provider == "easy_apply" else "applicator.external_browser"
    import importlib

    original = importlib.import_module(module).collect_questions
    visits = []

    def transient(*args, **kwargs):
        visits.append(args[0].url)
        if len(visits) == 1:
            raise BrowserTimeout("Detached question control")
        return original(*args, **kwargs)

    monkeypatch.setattr(module + ".collect_questions", transient)
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(settings)
    diagnosis = Mock(return_value=RecoveryPlan(strategy="reopen", reason="Fresh form will settle"))
    service = Service(store, data, {job.source: adapter}, runtime_diagnoser=diagnosis)
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    events = []
    assert service.submit(
        app_id, progress=lambda stage, detail: events.append((stage, detail))
    ).endswith(":confirmed")
    assert len(visits) == 2 and diagnosis.call_count == 1
    assert store.application(app_id)["state"] == State.SUBMITTED
    assert store.daily_usage().attempts == 1 and store.daily_usage().used == 1
    pages = [page for page in context.pages if page.url == visits[-1]]
    assert sum(page.evaluate("window.sends") for page in pages) == 1
    assert any(stage == "retrying_application" for stage, _ in events)
    assert (
        "sha256" in diagnosis.call_args.args[0].get("html", "")
        or "<form" in diagnosis.call_args.args[0]["html"]
    )
    assert any(e["kind"] == "form_diagnostic" for e in store.events(app_id))
    assert adapter.runtime_recovery is None
    expected = "Link" if provider == "easy_apply" else "Bridge"
    assert events[-1][1].startswith(expected + " · ")


@pytest.mark.parametrize("change", ["disable", "host", "pause"])
def test_external_runtime_retry_rechecks_scope_after_model_without_replaying(
    external, data, profile, monkeypatch, change
):
    adapter, context, job, settings = external
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(settings)
    calls = Mock(side_effect=BrowserTimeout("Detached control"))
    monkeypatch.setattr("applicator.external_browser.collect_questions", calls)

    def diagnose(observation):
        changes = (
            {"external_applications_enabled": False}
            if change == "disable"
            else {"external_allowed_hosts": ["careers.example.com"]}
            if change == "host"
            else {"automation_enabled": False}
        )
        store.set_settings(settings.model_copy(update=changes))
        return RecoveryPlan(strategy="reopen", reason="Transient control")

    service = Service(store, data, {job.source: adapter}, runtime_diagnoser=diagnose)
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    with pytest.raises(ReviewRequired, match="no retry was started"):
        service.submit(app_id)
    assert calls.call_count == 1
    assert sum(page.evaluate("window.sends") for page in context.pages) == 0
    assert store.daily_usage().used == store.daily_usage().held == 0
    assert store.application(app_id)["state"] == State.REVIEW


def test_retry_checkpoint_validates_without_marking_sending_or_claiming_destination(recovery):
    controller, store, _ = recovery
    from applicator.external_urls import destination_key

    settings = store.settings()
    settings.external_applications_enabled = True
    store.set_settings(settings)
    target = "https://jobs.lever.co/example/123"
    store.mark_sending(
        controller.app_id,
        controller.attempt,
        1,
        controller.job,
        external_target=target,
        checkpoint_only=True,
    )
    assert store.get_config(destination_key(target)) is None
    with store.connect() as db:
        assert (
            db.execute(
                "SELECT sent_day FROM attempts WHERE id=?", (controller.attempt,)
            ).fetchone()[0]
            is None
        )
    store.mark_sending(
        controller.app_id, controller.attempt, 1, controller.job, external_target=target
    )
    assert store.get_config(destination_key(target)) == str(controller.attempt)
    with store.connect() as db:
        assert db.execute(
            "SELECT sent_day FROM attempts WHERE id=?", (controller.attempt,)
        ).fetchone()[0]


def test_confirmed_company_recovery_is_reused_for_another_vacancy_with_its_own_facts_and_cv(
    external, data, profile, monkeypatch
):
    adapter, context, job, settings = external
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(settings)
    from applicator.external_browser import collect_questions

    visits = []

    def transient(*args, **kwargs):
        visits.append(args[0].url)
        if len(visits) in {1, 3}:
            raise BrowserTimeout("Detached control")
        return collect_questions(*args, **kwargs)

    monkeypatch.setattr("applicator.external_browser.collect_questions", transient)
    context.unroute("**/*")
    context.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="text/html",
            body=FORM.replace("Backend Engineer", "Python Engineer")
            if route.request.url.endswith("124")
            else FORM,
        ),
    )
    diagnose = Mock(return_value=RecoveryPlan(strategy="reopen", reason="Transient form render"))
    service = Service(store, data, {job.source: adapter}, runtime_diagnoser=diagnose)
    hashes = []
    names = []
    for vacancy, candidate in [
        (job, profile),
        (
            job.model_copy(
                update={
                    "source_id": "124",
                    "url": job.url.removesuffix("123") + "124",
                    "title": "Python Engineer",
                }
            ),
            profile.model_copy(update={"name": "Jamie Example"}),
        ),
    ]:
        store.save_profile(candidate)
        app_id, _ = store.add_job(vacancy)
        service.prepare(app_id)
        item = store.application(app_id)["manifest"]["files"]["cv_pdf"]
        service.submit(app_id)
        page = context.pages[-1]
        assert page.locator("#name").input_value() == candidate.name
        file = page.locator("#cv").evaluate(
            "async el => ({name:el.files[0].name,bytes:[...new Uint8Array(await el.files[0].arrayBuffer())]})"
        )
        assert hashlib.sha256(bytes(file["bytes"])).hexdigest() == item["sha256"]
        assert file["name"] == item["name"]
        hashes.append(item["sha256"])
        names.append(file["name"])
    assert len(visits) == 4 and diagnose.call_count == 1
    assert len(set(hashes)) == len(set(names)) == 2
    events = [
        json.loads(event["detail"])
        for event in store.events()
        if event["kind"] == "runtime_recovery_attempt"
    ]
    assert {event["source"] for event in events} == {"gpt-6.1-sol", "verified_memory"}
    assert store.daily_usage().used == store.daily_usage().attempts == 2


@pytest.mark.parametrize(
    "case", ["exhausted", "pending", "clicked_review", "paused", "stopping", "documents", "profile"]
)
def test_browser_retry_limits_and_last_moment_vetoes(data, profile, job, monkeypatch, case):
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    from applicator.models import Settings

    store.set_settings(Settings(automation_enabled=True))
    adapter = LinkedInBrowser(data, profile)
    diagnosis = Mock(return_value=RecoveryPlan(strategy="reopen", reason="Transient failure"))
    service = Service(store, data, {job.source: adapter}, runtime_diagnoser=diagnosis)
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    calls = []

    def submit(*args):
        progress = args[-1]
        calls.append(1)
        adapter.report("answering_questions", "Checking the live form")
        if case == "pending":
            progress["pending"]["salary"] = Question(id="salary", label="Salary")
        if case == "clicked_review":
            adapter.before_submit()
            progress["submitted"] = True
            raise ReviewRequired("Post-click review cannot prove non-sending")
        if case == "paused":
            store.set_settings(store.settings().model_copy(update={"automation_enabled": False}))
        if case == "stopping":
            service.runtime_stopping = lambda: True
        if case == "documents":
            next(args[2].glob("*_CV.pdf")).write_bytes(b"tampered")
        if case == "profile":
            store.save_profile(profile)
        raise BrowserTimeout("Detached field")

    monkeypatch.setattr(adapter, "_submit", submit)
    with pytest.raises((ReviewRequired, RuntimeError)) as failure:
        service.submit(app_id)
    assert len(calls) == (3 if case == "exhausted" else 1)
    if case == "clicked_review":
        assert store.application(app_id)["state"] == State.UNCERTAIN
        assert store.daily_usage().held == 1
    else:
        assert store.application(app_id)["state"] == State.REVIEW
        assert store.daily_usage().held == 0 and store.daily_usage().used == 0
    if case == "pending":
        assert isinstance(failure.value, QuestionnaireReview)
    if case == "exhausted":
        assert "exhausted" in str(failure.value)
        assert not service.recoverable_form_hold(app_id)
    if case not in {"exhausted"}:
        diagnosis.assert_not_called()
    assert adapter.runtime_recovery is None
