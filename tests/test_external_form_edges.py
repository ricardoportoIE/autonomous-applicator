"""Portal layout changes, upload integrity and bounded navigation recovery."""

import json
from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from test_external_applications import FORM, URL
from test_external_applications import chromium as chromium_fixture
from test_external_applications import external as external_fixture

from applicator.browser import (
    LinkedInBrowser,
    QuestionnaireReview,
    ReviewRequired,
)
from applicator.documents import generate
from applicator.external_browser import SitePlan, run_linkedin_handoff
from applicator.external_urls import destination_key
from applicator.models import Settings, State
from applicator.service import Service
from applicator.store import Store

chromium = chromium_fixture
external = external_fixture


def serve(context, body):
    context.unroute("**/*")
    context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=body))


@pytest.mark.parametrize("link", [True, False])
def test_company_landing_page_opens_a_separate_native_form(external, data, link):
    adapter, context, job, _ = external
    landing = "<h1>Backend Engineer</h1><p>Example Employer</p>"
    landing += (
        f'<a href="{URL}/apply">Apply for this job</a>'
        if link
        else "<button type=button onclick=\"location.href='" + URL + "/apply'\">Apply</button>"
    )
    context.unroute("**/*")
    context.route(
        "**/*",
        lambda route: route.fulfill(
            content_type="text/html", body=FORM if route.request.url.endswith("/apply") else landing
        ),
    )
    progress = {"submitted": False, "pending": {}, "step": 0}
    assert adapter.run_target(URL, job, data / "docs", progress, playwright=Mock()).endswith(
        "confirmed"
    )
    assert context.pages[0].evaluate("window.sends") == 1


def test_read_external_link_uses_jobposting_without_submitting(external):
    adapter, context, _, settings = external
    metadata = {
        "@type": "JobPosting",
        "title": "Backend Engineer",
        "description": "Build Python APIs",
        "hiringOrganization": {"name": "Example Employer"},
        "jobLocation": {"address": {"addressLocality": "Dublin", "addressCountry": "Ireland"}},
    }
    serve(context, '<script type="application/ld+json">' + json.dumps(metadata) + "</script>")
    assert adapter.read_opportunity(URL).company == "Example Employer"
    settings.external_applications_enabled = False
    with pytest.raises(ReviewRequired):
        adapter.read_opportunity(URL)


def test_external_session_has_its_own_visible_persistent_browser(external, data):
    adapter, _, _, _ = external
    playwright = Mock()
    type(adapter).context(adapter, playwright)
    kwargs = playwright.chromium.launch_persistent_context.call_args.kwargs
    assert kwargs["headless"] is False and kwargs["accept_downloads"] is False
    assert kwargs["service_workers"] == "block"
    assert playwright.chromium.launch_persistent_context.call_args.args[0].endswith("company-sites")


@pytest.mark.parametrize(
    "case",
    [
        "unconfirmed",
        "no_profile",
        "no_action",
        "multiple_forms",
        "same_step",
        "prefill",
        "cv_cleared",
        "answers_changed",
        "actions_changed",
        "bytes_changed",
        "custom_invalid",
    ],
)
def test_site_changes_stop_before_final_send(external, data, case):
    adapter, context, job, _ = external
    body = FORM
    if case == "unconfirmed":
        adapter.profile = adapter.profile.model_copy(update={"confirmed": False})
    elif case == "no_profile":
        adapter.profile = None
    elif case == "no_action":
        body = body.replace("Submit application", "Something unknown")
    elif case == "multiple_forms":
        body = body.replace("<p id=receipt>", "<form><input></form><p id=receipt>")
    elif case == "same_step":
        body = body.replace("<button type=submit>Submit application", "<button type=button>Next")
    elif case == "prefill":
        body = body.replace(
            "<button type=submit>",
            "<label>Expected salary<input id=salary required value=99999></label><button type=submit>",
        )
    elif case in {
        "cv_cleared",
        "answers_changed",
        "actions_changed",
        "bytes_changed",
        "custom_invalid",
    }:

        def planner(observation):
            page = context.pages[0]
            if case == "cv_cleared":
                page.locator("#cv").evaluate("el => el.value='' ")
            elif case == "answers_changed":
                page.locator("#email").fill("other@example.test")
            elif case == "actions_changed":
                page.locator("button").evaluate("el => el.textContent='Delete account'")
            elif case == "custom_invalid":
                page.locator("#cv").evaluate(
                    "el => el.setCustomValidity('The provider rejected the file')"
                )
            else:
                page.locator("#cv").evaluate(
                    "el => {const original=el.files[0];const data=new DataTransfer();data.items.add(new File(['changed'],original.name,{type:'application/pdf'}));el.files=data.files;}"
                )
            return SitePlan(
                action_id=observation["actions"][0]["id"], action="submit", reason="Observed submit"
            )

        adapter.planner = planner
    serve(context, body)
    with pytest.raises(ReviewRequired):
        adapter.submit(job, {}, data / "docs")
    assert not context.pages or context.pages[0].evaluate("window.sends") == 0


