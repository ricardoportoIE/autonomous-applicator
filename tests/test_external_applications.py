"""Company-site journeys use real Chromium without contacting employers or an AI API."""

import json
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright

from applicator.browser import LinkedInBrowser, QuestionnaireReview, ReviewRequired, browser_options
from applicator.documents import generate
from applicator.external_browser import (
    ExternalBrowser,
    SitePlan,
    guarded_context,
    observed_actions,
    plan_site_step,
    run_linkedin_handoff,
    structured_opportunity,
)
from applicator.external_urls import external_url, public_addresses, public_hostname
from applicator.models import Settings, State
from applicator.service import Service
from applicator.store import Store

HOST = "jobs.lever.co"
URL = "https://jobs.lever.co/example/123"
FORM = """<h1>Backend Engineer</h1><p>Example Employer</p>
<form><label>Full name<input id=name required></label>
<label>Email<input id=email type=email required></label>
<label>Resume<input id=cv type=file required></label>
<button type=submit>Submit application</button></form><p id=receipt></p>
<script>window.sends=0;document.querySelector('form').onsubmit=e=>{
e.preventDefault();window.sends++;document.querySelector('#receipt').textContent='Application submitted';};</script>"""


@pytest.fixture(scope="module")
def chromium():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        yield browser
        browser.close()


@pytest.fixture
def external(chromium, data, profile, job, monkeypatch):
    job.source, job.url, job.source_id = "permitted", URL, "123"
    settings = Settings(automation_enabled=True, external_applications_enabled=True)
    browser = ExternalBrowser(data, profile, settings=lambda: settings)
    context = chromium.new_context()
    context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=FORM))
    monkeypatch.setattr("applicator.external_browser.public_addresses", lambda host: None)
    monkeypatch.setattr("applicator.external_browser.sync_playwright", lambda: nullcontext(None))

    @contextmanager
    def session(playwright, **kwargs):
        yield context

    monkeypatch.setattr(browser, "context", session)
    browser.before_submit = Mock()
    generate(profile, job, ["python"], data / "docs", 1)
    yield browser, context, job, settings
    context.close()


def test_external_submission_archives_specific_cv_and_confirmation(external, data, profile):
    adapter, context, job, settings = external
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(settings)
    service = Service(store, data, {"permitted": adapter})
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    events = []
    receipt = service.submit(app_id, progress=lambda stage, detail: events.append(stage))
    assert receipt.endswith(":confirmed") and store.application(app_id)["state"] == State.SUBMITTED
    assert context.pages[0].evaluate("window.sends") == 1
    assert context.pages[0].locator("#name").input_value() == profile.name
    assert store.daily_usage().used == 1 and store.daily_usage().held == 0
    record = service.records.read(app_id)
    assert record["attempts"][0]["confirmation"]["url"] == URL
    assert any(field.get("type") == "file" for field in record["attempts"][0]["fields"])
    assert {
        "opening_company_website",
        "uploading_documents",
        "answering_questions",
        "submitting",
    } <= set(events)


@pytest.mark.parametrize("change", ["disable", "host", "pause"])
def test_atomic_final_gate_vetoes_external_policy_changes(external, data, profile, change):
    adapter, context, job, settings = external
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(settings)
    service = Service(store, data, {"permitted": adapter})
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    original = store.mark_sending

    def gate(*args, **kwargs):
        values = (
            {"external_applications_enabled": False}
            if change == "disable"
            else {"external_allowed_hosts": ["careers.example.com"]}
            if change == "host"
            else {"automation_enabled": False}
        )
        store.set_settings(settings.model_copy(update=values))
        original(*args, **kwargs)

    store.mark_sending = gate
    with pytest.raises(ReviewRequired):
        service.submit(app_id)
    assert context.pages[0].evaluate("window.sends") == 0
    assert store.application(app_id)["state"] == State.REVIEW
    assert store.daily_usage().used == 0 and store.daily_usage().held == 0


