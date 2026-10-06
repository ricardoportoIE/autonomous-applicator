"""Reachability, dynamic forms and transactional limits for questionnaire batches."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError
from test_question_collection import chromium as chromium
from test_question_collection import collect, provider_html

from applicator.browser import LinkedInBrowser, QuestionnaireReview, browser_options
from applicator.documents import generate
from applicator.models import Job, Question, Settings, State
from applicator.service import Service
from applicator.store import Store


@pytest.mark.browser
@pytest.mark.parametrize("kind", ["multi_select", "numeric", "unlabelled_optional", "known_phone"])
def test_field_review_retains_metadata_without_blocking_independent_answers(
    chromium, profile, kind
):
    controls = {
        "multi_select": '<label>Available days<select id="days" multiple required><option>Monday</option><option>Friday</option></select></label>',
        "numeric": '<label>How many years of Python?<input id="years" type="number" min="0" required></label>',
        "unlabelled_optional": '<input type="checkbox">',
        "known_phone": '<label>Phone country code<select id="country"><option>Ireland (+353)</option><option>United Kingdom (+44)</option></select></label><label>Phone<input id="phone" type="tel" required></label>',
    }
    profile.answers["question:how many years of python?"] = "Worked since 2023."
    profile.phone = "+3535550100"
    with chromium.new_page() as page:
        page.set_content(
            "<dialog open>" + controls[kind] + "<label>Salary<input required></label></dialog>"
        )
        pending, safe, _ = collect(page, profile)
        assert "question:salary" in pending
        if kind == "multi_select":
            question = pending["question:available days"]
            assert question.choices == ["Monday", "Friday"]
            assert question.form_context.control_type == "select-multiple"
            assert page.locator("select").evaluate("el=>el.selectedOptions.length") == 0
        elif kind == "numeric":
            assert (
                pending["question:how many years of python?"].form_context.constraints["min"] == "0"
            )
            assert page.locator("#years").input_value() == ""
        elif kind == "known_phone":
            assert page.locator("#phone").input_value() == "5550100"
            assert len(pending) == 1
        else:
            assert len(pending) == 1 and not page.locator("input[type=checkbox]").is_checked()
        assert safe


@pytest.mark.browser
@pytest.mark.parametrize("case", ["replacement_modal", "validation_reveals_question"])
def test_new_dialogues_and_validation_questions_are_read_before_review(
    data, profile, job, tmp_path, monkeypatch, case
):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    job.description = "Python FastAPI PostgreSQL"
    generate(profile, job, ["python"], tmp_path, 1)
    html = provider_html(
        [
            "<label>First question<input required></label>",
            "<label>Second question<input required></label>",
        ]
    )
    if case == "replacement_modal":
        html = html.replace("const dialog=", "let dialog=").replace(
            "function render(){",
            "function render(){const replacement=document.createElement('section');replacement.setAttribute('role','dialog');dialog.replaceWith(replacement);dialog=replacement;",
        )
    else:
        html = html.replace(
            "step=step+1;render();",
            "dialog.insertAdjacentHTML('beforeend','<label>New question after validation<input required></label>');",
        )

    def context(self, playwright, **_):
        session = playwright.chromium.launch_persistent_context(
            str(data / "dynamic-fixture-browser"), headless=True, **browser_options()
        )
        session.route("**/*", lambda route: route.fulfill(content_type="text/html", body=html))
        return session

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    adapter = LinkedInBrowser(data, profile)
    adapter.before_submit = Mock(side_effect=AssertionError("No submit is allowed"))
    with pytest.raises(QuestionnaireReview) as stopped:
        adapter.submit(job, {}, tmp_path)
    assert [q.label for q in stopped.value.questions] == [
        "First question",
        "Second question" if case == "replacement_modal" else "New question after validation",
    ]
    assert not adapter.before_submit.called


@pytest.mark.parametrize("held", [False, True])
def test_batch_limit_failure_does_not_partially_release_a_submission(data, profile, job, held):
    store = Store(data / "limit.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id = store.add_job(job)[0]
    Service(store, data).prepare(app_id)
    attempt = store.reserve(app_id, 1) if held else None
    before, events = store.application(app_id), store.events()
    batch = [Question(id=f"q{i}", label=f"Question {i}") for i in range(101)]
    with pytest.raises(ValidationError):
        store.hold(app_id, "Questionnaire review", attempt=attempt, questions=batch)
    assert store.application(app_id) == before and store.events() == events
    assert store.daily_usage().held == int(held)


@pytest.mark.parametrize("changed_profile", [False, True])
def test_unchanged_observations_preserve_current_approvals_without_reviving_stale_ones(
    data, profile, job, changed_profile
):
    store = Store(data / "unchanged.sqlite3")
    store.save_profile(profile)
    question = Question(id="format", label="Format", choices=["Online", "Office"])
    job.questions = [question]
    app_id = store.add_job(job)[0]
    store.approve_answer(app_id, "format", "Online", 1, job)
    store.save_routine_answer(app_id, question, "Online", "candidate_facts", [], 1, job)
    if changed_profile:
        store.save_profile(profile)
    store.hold(
        app_id,
        "Questionnaire review",
        questions=[question, Question(id="new", label="New question")],
    )
    row = store.application(app_id)
    assert row["approved_answers"] == ({} if changed_profile else {"question:format": "Online"})
    assert row["routine_answers"] == []
    assert Job.model_validate(row["job"]).questions[0].id == "format"
    assert row["state"] == State.REVIEW


def test_a_batch_containing_only_unchanged_questions_retains_its_current_approval(
    data, profile, job
):
    store = Store(data / "identical.sqlite3")
    store.save_profile(profile)
    question = Question(id="format", label="Format", choices=["Online", "Office"])
    job.questions = [question]
    app_id = store.add_job(job)[0]
    store.approve_answer(app_id, "format", "Online", 1, job)
    store.hold(app_id, "Questionnaire review", questions=[question])
    assert store.application(app_id)["approved_answers"] == {"question:format": "Online"}


@pytest.mark.browser
def test_an_empty_final_review_retains_gaps_from_previous_pages(chromium, profile):
    pending = {"question:previous": Question(id="previous", label="Previous")}
    with chromium.new_page() as page:
        page.set_content("<dialog open><button>Submit application</button></dialog>")
        retained, safe, _ = collect(page, profile, pending)
        assert retained == pending and len(retained) == 1 and safe
