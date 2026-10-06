"""Batch questionnaire discovery never invents claims or crosses the sending boundary."""

import json
from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright
from pydantic import ValidationError
from test_browser import LINKEDIN_HTML

from applicator.browser import (
    LinkedInBrowser,
    QuestionnaireReview,
    browser_options,
    collect_questions,
)
from applicator.documents import generate
from applicator.models import Job, Question, Settings, State
from applicator.question_adviser import question_key
from applicator.service import Service
from applicator.store import Store


@pytest.fixture
def chromium():
    with (
        sync_playwright() as playwright,
        playwright.chromium.launch(headless=True, **browser_options()) as browser,
    ):
        yield browser


def collect(page, profile, pending=None, resolver=None, resume_fields=None):
    pending = {} if pending is None else pending
    progress = Mock()
    safe = collect_questions(
        page,
        profile,
        pending,
        resume_field_ids=resume_fields,
        resolver=resolver,
        progress=progress,
        memory=lambda *_: None,
    )
    return pending, safe, progress


@pytest.mark.browser
@pytest.mark.parametrize("resolution", ["none", "unknown", "rejected", "known"])
def test_all_current_controls_are_inspected_and_radio_groups_are_deduplicated(
    chromium, profile, resolution
):
    html = """<dialog open><label>Salary<input id="salary" required></label>
    <fieldset><legend>Travel?</legend><label>Yes<input type="radio" name="travel" value="yes" required></label>
    <label>No<input type="radio" name="travel" value="no"></label></fieldset>
    <label>Clearance<select id="clearance" required><option value="">Choose</option><option>Yes</option><option disabled>Maybe</option><option>No</option></select></label>
    <label>I consent<input type="checkbox" required></label>
    <label>Email<input id="email" required></label>
    <section hidden><label>Hidden question<input required></label></section></dialog>"""
    calls = []

    def resolve(question):
        calls.append(question)
        if resolution == "rejected":
            raise ValueError("PRIVATE MODEL RESPONSE")
        if resolution == "known":
            return {"Salary": "50000", "Travel?": "No", "Clearance": "No", "I consent": "Yes"}[
                question.label
            ]
        return None

    with chromium.new_page() as page:
        page.set_content(html)
        pending, safe, progress = collect(
            page, profile, resolver=None if resolution == "none" else resolve
        )
        assert page.locator("#email").input_value() == profile.email
        assert safe
        if resolution == "known":
            assert pending == {} and page.locator("input[name=travel][value=no]").is_checked()
        else:
            assert [q.label for q in pending.values()] == [
                "Salary",
                "Travel?",
                "Clearance",
                "I consent",
            ]
            assert pending["question:travel?"].choices == ["Yes", "No"]
            assert pending["question:clearance"].choices == ["Yes", "No"]
            assert page.locator("#salary").input_value() == ""
            assert not page.locator("input[type=checkbox]").is_checked()
        assert len(calls) == (0 if resolution == "none" else 4)
        assert progress.call_args.args[0] == "collecting_questions"
        assert "PRIVATE" not in str(progress.call_args)


@pytest.mark.browser
@pytest.mark.parametrize("kind", ["text", "radio", "checkbox", "select", "unlabelled"])
def test_unapproved_prefills_are_not_used_to_reach_later_pages(chromium, profile, kind):
    controls = {
        "text": '<label>Salary<input value="999999" required></label>',
        "radio": '<fieldset><legend>Travel?</legend><label>Yes<input name="travel" type="radio" checked required></label><label>No<input name="travel" type="radio"></label></fieldset>',
        "checkbox": '<label>I consent<input type="checkbox" checked required></label>',
        "select": "<label>Clearance<select required><option>Yes</option><option>No</option></select></label>",
        "unlabelled": '<input value="unapproved" required>',
    }
    with chromium.new_page() as page:
        page.set_content(
            "<dialog open>"
            + controls[kind]
            + "<label>Salary elsewhere<input required></label></dialog>"
        )
        pending, safe, _ = collect(page, profile)
        assert len(pending) == 2
        assert not safe