@pytest.mark.parametrize("field", ["Cover letter", "Unknown document", "Optional document"])
@pytest.mark.parametrize("required", [True, False])
def test_cover_letter_and_unmapped_uploads_are_handled_explicitly(external, data, field, required):
    adapter, context, job, _ = external
    body = FORM.replace(
        "<button type=submit>",
        f"<label>{field}<input type=file {'required' if required else ''}></label><button type=submit>",
    )
    serve(context, body)
    if required:
        with pytest.raises(ReviewRequired):
            adapter.submit(job, {}, data / "docs")
        assert context.pages[0].evaluate("window.sends") == 0
    else:
        assert adapter.submit(job, {}, data / "docs").endswith("confirmed")


def test_cv_cover_letter_and_native_field_types_are_truthful(external, data):
    adapter, context, job, _ = external
    job.cover_letter_required = True
    adapter.profile.answers.update(
        {
            "question:years with ai": "0",
            "question:summary": "I have no professional experience with this technology.",
            "question:permission": "Yes",
            "question:can relocate": "No",
        }
    )
    generate(adapter.profile, job, ["python"], data / "docs", 1)
    body = FORM.replace(
        "<button type=submit>",
        """<label>Cover letter<input type=file required></label>
    <label>Years with AI<input type=number min=0 required></label><label>Summary<textarea required></textarea></label>
    <label>Permission<input type=checkbox required></label><fieldset><legend>Can relocate</legend>
    <label>Yes<input type=radio name=relocate value=yes required></label><label>No<input type=radio name=relocate value=no required></label></fieldset>
    <label>Sponsorship<select required><option value="">Choose</option><option>Yes</option><option>No</option></select></label><button type=submit>""",
    )
    adapter.profile.answers["question:sponsorship"] = "Yes"
    serve(context, body)
    try:
        assert adapter.submit(job, {}, data / "docs").endswith("confirmed")
    except QuestionnaireReview as exc:
        pytest.fail("Unexpected unresolved fields: " + repr([q.label for q in exc.questions]))
    page = context.pages[0]
    assert page.get_by_label("Years with AI").input_value() == "0"
    assert page.get_by_label("Permission").is_checked()
    assert page.get_by_label("No", exact=True).is_checked()
    assert (
        page.locator("input[type=file]")
        .evaluate_all("els=>els.map(el=>el.files[0].name)")[1]
        .endswith("_Cover_Letter.pdf")
    )


def test_upload_that_site_clears_is_not_assumed_successful(external, data):
    adapter, context, job, _ = external
    serve(context, FORM.replace("id=cv type=file", "id=cv type=file onchange=\"this.value=''\""))
    with pytest.raises(ReviewRequired, match="upload was not confirmed"):
        adapter.submit(job, {}, data / "docs")


def test_memory_failure_cannot_change_a_confirmed_outcome(external, data, monkeypatch):
    adapter, context, job, _ = external
    monkeypatch.setattr(
        adapter, "_remember", Mock(side_effect=OSError("Unavailable private storage"))
    )
    assert adapter.submit(job, {}, data / "docs").endswith("confirmed")
    assert context.pages[0].evaluate("window.sends") == 1


def test_navigation_limit_prevents_an_endless_company_form(external, data):
    adapter, context, job, _ = external
    body = """<h1>Backend Engineer</h1><p>Example Employer</p><form><h2 id=step>Step 1</h2><button type=button>Next</button></form>
    <script>window.sends=0;let step=1;document.querySelector('button').onclick=()=>{document.querySelector('#step').textContent='Step '+(++step);};</script>"""
    serve(context, body)
    with pytest.raises(ReviewRequired, match="exceeded ten"):
        adapter.submit(job, {}, data / "docs")
    assert context.pages[0].evaluate("window.sends") == 0


@pytest.mark.parametrize("kind", ["popup", "same_tab", "no_destination"])
def test_linkedin_apply_button_destination_handling(external, chromium, data, kind, monkeypatch):
    executor, _, job, _ = external
    owner = LinkedInBrowser(data, executor.profile)
    owner.external_executor = executor
    owner.before_submit = Mock()
    context = chromium.new_context()
    script = (
        f"window.open('{URL}')"
        if kind == "popup"
        else f"location.href='{URL}'"
        if kind == "same_tab"
        else "void(0)"
    )
    body = f'<main><button type=button onclick="{script}">Apply</button></main>'
    context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=body))
    page = context.new_page()
    page.goto("https://www.linkedin.com/jobs/view/123/")
    run = Mock(return_value="company-site:fixture:confirmed")
    monkeypatch.setattr(executor, "run_target", run)
    progress = {"submitted": False, "pending": {}, "step": 0}
    try:
        if kind == "no_destination":
            with pytest.raises(ReviewRequired, match="destination could not be read"):
                run_linkedin_handoff(owner, page, job, data / "docs", progress)
            run.assert_not_called()
        else:
            assert run_linkedin_handoff(owner, page, job, data / "docs", progress).endswith(
                "confirmed"
            )
            assert run.call_args.args[0] == URL
    finally:
        context.close()


