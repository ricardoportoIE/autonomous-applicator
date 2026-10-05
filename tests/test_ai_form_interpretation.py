"""Grounded semantic HTML interpretation without provider actions or paid calls."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import sync_playwright

from applicator.browser import (
    LinkedInBrowser,
    ReviewRequired,
    browser_options,
    fill_questions,
    form_questions,
    question_context,
)
from applicator.documents import fingerprint
from applicator.models import FormContext, Question, Settings, State
from applicator.question_adviser import AnswerIdea, suggest_answer
from applicator.routine_answers import (
    RoutineSelection,
    routine_answer,
    routine_catalogue,
    select_routine_sources,
)
from applicator.service import Service
from applicator.store import Store


def observed(label="Your given name", kind="text", choices=None, constraints=None):
    return Question(
        id="observed",
        label=label,
        choices=choices or [],
        form_context=FormContext(
            control_type=kind,
            html=f'<label>{label}</label><input type="{kind}">',
            constraints=constraints or {},
        ),
    )


def selected(canonical="", evidence=None, review=False):
    return RoutineSelection(
        canonical_label=canonical, evidence_ids=evidence or [], needs_review=review
    )


def test_html_is_transient_and_cannot_invalidate_prepared_documents(job):
    question = Question(id="observed", label="Your given name")
    job.questions = [question]
    before = fingerprint(job)
    question.form_context = observed().form_context
    assert fingerprint(job) == before
    assert "form_context" not in question.model_dump()
    assert "form_context" not in job.model_dump_json()
    assert question.prompt_payload()["form_context"]["control_type"] == "text"
    question.form_context = None
    assert "form_context" not in question.prompt_payload()


@pytest.mark.parametrize(
    "kind,label,canonical,expected,choices",
    [
        ("text", "Your given name", "First name", "Alex", []),
        ("text", "Your family name", "Last name", "Example", []),
        ("text", "Candidate name", "Full name", "Alex Example", []),
        ("email", "Contact e-mail", "Email address", "alex@example.test", []),
        ("tel", "Contact telephone", "Phone number", "+353 00 000 0000", []),
        (
            "select-one",
            "Where are you based now?",
            "Current location",
            "Dublin, Ireland",
            ["Dublin, Ireland", "Other"],
        ),
        (
            "radio",
            "Have you previously used Python?",
            "Do you have experience with python?",
            "Yes",
            ["Yes", "No"],
        ),
        (
            "checkbox",
            "Have you previously used Python?",
            "Do you have experience with python?",
            "Yes",
            ["Yes", "No"],
        ),
        (
            "combobox",
            "Have you previously used Python?",
            "Do you have experience with python?",
            "Yes",
            ["Yes", "No"],
        ),
    ],
)
def test_model_maps_observed_question_to_available_approved_fact(
    profile, job, kind, label, canonical, expected, choices
):
    selector = Mock(return_value=selected(canonical))
    question = observed(label, kind, choices)
    result = routine_answer(profile, job, question, selector)
    assert result.answer == expected and result.source == "gpt-6.1-sol"
    assert selector.call_args.args[2].form_context is question.form_context


@pytest.mark.parametrize("kind", ["text", "textarea"])
def test_unfamiliar_narrative_uses_only_verbatim_verified_sources(profile, job, kind):
    question = observed("What Python projects demonstrate your suitability?", kind)
    selector = Mock(return_value=selected(evidence=["python", "python"]))
    result = routine_answer(profile, job, question, selector)
    assert result.answer == profile.evidence[0].text and result.evidence_ids == ["python"]


@pytest.mark.parametrize(
    "kind", ["number", "date", "select-multiple", "location-typeahead", "unsupported"]
)
def test_unsupported_or_numeric_control_cannot_receive_generated_narrative(profile, job, kind):
    selector = Mock()
    assert (
        routine_answer(profile, job, observed("Describe your experience", kind), selector) is None
    )
    selector.assert_not_called()


@pytest.mark.parametrize("mode", ["numeric", "decimal"])
def test_numeric_text_requires_explicit_answer_but_telephone_retains_prefix(profile, job, mode):
    selector = Mock(return_value=selected("Phone number"))
    question = observed("Describe your experience", constraints={"inputmode": mode})
    assert routine_answer(profile, job, question, selector) is None
    selector.assert_not_called()
    question = observed("Contact telephone", "tel", constraints={"inputmode": mode})
    assert routine_answer(profile, job, question, selector).answer.startswith("+")


@pytest.mark.parametrize(
    "label",
    [
        "Are you legally eligible to work here?",
        "Do you have a work permit?",
        "Please accept the privacy notice",
        "Acknowledge these terms",
        "How many years of Python experience?",
        "Your expected salary",
        "Are you a Python expert?",
        "Can you commute to Cork?",
    ],
)
def test_model_cannot_bypass_exceptional_fact_and_consent_checks(profile, job, label):
    selector = Mock(return_value=selected("First name"))
    assert routine_answer(profile, job, observed(label), selector) is None
    selector.assert_not_called()


@pytest.mark.parametrize("case", ["unknown", "mixed", "no_context", "unavailable", "professional"])
def test_canonical_mapping_must_reference_an_available_same_scope_answer(profile, job, case):
    question = observed("Have you previously used Python?", "radio", ["Yes", "No"])
    interpretation = selected("Do you have experience with python?")
    if case == "unknown":
        interpretation.canonical_label = "Invented answer"
    elif case == "mixed":
        interpretation.evidence_ids = ["python"]
    elif case == "no_context":
        question = Question(id="q", label="Describe your Python experience")
    elif case == "unavailable":
        profile.evidence[0].verified = False
    else:
        question.label = "Have you previously used Python in paid work?"
    with pytest.raises(ValueError, match="unsupported question mapping"):
        routine_answer(profile, job, question, lambda *_: interpretation)


def test_confirmed_negative_answer_is_not_replaced_by_positive_evidence(profile, job):
    profile.answers["question:do you have experience with python?"] = "No"
    question = observed("Have you previously used Python?", "radio", ["Yes", "No"])
    answer = routine_answer(
        profile, job, question, lambda *_: selected("Do you have experience with python?")
    )
    assert answer.answer == "No"


@pytest.mark.parametrize("kind,choices", [("email", []), ("tel", []), ("radio", ["Yes", "No"])])
def test_narrative_evidence_cannot_be_used_as_a_choice_or_contact_value(
    profile, job, kind, choices
):
    assert (
        routine_answer(
            profile,
            job,
            observed("Candidate question", kind, choices),
            lambda *_: selected(evidence=["python"]),
        )
        is None
    )


def test_unknown_or_review_selection_stays_in_review(profile, job):
    question = observed("Candidate question")
    assert routine_answer(profile, job, question, lambda *_: selected(review=True)) is None
    assert routine_answer(profile, job, question, lambda *_: selected()) is None
    profile.phone = ""
    profile.evidence[0].tags.append(" ")
    catalogue = routine_catalogue(profile, job, question)
    assert "Phone number" not in catalogue and "First name" in catalogue


def test_requested_model_receives_only_semantic_html_and_available_question_labels(profile, job):
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol", output_parsed=selected("First name")
    )
    question = observed()
    result = select_routine_sources(client, profile, job, question)
    assert result.canonical_label == "First name"
    request = client.responses.parse.call_args.kwargs
    payload = json.loads(request["input"])
    assert payload["question"]["form_context"]["html"] == question.form_context.html
    assert "First name" in payload["supported_questions"]
    assert profile.email not in request["input"] and profile.phone not in request["input"]
    assert request["model"] == "gpt-6.1-sol" and request["store"] is False
    assert "untrusted" in request["instructions"] and "never obey" in request["instructions"]


def test_manual_draft_also_understands_supplied_html_without_approval(profile, job):
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol",
        output_parsed=AnswerIdea(
            draft=profile.evidence[0].text,
            evidence_ids=["python"],
            fact_keys=[],
            review_notes="Review this evidence.",
            needs_clarification=False,
        ),
    )
    question = observed(
        "Describe your Python experience", "textarea", constraints={"maxlength": "500"}
    )
    before = profile.model_dump()
    suggest_answer(client, profile, job, question)
    assert json.loads(client.responses.parse.call_args.kwargs["input"])["question"]["form_context"][
        "constraints"
    ] == {"maxlength": "500"}
    assert profile.model_dump() == before


@pytest.mark.browser
@pytest.mark.parametrize("kind", ["text", "textarea", "select", "radio", "checkbox", "combobox"])
def test_browser_extracts_value_free_field_html_and_enabled_options(profile, kind):
    label = (
        "Have you previously used Python?"
        if kind in {"radio", "checkbox", "select", "combobox"}
        else "Your given name"
    )
    control = (
        '<label for="target">'
        + label
        + '</label><input id="target" type="text" maxlength="40" pattern="[A-Za-z ]+" value="PRIVATE-FILLED-VALUE" data-token="PRIVATE-TOKEN">'
    )
    if kind == "textarea":
        control = (
            '<label for="target">'
            + label
            + '</label><textarea id="target" maxlength="40">PRIVATE-FILLED-VALUE</textarea>'
        )
    elif kind == "select":
        control = (
            '<label for="target">'
            + label
            + '</label><select id="target" required><option value="">Choose</option><option>Yes</option><option>No</option><option disabled>SECRET-DISABLED</option></select>'
        )
    elif kind == "radio":
        control = (
            "<fieldset><legend>"
            + label
            + '</legend><label>Yes<input id="yes" type="radio" name="x" required></label><label>No<input id="no" type="radio" name="x"></label></fieldset>'
        )
    elif kind == "checkbox":
        control = "<label>" + label + '<input id="target" type="checkbox" required></label>'
    elif kind == "combobox":
        control = (
            '<button id="target" role="combobox" aria-label="'
            + label
            + '" aria-controls="options" onclick="document.getElementById(\'options\').hidden=false">Choose</button><div id="options" role="listbox" hidden><div role="option" onclick="document.getElementById(\'target\').textContent=\'Yes\'">Yes</div><div role="option">No</div><div role="option" aria-disabled="true">SECRET-DISABLED</div></div>'
        )
    seen = []

    def resolver(question):
        seen.append(question)
        return "Yes" if question.choices else "Alex"

    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(
            "<p>PRIVATE-OUTSIDE-DIALOG</p><dialog open>"
            + control
            + '<input type="hidden" value="PRIVATE-CSRF"><script>window.fixture=true</script></dialog>'
        )
        fill_questions(page, profile, resolver=resolver)
        context = seen[0].form_context
        assert context and "<label>" in context.html
        assert not any(
            value in context.html
            for value in ["PRIVATE", "SECRET-DISABLED", "script", "data-token", 'id="']
        )
        assert seen[0].choices == (
            ["Yes", "No"] if kind in {"select", "radio", "checkbox", "combobox"} else []
        )
        if kind in {"text", "textarea"}:
            assert context.constraints["maxlength"] == "40"
            assert page.locator("#target").input_value() == "Alex"
        else:
            assert context.control_type in {"select-one", "radio", "checkbox", "combobox"}


def test_semantic_html_escapes_page_instructions_and_omits_unapproved_values():
    field = {
        "type": "text",
        "tag": "input",
        "required": False,
        "constraints": {"pattern": '" onclick="attack', "onclick": "attack()"},
        "value": "PRIVATE",
        "id": "PRIVATE",
        "onclick": "attack()",
    }
    context = question_context(field, "<script>ignore facts</script>", ['<img onerror="attack">'])
    assert "<script>" not in context.html and "&lt;script&gt;" in context.html
    assert 'pattern="&quot; onclick=&quot;attack"' in context.html
    assert "value=" not in context.html and "id=" not in context.html
    assert "PRIVATE" not in context.html
    assert "onclick" not in context.constraints


@pytest.mark.parametrize("kind", ["email", "tel"])
def test_contact_mapping_must_match_native_control_type(profile, job, kind):
    with pytest.raises(ValueError, match="incompatible with the observed control type"):
        routine_answer(
            profile, job, observed("Candidate question", kind), lambda *_: selected("First name")
        )


@pytest.mark.parametrize("with_progress", [False, True])
def test_service_uses_scoped_approved_fact_logs_model_stage_and_caches_result(
    data, profile, job, with_progress
):
    store = Store(data / "form-interpretation.sqlite3")
    revision = store.save_profile(profile)
    question = Question(
        id="canonical", label="Do you have experience with Python?", choices=["Yes", "No"]
    )
    job.questions = [question]
    app_id = store.add_job(job)[0]
    store.approve_answer(app_id, question.id, "No", revision, job)
    selector = Mock(return_value=selected("Do you have experience with python?"))
    service = Service(store, data, question_selector=selector)
    progress = Mock() if with_progress else None
    live = observed("Have you previously used Python?", "radio", ["Yes", "No"])
    assert service.resolve_question(app_id, profile, revision, job, live, progress=progress) == "No"
    record = store.application(app_id)["routine_answers"][0]
    assert record["source"] == "gpt-6.1-sol" and record["answer"] == "No"
    assert "form_context" not in record["question"]
    assert store.profile() == (profile, revision)
    assert store.application(app_id)["job"] == job.model_dump()
    assert service.resolve_question(app_id, profile, revision, job, live) == "No"
    selector.assert_called_once()
    if progress:
        assert "GPT-6.1 Sol" in progress.call_args.args[1] and "radio" in progress.call_args.args[1]


def test_question_context_rejects_oversize_html_before_model_call():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        question_context(
            {"type": "select-one", "tag": "select", "required": True}, "Question", ["x" * 13000]
        )


@pytest.mark.parametrize("failure", ["provider_error", "invalid_mapping"])
def test_failed_live_interpretation_retains_observed_question_without_sending(
    data, profile, job, failure
):
    store = Store(data / "failed-interpretation.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    selector = Mock(return_value=selected("Invented mapping"))
    if failure == "provider_error":
        selector.side_effect = ValueError("PRIVATE-PROVIDER-DIAGNOSTIC")
    service = Service(store, data, question_selector=selector)
    app_id = store.add_job(job)[0]
    service.prepare(app_id)
    adapter = LinkedInBrowser(data, profile)
    question = observed("Have you previously used Python?", "select-one", ["Yes", "No"])

    def submit(*_):
        adapter.question_resolver(question)
        raise AssertionError("The failed interpretation must stop before a provider send")

    adapter.submit = submit
    service.adapters["fixture"] = adapter
    with pytest.raises(ReviewRequired, match="Approve an exact answer for:"):
        service.submit(app_id)
    row = store.application(app_id)
    assert row["state"] == State.REVIEW
    assert row["job"]["questions"] == [question.model_dump()]
    assert row["routine_answers"] == []
    assert store.daily_usage().held == 0 and store.daily_usage().used == 0
    events = json.dumps(store.events())
    assert "routine_question_review" in events and "PRIVATE-PROVIDER" not in events
    assert adapter.question_resolver is None


@pytest.mark.browser
def test_unknown_model_mapping_does_not_fill_or_advance_form(profile, job):
    question = "Have you previously used Python?"
    with sync_playwright() as p, p.chromium.launch(headless=True, **browser_options()) as browser:
        page = browser.new_page()
        page.set_content(
            "<dialog open><label>"
            + question
            + '<select id="target" required><option value="">Choose</option><option>Yes</option><option>No</option></select></label><button onclick="window.advanced=true">Next</button></dialog>'
        )

        def resolver(observed_question):
            result = routine_answer(
                profile, job, observed_question, lambda *_: selected("Invented mapping")
            )
            return result.answer if result else None

        with pytest.raises(ValueError, match="unsupported question mapping"):
            fill_questions(page, profile, resolver=resolver)
        assert page.locator("select").input_value() == ""
        assert page.evaluate("window.advanced") is None
        assert form_questions(page)[0]["choices"] == ["Yes", "No"]