@pytest.mark.browser
def test_conditional_questions_revealed_by_an_approved_choice_join_the_same_batch(
    chromium, profile
):
    profile.answers["question:travel?"] = "Yes"
    with chromium.new_page() as page:
        page.set_content("""<dialog open><label>Travel?<select id="travel" onchange="document.querySelector('#conditional').hidden=false" required><option value="">Choose</option><option>Yes</option><option>No</option></select></label>
        <div id="conditional" hidden><label>Travel frequency<input required></label></div>
        <label>Salary<input required></label></dialog>""")
        pending, safe, _ = collect(page, profile)
        assert [q.label for q in pending.values()] == ["Salary", "Travel frequency"]
        assert safe


@pytest.mark.browser
def test_collection_dismisses_an_unanswered_custom_dropdown_and_reads_its_choices(
    chromium, profile
):
    with chromium.new_page() as page:
        page.set_content("""<dialog open><button role="combobox" aria-label="Interview format" aria-controls="formats" onclick="document.querySelector('#formats').hidden=false" onkeydown="if(event.key==='Escape')document.querySelector('#formats').hidden=true"></button>
        <div id="formats" role="listbox" hidden><span role="option">Online</span><span role="option" aria-disabled="true">Blocked</span><span role="option">Office</span></div>
        <label>Salary<input required></label></dialog>""")
        pending, safe, _ = collect(page, profile)
        assert pending["question:interview format"].choices == ["Online", "Office"]
        assert pending["question:interview format"].form_context.control_type == "combobox"
        assert "form_context" not in pending["question:interview format"].model_dump()
        assert not page.locator("#formats").is_visible()
        assert len(pending) == 2 and safe


@pytest.mark.browser
def test_phone_mapping_failures_do_not_hide_other_required_questions(chromium, profile):
    profile.phone = ""
    with chromium.new_page() as page:
        page.set_content("""<dialog open><label>Phone country code<select><option>Ireland (+353)</option></select></label>
        <label>Mobile phone number<input type="tel" required></label><label>Salary<input required></label></dialog>""")
        pending, safe, _ = collect(page, profile)
        assert [q.label for q in pending.values()] == [
            "Phone country code",
            "Mobile phone number",
            "Salary",
        ]
        assert not safe


@pytest.mark.browser
def test_continuously_changing_conditional_controls_have_a_bounded_collection(chromium, profile):
    with chromium.new_page() as page:
        page.set_content("""<dialog open><label>Email<input id="email" required></label></dialog>
        <script>let n=0;document.querySelector('#email').oninput=()=>{
        const input=document.createElement('input');input.required=true;
        const label=document.createElement('label');label.textContent='New question '+(++n);
        label.append(input);document.querySelector('dialog').append(label);};
        </script>""")
        # Field changes must be structural, rather than merely different values.
        original = page.wait_for_timeout

        def reveal(delay):
            page.evaluate("document.querySelector('#email').dispatchEvent(new Event('input'))")
            original(delay)

        page.wait_for_timeout = reveal
        pending = {}
        with pytest.raises(ValueError, match="did not settle"):
            collect(page, profile, pending)
        assert len(pending) == 3


@pytest.mark.browser
def test_resume_controls_are_excluded_and_existing_pending_answers_can_be_resolved(
    chromium, profile
):
    profile.answers["question:salary"] = "50000"
    pending = {"question:salary": Question(id="salary", label="Salary")}
    with chromium.new_page() as page:
        page.set_content(
            """<dialog open><label>Resume<input id="resume" required></label><label>Salary<input id="salary" required></label></dialog>"""
        )
        pending, safe, _ = collect(page, profile, pending, resume_fields={"resume"})
        assert pending == {} and safe
        assert page.locator("#resume").input_value() == ""
        assert page.locator("#salary").input_value() == "50000"