def test_handoff_requires_one_apply_action_and_a_configured_executor(external, chromium, data):
    executor, _, job, _ = external
    owner = LinkedInBrowser(data, executor.profile)
    page = chromium.new_page()
    page.set_content("<main></main>")
    progress = {"submitted": False, "pending": {}, "step": 0}
    with pytest.raises(ReviewRequired, match="Configure"):
        run_linkedin_handoff(owner, page, job, data / "docs", progress)
    owner.external_executor = executor
    with pytest.raises(ReviewRequired, match="ambiguous"):
        run_linkedin_handoff(owner, page, job, data / "docs", progress)
    page.set_content(f'<main><a href="{URL}">Apply</a></main>')
    with pytest.raises(ReviewRequired, match="final sending gate"):
        run_linkedin_handoff(owner, page, job, data / "docs", progress)
    page.close()


def test_same_portal_vacancy_is_not_sent_twice_from_different_sources(external, data, profile):
    adapter, context, job, settings = external
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(settings)
    service = Service(store, data, {"permitted": adapter, "manual": adapter})
    first, _ = store.add_job(job)
    second, _ = store.add_job(
        job.model_copy(
            update={
                "source": "manual",
                "source_id": "manual-duplicate",
                "url": URL + "/apply?source=LinkedIn",
            }
        )
    )
    service.prepare(first)
    service.prepare(second)
    assert service.submit(first).endswith("confirmed")
    with pytest.raises(ReviewRequired, match="already has"):
        service.submit(second)
    assert store.application(second)["state"] == State.REVIEW and store.daily_usage().used == 1
    assert context.pages[-1].evaluate("window.sends") == 0
    assert destination_key(URL) == destination_key(URL + "/apply?utm_source=linkedin#form")
    assert destination_key("https://boards.greenhouse.io/example?gh_jid=1") != destination_key(
        "https://boards.greenhouse.io/example?gh_jid=2"
    )


def test_released_pre_send_destination_claim_allows_a_verified_retry(external, data, profile):
    adapter, context, job, settings = external
    store = Store(data / "applicator.sqlite3")
    revision = store.save_profile(profile)
    store.set_settings(settings)
    service = Service(store, data, {"permitted": adapter, "manual": adapter})
    first, _ = store.add_job(job)
    second, _ = store.add_job(
        job.model_copy(update={"source": "manual", "source_id": "retry", "url": URL + "/apply"})
    )
    service.prepare(first)
    service.prepare(second)
    attempt = store.reserve(first, revision)
    store.mark_sending(first, attempt, revision, job, external_target=URL)
    store.hold(first, "Known pre-send interruption", attempt=attempt)
    assert store.daily_usage().held == 0 and store.daily_usage().used == 0
    assert service.submit(second).endswith(":confirmed")
    assert store.application(first)["state"] == State.REVIEW
    assert store.application(second)["state"] == State.SUBMITTED
    assert context.pages[0].evaluate("window.sends") == 1
    assert store.daily_usage().used == 1 and store.daily_usage().held == 0


def test_fifo_can_switch_from_external_to_easy_apply_without_a_stale_destination(
    data, profile, job, monkeypatch
):
    store = Store(data / "applicator.sqlite3")
    store.save_profile(profile)
    store.set_settings(
        Settings(
            automation_enabled=True, linkedin_authorised=True, external_applications_enabled=True
        )
    )
    adapter = LinkedInBrowser(data, profile)
    service = Service(store, data, {"linkedin": adapter})
    ids = []
    for source_id in ("111", "222"):
        vacancy = job.model_copy(
            update={
                "source": "linkedin",
                "source_id": source_id,
                "url": f"https://www.linkedin.com/jobs/view/{source_id}/",
            }
        )
        app_id, _ = store.add_job(vacancy)
        service.prepare(app_id)
        ids.append(app_id)

    def execute(vacancy, answers, folder, progress):
        assert adapter.external_sending_url is None
        if vacancy.source_id == "111":
            adapter.external_sending_url = URL
        adapter.before_submit()
        progress["submitted"] = True
        return "fixture:" + vacancy.source_id + ":confirmed"

    monkeypatch.setattr(adapter, "_submit", execute)
    assert len(service.tick()) == 2
    assert all(store.application(app_id)["state"] == State.SUBMITTED for app_id in ids)
    assert store.daily_usage().used == 2


def test_linkedin_routes_the_reviewed_primary_job_not_recommended_easy_apply(
    external, data, monkeypatch
):
    executor, context, job, _ = external
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    owner = LinkedInBrowser(data, executor.profile)
    owner.external_executor = executor
    serve(
        context,
        '<main><a href="https://jobs.lever.co/example/123">Apply</a></main><aside><button>Easy Apply</button></aside>',
    )
    monkeypatch.setattr("applicator.browser.sync_playwright", lambda: nullcontext(None))
    monkeypatch.setattr(owner, "context", executor.context)
    monkeypatch.setattr("applicator.browser.job_details", lambda *args: job)
    handoff = Mock(return_value="company-site:fixture:confirmed")
    monkeypatch.setattr("applicator.external_browser.run_linkedin_handoff", handoff)
    assert owner.submit(job, {}, data / "docs").endswith("confirmed")
    handoff.assert_called_once()
    assert handoff.call_args.args[2] == job