@pytest.mark.parametrize(
    "case",
    ["unknown", "no_cv", "identity", "ambiguous", "invalid", "missing_gate", "action_target"],
)
def test_pre_send_stops_never_click_submit_and_save_diagnostics(external, data, case):
    adapter, context, job, _ = external
    body = FORM
    if case == "unknown":
        body = body.replace(
            "<button type=submit>",
            "<label>Expected salary<input id=salary required></label><button type=submit>",
        )
    elif case == "no_cv":
        body = body.replace("<label>Resume<input id=cv type=file required></label>", "")
    elif case == "identity":
        body = body.replace("Backend Engineer", "Other Engineer")
    elif case == "ambiguous":
        body = body.replace("</form>", "<button type=submit>Send application</button></form>")
    elif case == "invalid":
        body = body.replace("id=email type=email", "id=email type=email pattern=x")
    elif case == "missing_gate":
        adapter.before_submit = None
    else:
        body = body.replace("<form>", '<form action="https://evil.example.com/collect">')
    context.unroute("**/*")
    context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=body))
    with pytest.raises(ReviewRequired):
        adapter.submit(job, {}, data / "docs")
    assert context.pages[0].evaluate("window.sends") == 0
    if case != "identity":
        assert adapter.form_diagnostic.get("path")
        html = (data / adapter.form_diagnostic["path"]).read_text(encoding="utf-8")
        assert "alex@example.test" not in html and "onsubmit" not in html


def test_unknown_final_result_is_not_review_or_retried(external, data, profile):
    adapter, context, job, settings = external
    context.unroute("**/*")
    context.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="text/html", body=FORM.replace("Application submitted", "No confirmation")
        ),
    )
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(settings)
    service = Service(store, data, {"permitted": adapter})
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    with pytest.raises(Exception) as error:
        service.submit(app_id)
    assert not isinstance(error.value, ReviewRequired)
    assert store.application(app_id)["state"] == State.UNCERTAIN
    assert context.pages[0].evaluate("window.sends") == 1
    assert str(app_id) not in service.tick()


@pytest.mark.parametrize("change", ["disable", "host"])
def test_post_send_policy_change_cannot_release_a_sent_attempt(external, data, profile, change):
    adapter, context, job, settings = external
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(settings)
    service = Service(store, data, {"permitted": adapter})
    app_id, _ = store.add_job(job)
    service.prepare(app_id)

    def changed():
        if change == "disable":
            settings.external_applications_enabled = False
        else:
            settings.external_allowed_hosts = ["careers.example.com"]
        store.set_settings(settings)

    context.expose_function("policy_changed", changed)
    body = FORM.replace("onsubmit=e=>", "onsubmit=async e=>").replace(
        "window.sends++;", "window.sends++;await policy_changed();"
    )
    context.unroute("**/*")
    context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=body))
    if change == "disable":
        assert service.submit(app_id).endswith(":confirmed")
        assert store.application(app_id)["state"] == State.SUBMITTED
        assert store.daily_usage().used == 1 and store.daily_usage().held == 0
    else:
        with pytest.raises(ValueError):
            service.submit(app_id)
        assert store.application(app_id)["state"] == State.UNCERTAIN
        assert store.daily_usage().used == 0 and store.daily_usage().held == 1
    assert context.pages[0].evaluate("window.sends") == 1
    assert str(app_id) not in service.tick()
    assert context.pages[0].evaluate("window.sends") == 1


def test_multi_page_collection_retains_all_reachable_questions(external, data):
    adapter, context, job, _ = external
    body = """<h1>Backend Engineer</h1><p>Example Employer</p><form>
    <label>Expected salary<input id=salary required></label><button type=button>Next</button></form>
    <script>window.sends=0;document.querySelector('button').onclick=()=>{document.querySelector('form').innerHTML=
    '<label>Notice period<input id=notice required></label><label>Resume<input id=cv type=file></label><button type=submit>Submit application</button>';};</script>"""
    context.unroute("**/*")
    context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=body))
    with pytest.raises(QuestionnaireReview) as error:
        adapter.submit(job, {}, data / "docs")
    assert {q.label for q in error.value.questions} == {"Expected salary", "Notice period"}
    assert context.pages[0].evaluate("window.sends") == 0
    assert error.value.questions[0].form_context


