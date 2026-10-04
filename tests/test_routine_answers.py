"""Automatic answers use exact approved facts and fail closed for uncertain claims."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from applicator.models import Evidence, Question
from applicator.routine_answers import (
    RoutineSelection,
    routine_answer,
    select_routine_sources,
)


@pytest.mark.parametrize(
    "label,expected",
    [
        ("First name", "Alex"),
        ("Last name", "Example"),
        ("Full name", "Alex Example"),
        ("Email address", "alex@example.test"),
        ("Phone number", "+353 00 000 0000"),
        ("Where are you currently based?", "Dublin, Ireland"),
        ("Will you require sponsorship?", "Yes"),
    ],
)
def test_exact_candidate_facts(profile, job, label, expected):
    result = routine_answer(profile, job, Question(id="q", label=label))
    assert result and result.answer == expected and result.source == "candidate_facts"


def test_explicit_approved_answer_takes_priority(profile, job):
    profile.answers["question:do you have experience with python?"] = "No"
    question = Question(id="q", label="Do you have experience with Python?", choices=["Yes", "No"])
    assert routine_answer(profile, job, question).answer == "No"


@pytest.mark.parametrize(
    "label",
    [
        "Do you have experience with Python?",
        "Have you used Python?",
        "Have you worked with Python and Docker?",
        "Do you have experience using PostgreSQL?",
    ],
)
def test_supported_technology_questions(profile, job, label):
    result = routine_answer(profile, job, Question(id="q", label=label, choices=["Yes", "No"]))
    assert result and result.answer == "Yes" and result.evidence_ids == ["python"]


@pytest.mark.parametrize(
    "label",
    [
        "Do you have experience with Java?",
        "Do you have experience with Python and Java?",
        "Do you have commercial experience with Python?",
        "Do you have experience with production Python?",
        "Do you have experience with Python security architecture?",
        "Are you a Python expert?",
        "Expected salary?",
        "Are you legally authorised to work in Ireland?",
        "What is your notice period?",
        "Can you relocate?",
        "Describe your travel availability and experience",
        "Do you agree to the terms?",
        "Describe your disability",
        "What is your gender?",
        "How many years of experience with Python?",
        "Tell us something about yourself",
    ],
)
def test_missing_exceptional_or_personal_answers_stay_in_review(profile, job, label):
    selector = Mock()
    assert routine_answer(profile, job, Question(id="q", label=label), selector) is None
    selector.assert_not_called()


def test_unverified_evidence_and_unconfirmed_candidate_cannot_answer(profile, job):
    question = Question(id="q", label="Have you used Python?", choices=["Yes", "No"])
    profile.evidence[0].verified = False
    assert routine_answer(profile, job, question) is None
    profile.evidence[0].verified = True
    profile.confirmed = False
    assert routine_answer(profile, job, question) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3 years of experience with Python.", "3"),
        ("2.5 years Python.", "2.5"),
        ("Around 3 years Python.", None),
        ("At least 3 years Python.", None),
        ("Less than 3 years Python.", None),
        ("2-3 years Python.", None),
        ("Built Python services since 2021.", None),
        ("I do not have 3 years Python.", None),
        ("I previously claimed 3 years Python, which was incorrect.", None),
        ("3 years Python, 4 years Python.", None),
    ],
)
def test_years_require_explicit_unqualified_numeric_evidence(profile, job, text, expected):
    profile.evidence[0].text = text
    result = routine_answer(
        profile, job, Question(id="q", label="How many years of experience with Python?")
    )
    assert (result.answer if result else None) == expected


def test_conflicting_years_or_choices_do_not_guess(profile, job):
    profile.evidence[0].text = "3 years Python."
    other = profile.evidence[0].model_copy(update={"id": "other", "text": "4 years Python."})
    profile.evidence.append(other)
    question = Question(id="q", label="How many years of experience with Python?")
    assert routine_answer(profile, job, question) is None
    profile.evidence.pop()
    question.choices = ["1", "2"]
    assert routine_answer(profile, job, question) is None


def test_model_selects_sources_but_does_not_write_answer(profile, job):
    question = Question(id="q", label="Describe your Python project experience")
    selector = Mock(
        return_value=RoutineSelection(evidence_ids=["python", "python"], needs_review=False)
    )
    result = routine_answer(profile, job, question, selector)
    assert result.answer == profile.evidence[0].text
    assert result.evidence_ids == ["python"] and result.source == "gpt-6.1-sol"
    question.label = "Describe your professional Python experience"
    selector.return_value = RoutineSelection(evidence_ids=[], needs_review=True)
    assert routine_answer(profile, job, question, selector) is None
    assert selector.call_args.args[0].evidence == []


def test_model_cannot_select_unrelated_sources_for_a_specific_skill(profile, job):
    question = Question(id="q", label="Describe your Java project experience")
    selector = Mock(return_value=RoutineSelection(evidence_ids=["python"], needs_review=False))
    assert routine_answer(profile, job, question, selector) is None


@pytest.mark.parametrize(
    "selection",
    [
        RoutineSelection(evidence_ids=[], needs_review=False),
        RoutineSelection(evidence_ids=["python"], needs_review=True),
    ],
)
def test_no_approved_selection_means_review(profile, job, selection):
    question = Question(id="q", label="Describe your project experience")
    assert routine_answer(profile, job, question, lambda *_: selection) is None


def test_unknown_evidence_and_oversize_answer_are_rejected(profile, job):
    question = Question(id="q", label="Describe your project experience")
    with pytest.raises(ValueError, match="unapproved"):
        routine_answer(
            profile,
            job,
            question,
            lambda *_: RoutineSelection(evidence_ids=["invented"], needs_review=False),
        )
    profile.evidence = [
        Evidence(
            id=str(i),
            category="project",
            title="Source",
            text="x" * 1500,
            verified=True,
            source="Approved source",
        )
        for i in range(3)
    ]
    with pytest.raises(ValueError, match="form limit"):
        routine_answer(
            profile,
            job,
            question,
            lambda *_: RoutineSelection(evidence_ids=["0", "1", "2"], needs_review=False),
        )


def test_sensitive_questions_and_invalid_choices_are_never_automatically_filled(profile, job):
    assert routine_answer(profile, job, Question(id="q", label="Email", sensitive=True)) is None
    assert routine_answer(profile, job, Question(id="q", label="Email", choices=["Other"])) is None
    profile.sponsorship_required = False
    assert (
        routine_answer(
            profile,
            job,
            Question(id="q", label="Do you require visa sponsorship?", choices=["Yes", "No"]),
        ).answer
        == "No"
    )
    assert (
        routine_answer(
            profile, job, Question(id="q", label="Do you require sponsorship?", choices=["Maybe"])
        )
        is None
    )


def test_source_selection_contract_uses_requested_model_without_contact_data(profile, job):
    client = Mock()
    selection = RoutineSelection(evidence_ids=["python"], needs_review=False)
    client.responses.parse.return_value = SimpleNamespace(
        model="gpt-6.1-sol-2026-10", output_parsed=selection
    )
    assert (
        select_routine_sources(
            client, profile, job, Question(id="q", label="Describe your experience")
        )
        == selection
    )
    request = client.responses.parse.call_args.kwargs
    assert request["model"] == "gpt-6.1-sol" and request["store"] is False
    assert request["text_format"] is RoutineSelection
    assert profile.email not in request["input"] and profile.phone not in request["input"]
    assert json.loads(request["input"])["verified_evidence"][0]["id"] == "python"
    for model, output in [("another-model", selection), ("gpt-6.1-sol", None)]:
        client.responses.parse.return_value = SimpleNamespace(model=model, output_parsed=output)
        with pytest.raises(ValueError):
            select_routine_sources(
                client, profile, job, Question(id="q", label="Describe experience")
            )