def provider_html(pages, *, validate=False, cycle=False):
    base = LINKEDIN_HTML[: LINKEDIN_HTML.index("<script>")]
    return (
        base
        + "<script>const pages="
        + json.dumps(pages)
        + ";"
        + f"""
    const dialog=document.querySelector('section');let step=0;
    function render(){{dialog.innerHTML='<form><h2>Step '+(step+1)+'</h2>'+pages[step]+
      (step===pages.length-1?'<button id="submit" type="button">Submit application</button>':'<button id="next" type="button">Next</button>')+'</form>';
      const next=document.querySelector('#next');if(next)next.onclick=()=>{{
        window.nextClicks=(window.nextClicks||0)+1;
        if({"true" if validate else "false"} && !dialog.querySelector('form').reportValidity())return;
        step={"0" if cycle else "step+1"};render();}};
      const submit=document.querySelector('#submit');if(submit)submit.onclick=()=>{{window.sent=true;}};
    }}
    document.querySelector('#easy').onclick=()=>{{dialog.hidden=false;render();}};
    </script>"""
    )


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    ["pages", "required", "prefill", "cycle", "model_error", "ten_steps", "technical_after_gap"],
)
def test_provider_walk_collects_reachable_pages_and_never_submits_with_gaps(
    data, profile, job, tmp_path, monkeypatch, case
):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    job.description = "Python FastAPI PostgreSQL"
    generate(profile, job, ["python"], tmp_path, 1)
    pages = [
        "<label>First unknown<input required></label><label>Email<input required></label>",
        "<label>Second unknown<input required></label><label>Third unknown<textarea required></textarea></label>",
        "<label>Last unknown<input required></label>",
    ]
    if case == "prefill":
        pages[0] = (
            '<label>First unknown<input value="unapproved" required></label><label>Other unknown<input required></label>'
        )
    elif case == "ten_steps":
        pages = [f"<label>Unknown {i}<input required></label>" for i in range(11)]
    elif case == "technical_after_gap":
        pages[1] = (
            '<label>Second unknown<input required></label><input type="file" aria-label="Unsupported extra document"><input type="file" aria-label="Another unsupported document">'
        )
    html = provider_html(pages, validate=case == "required", cycle=case == "cycle")
    clicks = []
    snapshots = []

    def context(self, playwright, **_):
        session = playwright.chromium.launch_persistent_context(
            str(data / "batch-fixture-browser"), headless=True, **browser_options()
        )
        session.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        session.expose_binding("recordSend", lambda *_: clicks.append("sent"))
        session.add_init_script(
            "document.addEventListener('click',e=>{if(e.target.id==='submit')window.recordSend();},true)"
        )
        session.on("close", lambda: None)
        # Observe the live form immediately before closing its intercepted context.
        original_close = session.close

        def close():
            snapshots.append(
                session.pages[-1].evaluate(
                    "({next:window.nextClicks||0, email:document.querySelector('input')?.value})"
                )
            )
            original_close()

        session.close = close
        return session

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    adapter = LinkedInBrowser(data, profile)
    adapter.before_submit = Mock(side_effect=AssertionError("Sending gate must not be reached"))
    if case == "model_error":
        adapter.question_resolver = Mock(side_effect=ValueError("Private model error"))
    with pytest.raises(QuestionnaireReview) as stopped:
        adapter.submit(job, {}, tmp_path)
    labels = [q.label for q in stopped.value.questions]
    assert len(labels) == len(set(labels))
    assert labels == (
        [f"Unknown {i}" for i in range(10)]
        if case == "ten_steps"
        else ["First unknown", "Other unknown"]
        if case == "prefill"
        else ["First unknown", "Second unknown"]
        if case == "technical_after_gap"
        else ["First unknown"]
        if case in {"required", "cycle"}
        else ["First unknown", "Second unknown", "Third unknown", "Last unknown"]
    )
    assert not clicks and not adapter.before_submit.called
    assert "Private model" not in str(stopped.value)
    assert snapshots[0]["next"] == (
        0
        if case == "prefill"
        else 1
        if case in {"required", "cycle", "technical_after_gap"}
        else 10
        if case == "ten_steps"
        else 2
    )


