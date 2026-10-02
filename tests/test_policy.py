import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from applicator.models import Evidence, Job, Profile, Question, Settings, State
from applicator.policy import (
    answer_questions,
    contains,
    evaluate,
    normalise,
    requirements,
    route,
    select_evidence,
)


@pytest.mark.parametrize(
    ("score", "state"),
    [
        (0, State.SKIPPED),
        (49, State.SKIPPED),
        (50, State.REVIEW),
        (79, State.REVIEW),
        (80, State.READY),
        (100, State.READY),
    ],
)
def test_boundaries(score, state):
    assert route(score, Settings()) == state


@given(st.integers(min_value=0, max_value=100))
def test_routes_obey_threshold(score):
    result = route(score, Settings())
    assert (result == State.READY) == (score >= 80)
    assert (result == State.SKIPPED) == (score < 50)


def test_full_match(profile, job):
    result = evaluate(job, profile, Settings())
    assert result.score == 100 and result.state == State.READY
    assert result.evidence_ids == ["python"]


@pytest.mark.parametrize(
    "description",
    [
        "No sponsorship",
        "Cannot sponsor",
        "Must have unrestricted right to work",
        "We do not offer visa sponsorship",
        "Sponsorship is not available",
    ],
)
def test_sponsorship_exclusions(profile, job, description):
    job.description = description
    result = evaluate(job, profile, Settings())
    assert result.state == State.SKIPPED
    assert result.blockers


def test_sponsorship_unknown_and_years_do_not_veto(profile, job):
    job.title = "Senior Backend Engineer"
    job.description = "Requires 10+ years. Right to work required."
    assert evaluate(job, profile, Settings()).state == State.READY
    job.sponsorship = "unavailable"
    profile.sponsorship_required = False
    assert evaluate(job, profile, Settings()).state == State.READY


@pytest.mark.parametrize(
    "description",
    [
        "Must hold current security clearance",
        "German fluency required; fluent in German",
        "Must be an EU citizen",
        "Driving licence required",
    ],
)
def test_mandatory_conditions_pause(profile, job, description):
    job.description = description
    assert evaluate(job, profile, Settings()).state == State.REVIEW


def test_unverified_unknown_location_and_unconfirmed(profile, job):
    profile.confirmed = False
    assert evaluate(job, profile, Settings()).state == State.REVIEW
    profile.confirmed = True
    job.location = "Remote worldwide"
    assert evaluate(job, profile, Settings()).blockers
    profile.evidence[0].verified = False
    assert evaluate(job, profile, Settings()).score < 50


def test_no_requirements_and_seniority(profile, job):
    job.requirements = []
    job.description = "A friendly team."
    assert "No assessable" in evaluate(job, profile, Settings()).blockers[0]
    job.title = "Principal Engineer"
    job.requirements = ["Python"]
    assert evaluate(job, profile, Settings()).state == State.REVIEW


def test_gaps_aliases_and_role(profile, job):
    job.requirements = ["Python", "Kubernetes", "Azure"]
    result = evaluate(job, profile, Settings())
    assert result.gaps == ["kubernetes", "azure"]
    job.title = "Sales Representative"
    assert evaluate(job, profile, Settings()).score < 50
    assert normalise(" Amazon Web Services  Postgres React.js ") == "aws postgresql react"
    assert contains("Python developer", "Python")
    assert not contains("Django specialist", "go")
    job.requirements = []
    job.description = "Use Python, AWS and PostgreSQL."
    assert set(requirements(job)) == {"python", "aws", "postgresql"}


def test_questions_known_unknown_sensitive_and_choices(profile, job):
    job.questions = [
        Question(id="email", label="Email", answer_key="email"),
        Question(
            id="sponsor", label="Sponsorship?", answer_key="sponsorship", choices=["Yes", "No"]
        ),
        Question(id="salary", label="Salary", answer_key="salary"),
        Question(id="optional", label="Optional", required=False),
        Question(id="sensitive", label="Health", answer_key="email", sensitive=True),
        Question(
            id="invalid", label="Choices", answer_key="sponsorship", choices=["True", "False"]
        ),
    ]
    answers, unknown = answer_questions(job, profile)
    assert answers == {"email": profile.email, "sponsor": "Yes"}
    assert unknown == ["salary", "sensitive", "invalid"]
    assert evaluate(job, profile, Settings()).state == State.REVIEW


def test_evidence_selection(profile, job):
    for index in range(5):
        profile.evidence.append(
            Evidence(
                id=f"extra_{index}",
                category="project",
                title="Project",
                text="Independent Python project",
                tags=["Python"],
                source="reviewed",
                verified=True,
            )
        )
    chosen = select_evidence(job, profile, [item.id for item in profile.evidence])
    assert len(chosen) == 3 and chosen[0] == "python"


def test_contracts_reject_invalid_data(profile, job):
    with pytest.raises(ValidationError):
        Profile.model_validate({**profile.model_dump(), "evidence": profile.evidence * 2})
    with pytest.raises(ValidationError):
        Profile.model_validate({**profile.model_dump(), "answers": {"x": "x" * 3001}})
    with pytest.raises(ValidationError):
        Job.model_validate({**job.model_dump(), "url": "javascript:alert(1)"})
    with pytest.raises(ValidationError):
        Job.model_validate({**job.model_dump(), "url": "https://name:secret@example.test/job"})
    question = Question(id="x", label="Question")
    with pytest.raises(ValidationError):
        Job.model_validate({**job.model_dump(), "questions": [question, question]})
    with pytest.raises(ValidationError):
        Settings(auto_threshold=79)