def test_verified_site_method_is_reused_without_model_and_is_not_a_fact(external, data):
    adapter, context, job, _ = external
    adapter.planner = Mock(
        side_effect=lambda observation: SitePlan(
            action_id=observation["actions"][0]["id"],
            action="submit",
            reason="Observed final action",
        )
    )
    assert adapter.submit(job, {}, data / "docs").endswith("confirmed")
    assert adapter.planner.call_count == 1
    adapter.planner.side_effect = ValueError(
        "The model should not be needed for this verified shape"
    )
    assert adapter.submit(job, {}, data / "docs").endswith("confirmed")
    assert adapter.planner.call_count == 1
    with Store(data / "applicator.sqlite3").connect() as db:
        entries = db.execute("SELECT value FROM config WHERE key LIKE 'external_form:%'").fetchall()
    assert json.loads(entries[0][0])["successes"] == 2
    assert "alex@example.test" not in entries[0][0]


@pytest.mark.parametrize(
    "plan",
    [
        SitePlan(action_id="action_999", action="submit", reason="Invented"),
        SitePlan(action_id="", action="review", reason="Ambiguous"),
        SitePlan(action_id="action_0", action="next", reason="Wrong kind"),
    ],
)
def test_untrusted_model_plans_cannot_bypass_local_controls(external, data, plan):
    adapter, context, job, _ = external
    adapter.planner = lambda observation: plan
    with pytest.raises(ReviewRequired):
        adapter.submit(job, {}, data / "docs")
    assert context.pages[0].evaluate("window.sends") == 0


def test_model_receives_only_semantic_layout_and_validates_response():
    client = Mock()
    plan = SitePlan(action_id="action_0", action="submit", reason="Final application action")
    client.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol-2026-01-01", output_parsed=plan
    )
    assert plan_site_step(client, {"actions": []}) == plan
    kwargs = client.responses.parse.call_args.kwargs
    assert kwargs["model"] == "gpt-6.1-sol" and kwargs["store"] is False
    for response in [
        SimpleNamespace(model="other", output_parsed=plan),
        SimpleNamespace(model="gpt-6.1-sol", output_parsed=None),
    ]:
        client.responses.parse.return_value = response
        with pytest.raises(ReviewRequired):
            plan_site_step(client, {})


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "192.168.1.2",
        "jobs.lever.co.evil.test",
        "*.lever.co",
        "https://jobs.lever.co",
        "jobs.lever.co:443",
        "a.local",
        "a.internal",
        "a.invalid",
    ],
)
def test_company_host_settings_reject_private_reserved_or_ambiguous_names(host):
    with pytest.raises(ValueError):
        Settings(external_allowed_hosts=[host])


@pytest.mark.parametrize(
    "url",
    [
        "http://jobs.lever.co/a",
        "https://user:password@jobs.lever.co/a",
        "https://jobs.lever.co:444/a",
        "https://jobs.lever.co.evil.com/a",
        "file:///etc/passwd",
        "https://jobs.lever.co:invalid/a",
    ],
)
def test_destination_validation_rejects_unconfigured_or_unsafe_urls(url):
    with pytest.raises(ValueError):
        external_url(url, [HOST])