def test_batch_hold_is_atomic_durable_and_retains_unrelated_approvals_routine_answers_and_location(
    data, profile, job
):
    store = Store(data / "batch.sqlite3")
    revision = store.save_profile(profile)
    job.questions = [Question(id="start", label="Start date", choices=["Tomorrow", "Later"])]
    app_id = store.add_job(job)[0]
    other = store.add_job(
        job.model_copy(update={"source_id": "other", "url": "http://127.0.0.1:9999/other"})
    )[0]
    store.approve_answer(app_id, "start", "Later", revision, job)
    routine = Question(id="known", label="Known question")
    store.save_routine_answer(
        app_id, routine, "Confirmed fact", "candidate_facts", [], revision, job
    )
    store.confirm_location(app_id, revision, job.location)
    other_before = store.application(other)
    batch = [
        Question(id="one", label="Salary"),
        Question(id="two", label="Travel?", choices=["Yes", "No"]),
    ]
    store.hold(app_id, "Questionnaire review: 2 pending questions", questions=batch)
    row = Store(store.path).application(app_id)
    assert [q["id"] for q in row["job"]["questions"]] == ["start", "one", "two"]
    assert row["approved_answers"] == {"question:start date": "Later"}
    assert row["routine_answers"][0]["answer"] == "Confirmed fact"
    assert (
        "condition:location:dublin, ireland"
        in store.effective_profile(app_id, profile, Job.model_validate(row["job"])).answers
    )
    assert store.application(other) == other_before
    assert store.profile() == (profile, revision)
    store.hold(app_id, "Questionnaire review: duplicate observation", questions=batch)
    assert len(store.application(app_id)["job"]["questions"]) == 3


def test_changed_choices_expire_only_that_answer_and_preserve_identifiers_and_sensitivity(
    data, profile, job
):
    store = Store(data / "changed.sqlite3")
    revision = store.save_profile(profile)
    job.questions = [
        Question(id="old", label="Format", choices=["Online", "Office"]),
        Question(id="private", label="Sensitive", sensitive=True),
    ]
    app_id = store.add_job(job)[0]
    store.approve_answer(app_id, "old", "Online", revision, job)
    store.hold(
        app_id,
        "Questionnaire review",
        questions=[
            Question(id="new", label="Format", choices=["Office", "Phone"]),
            Question(id="new_private", label="Sensitive"),
        ],
    )
    row = store.application(app_id)
    assert row["approved_answers"] == {}
    assert [q["id"] for q in row["job"]["questions"]] == ["old", "private"]
    assert row["job"]["questions"][1]["sensitive"]


def test_oversized_batch_rolls_back_the_complete_hold(data, profile, job):
    store = Store(data / "oversized.sqlite3")
    store.save_profile(profile)
    app_id = store.add_job(job)[0]
    before = store.application(app_id)
    events = store.events()
    with pytest.raises(ValidationError):
        store.hold(
            app_id,
            "Questionnaire review",
            questions=[Question(id=f"q{i}", label=f"Question {i}") for i in range(101)],
        )
    assert store.application(app_id) == before
    assert store.events() == events


def test_service_persists_the_whole_collection_and_releases_capacity(data, profile, job):
    store = Store(data / "service-batch.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, routine_answers_enabled=False))
    adapter = LinkedInBrowser(data, profile)
    service = Service(store, data, {"fixture": adapter})
    app_id = store.add_job(job)[0]
    service.prepare(app_id)
    batch = [
        Question(id="one", label="Salary"),
        Question(id="two", label="Travel?", choices=["Yes", "No"]),
    ]

    def submit(*_):
        for question in batch:
            assert adapter.question_resolver(question) is None
        raise QuestionnaireReview(batch, 2, "Reached final review; no application was sent.")

    adapter.submit = submit
    with pytest.raises(QuestionnaireReview):
        service.submit(app_id)
    row = store.application(app_id)
    assert row["state"] == State.REVIEW
    assert row["job"]["questions"] == [q.model_dump() for q in batch]
    assert store.daily_usage().held == 0 and store.daily_usage().used == 0
    assert adapter.question_resolver is None and adapter.before_submit is None
    assert not store.form_recovery_available(app_id)
    current = Job.model_validate(row["job"])
    for question in batch:
        store.approve_answer(
            app_id, question.id, "50000" if not question.choices else "No", 1, current
        )
    assert set(store.application(app_id)["approved_answers"]) == {question_key(q) for q in batch}