def test_hostname_normalisation_and_public_dns(monkeypatch):
    assert public_hostname(" JOBS.LEVER.CO ") == HOST
    assert Settings(external_allowed_hosts=[HOST, HOST]).external_allowed_hosts == [HOST]
    monkeypatch.setattr(
        "socket.getaddrinfo", lambda *args, **kwargs: [(0, 0, 0, "", ("8.8.8.8", 443))]
    )
    public_addresses(HOST)
    for address in [[], [(0, 0, 0, "", ("127.0.0.1", 443))]]:
        monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: address)
        with pytest.raises(ValueError):
            public_addresses(HOST)


def test_request_guard_blocks_private_redirects_and_unapproved_posts(monkeypatch):
    context = Mock()
    monkeypatch.setattr("applicator.external_browser.public_addresses", Mock())
    with guarded_context(context, [HOST]):
        handler = context.route.call_args.args[1]
        for url, method, navigation, allowed in [
            (URL, "GET", True, True),
            (URL, "POST", False, True),
            ("https://cdn.example.com/script.js", "GET", False, True),
            ("https://evil.example.com/a", "POST", False, False),
            ("https://evil.example.com/a", "GET", True, False),
            ("http://jobs.lever.co", "GET", True, False),
            ("https://localhost/a", "GET", False, False),
        ]:
            route = Mock(
                request=SimpleNamespace(
                    url=url, method=method, is_navigation_request=lambda: navigation
                )
            )
            handler(route)
            assert route.fallback.called == allowed and route.abort.called != allowed
    context.unroute.assert_called_once()


def test_company_link_read_requires_single_complete_structured_job():
    posting = {
        "@type": "JobPosting",
        "title": "Backend Engineer",
        "hiringOrganization": {"name": "Example Employer"},
        "description": "<p>Build Python &amp; APIs.</p>",
        "jobLocation": {
            "address": {"addressLocality": "Dublin", "addressCountry": {"name": "Ireland"}}
        },
    }
    job = structured_opportunity([json.dumps({"@graph": [posting]})], URL)
    assert job.company == "Example Employer" and job.location == "Dublin, Ireland"
    assert "Python & APIs" in job.description
    for payload in [
        [],
        [json.dumps([posting, posting])],
        ["x" * 200001],
        ["[]"],
        [json.dumps(1)],
        [json.dumps({**posting, "jobLocation": [{}, {}]})],
    ]:
        with pytest.raises(ReviewRequired):
            structured_opportunity(payload, URL)
    assert (
        structured_opportunity(
            [json.dumps({**posting, "jobLocation": [posting["jobLocation"]]})], URL
        ).title
        == job.title
    )


def test_native_actions_never_treat_implicit_submit_as_reversible(chromium):
    page = chromium.new_page()
    page.set_content(
        "<form><button>Next</button><button disabled>Submit application</button><button type=button>Continue</button></form>"
    )
    assert observed_actions(page.locator("form"), form=True) == [
        {"id": "action_2", "action": "next", "label": "Continue"}
    ]
    assert observed_actions(page.locator("body"), form=False) == []
    page.close()


@pytest.mark.parametrize("redirect", [False, True])
def test_linkedin_handoff_preserves_final_gate_and_question_lifecycle(
    external, chromium, data, redirect
):
    adapter, _, job, _ = external
    owner = LinkedInBrowser(data, adapter.profile)
    owner.external_executor = adapter
    owner.before_submit = Mock()
    adapter.form_diagnostic = {"source_id": "previous-job"}
    adapter.form_diagnostics_evidence = [adapter.form_diagnostic]
    page = chromium.new_page()
    target = (
        "https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Fjobs.lever.co%2Fexample%2F123"
        if redirect
        else URL
    )
    page.set_content(f'<main><a href="{target}">Apply</a></main>')
    progress = {"submitted": False, "pending": {}, "step": 0}
    assert run_linkedin_handoff(owner, page, job, data / "docs", progress).endswith("confirmed")
    owner.before_submit.assert_called_once()
    assert owner.external_sending_url == URL and progress["submitted"] is True
    assert owner.form_diagnostic == {} and owner.form_diagnostics_evidence == []
    page.close()
