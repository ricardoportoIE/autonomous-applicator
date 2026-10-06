"""Optional cloud skills cannot penalise fit or bypass professional experience review."""

import pytest

from applicator.browser import ReviewRequired
from applicator.models import Evidence, Question, Settings, State
from applicator.policy import (
    evaluate,
    required_description,
    required_experience_holds,
    requirement_terms,
    requirements,
    select_evidence,
)
from applicator.question_adviser import question_key
from applicator.service import Service
from applicator.store import Store


@pytest.mark.parametrize(
    "heading",
    ["Preferred skills & experience", "Desirable skills", "Nice to have", "Optional requirements"],
)
def test_optional_sections_do_not_penalise_required_skills(job, profile, heading):
    job.requirements = []
    job.description = f"Must Have Skills & Experience\nPython\n{heading}\nAzure\n"
    assert requirements(job) == ["python"]
    result = evaluate(job, profile, Settings())
    assert result.score == 100 and result.gaps == []


@pytest.mark.parametrize(
    "heading", ["Required qualifications", "Requirements", "Essential skills", "About you"]
)
def test_later_required_section_restores_requirement_capture(job, heading):
    job.requirements = []
    job.description = f"Preferred skills\nAzure\n{heading}\nPython required"
    assert requirements(job) == ["python"]


@pytest.mark.parametrize("suffix", ["preferred", "desirable", "is a bonus", "not required"])
def test_optional_clause_is_removed_independently(job, suffix):
    job.requirements = []
    job.description = f"Python required; Azure {suffix}"
    assert requirements(job) == ["python"]


def test_ambiguous_mixed_clause_keeps_mandatory_mentions(job):
    job.requirements = []
    job.description = "Python required and Azure preferred"
    assert requirements(job) == ["python", "azure"]


@pytest.mark.parametrize(
    "description",
    ["AWS/Azure/GCP", "AWS, Azure, or GCP", "AWS or Azure", "AWS, Azure or Google Cloud"],
)
@pytest.mark.parametrize("technology", ["AWS", "Azure"])
def test_cloud_alternatives_are_one_requirement_satisfied_by_one_verified_member(
    job, profile, description, technology
):
    job.requirements = []
    job.description = "Requirements\nExperience in cloud, " + description
    profile.evidence[0].tags = [technology]
    result = evaluate(job, profile, Settings())
    assert len(requirements(job)) == 1
    assert result.score == 100 and result.state == State.READY
    assert result.evidence_ids == ["python"] and result.gaps == []


@pytest.mark.parametrize("description", ["AWS, Azure", "AWS and Azure"])
def test_cloud_lists_without_explicit_alternative_remain_separate(job, profile, description):
    job.requirements = []
    job.description = "Requirements\n" + description
    profile.evidence[0].tags = ["AWS"]
    result = evaluate(job, profile, Settings())
    assert set(requirements(job)) == {"aws", "azure"}
    assert result.score == 65 and result.gaps == ["azure"]


def test_separate_mandatory_provider_is_not_removed_by_an_earlier_alternative(job, profile):
    job.requirements = []
    job.description = "AWS or Azure\nAzure expertise required"
    profile.evidence[0].tags = ["AWS"]
    result = evaluate(job, profile, Settings())
    assert result.score == 65 and result.gaps == ["azure"]


def test_no_verified_alternative_and_unknown_manual_group_stay_unmatched(job, profile):
    job.requirements = ["AWS or Azure"]
    assert evaluate(job, profile, Settings()).matched == []
    assert requirement_terms("aws or invented") == ["aws or invented"]
    assert requirement_terms("unknown") == ["unknown"]


def test_explicit_reviewed_requirements_are_not_rewritten_from_optional_description(job):
    job.requirements = ["Azure", "Azure"]
    job.description = "Preferred skills\nAzure"
    assert requirements(job) == ["azure"]


def test_evidence_selection_ranks_alternative_member_without_claiming_other_providers(job, profile):
    job.requirements = ["AWS or Azure"]
    profile.evidence.append(
        Evidence(
            id="cloud",
            category="project",
            title="Cloud project",
            text="Built an AWS project.",
            tags=["AWS"],
            source="Confirmed project",
            verified=True,
        )
    )
    assert select_evidence(job, profile, ["python", "cloud"])[0] == "cloud"
    assert "Azure" not in profile.evidence[1].tags


@pytest.mark.parametrize(
    "scope", ["work", "professional", "commercial", "paid", "backend software engineering"]
)
def test_explicit_professional_minimum_requires_confirmation_without_inferred_years(
    job, profile, scope
):
    job.description = f"Requirements\nMinimum 5 years of {scope} experience with Python"
    result = evaluate(job, profile, Settings())
    assert result.score == 100 and result.state == State.REVIEW
    assert any(
        "Required professional experience needs review" in value for value in result.blockers
    )
    assert profile.evidence[0].category == "project"


@pytest.mark.parametrize("approved", ["0", "3", "5", "6"])
def test_explicit_same_technology_work_duration_is_compared_to_the_required_minimum(
    job, profile, approved
):
    job.description = "Requirements\n5+ years of work experience with Python"
    label = "How many years of work experience do you have with Python?"
    profile.answers[question_key(Question(id="years", label=label))] = approved
    result = evaluate(job, profile, Settings())
    assert result.state == (State.READY if int(approved) >= 5 else State.REVIEW)


def test_generic_requirement_can_use_only_its_exact_candidate_confirmation(job, profile):
    job.description = "Minimum 5 years of relevant software engineering experience"
    assert required_experience_holds(job, profile)
    key = "condition:experience_requirement:" + required_description(job)
    profile.answers[key] = "Confirmed"
    assert required_experience_holds(job, profile) == []
    job.description = "Minimum 6 years of relevant software engineering experience"
    assert required_experience_holds(job, profile)


@pytest.mark.parametrize("target", ["Software Engineering", "Backend Software Engineering"])
def test_confirmed_general_engineering_duration_does_not_meet_a_larger_minimum(
    job, profile, target
):
    job.description = "Minimum 5 years of relevant " + target + " experience"
    profile.answers[
        question_key(
            Question(
                id="years",
                label="How many years of work experience do you have with " + target + "?",
            )
        )
    ] = "3"
    holds = required_experience_holds(job, profile)
    assert len(holds) == 1 and "approved 3 years; requires at least 5" in holds[0]


def test_requirement_confirmation_does_not_replace_a_known_insufficient_duration(job, profile):
    job.description = "Minimum 5 years of work experience with Python"
    profile.answers[
        question_key(
            Question(id="years", label="How many years of work experience do you have with Python?")
        )
    ] = "3"
    profile.answers["condition:experience_requirement:" + required_description(job)] = "Confirmed"
    assert required_experience_holds(job, profile)


@pytest.mark.parametrize("target", ["AI Agents", "Artificial Intelligence (AI)", "RAG pipelines"])
def test_approved_zero_for_a_professional_ai_topic_is_a_real_experience_gap(job, profile, target):
    job.description = "2+ years of work experience with " + target
    profile.answers[
        question_key(
            Question(
                id="years",
                label="How many years of work experience do you have with " + target + "?",
            )
        )
    ] = "0"
    holds = required_experience_holds(job, profile)
    assert len(holds) == 1 and "approved 0 years; requires at least 2" in holds[0]


@pytest.mark.parametrize("separator", ["-", "–", "—"])
def test_experience_range_uses_the_lower_bound_without_date_arithmetic(job, profile, separator):
    job.description = f"3{separator}5 years of work experience with Python"
    profile.answers[
        question_key(
            Question(id="years", label="How many years of work experience do you have with Python?")
        )
    ] = "3"
    assert required_experience_holds(job, profile) == []


def test_optional_minima_and_unscoped_years_do_not_create_professional_claims(job, profile):
    job.description = (
        "Requires 10+ years.\nPreferred skills\n5 years of professional Python experience"
    )
    assert required_experience_holds(job, profile) == []


def test_required_production_ml_is_not_satisfied_by_a_cloud_alternative(job, profile):
    job.requirements = []
    job.description = (
        "Requirements\nExperience in deploying ML models into production\nAWS/Azure/GCP"
    )
    profile.evidence[0].tags.append("AWS")
    result = evaluate(job, profile, Settings())
    assert result.score == 100 and result.state == State.REVIEW
    assert "Production machine learning experience needs candidate confirmation." in result.blockers
    profile.answers["condition:production_ml"] = "Confirmed"
    assert evaluate(job, profile, Settings()).state == State.READY
    profile.answers["condition:production_ml"] = "No"
    assert any(
        "Required production machine learning experience is not met" in blocker
        for blocker in evaluate(job, profile, Settings()).blockers
    )
    profile.answers.clear()
    job.description = "Requirements\nAWS/Azure/GCP\nPreferred skills\nExperience in deploying ML models into production"
    assert evaluate(job, profile, Settings()).state == State.READY


def test_preparation_still_generates_documents_for_an_interesting_experience_review(
    data, profile, job
):
    job.description = "Python required\nMinimum 5 years of professional Python experience"
    store = Store(data / "experience.sqlite3")
    store.save_profile(profile)
    app_id = store.add_job(job)[0]
    Service(store, data).prepare(app_id)
    row = store.application(app_id)
    assert row["state"] == State.REVIEW and row["manifest"]["files"]["cv_pdf"]
    assert store.daily_usage().attempts == 0


@pytest.mark.parametrize("closed", [True, False])
def test_confirmed_provider_closure_skips_the_record_without_using_sending_capacity(
    data, profile, job, closed
):
    from unittest.mock import Mock

    store = Store(data / "closed.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id = store.add_job(job)[0]
    reason = (
        "The LinkedIn opportunity is no longer accepting applications"
        if closed
        else "Easy Apply control unavailable after three recovery passes"
    )
    adapter = Mock()
    adapter.submit.side_effect = ReviewRequired(reason)
    service = Service(store, data, {"fixture": adapter})
    service.prepare(app_id)
    manifest = store.application(app_id)["manifest"]
    with pytest.raises(ReviewRequired):
        service.submit(app_id)
    row = store.application(app_id)
    assert row["state"] == (State.SKIPPED if closed else State.REVIEW)
    assert row["evaluation"]["state"] == row["state"] and reason in row["evaluation"]["blockers"]
    assert row["manifest"] == manifest
    assert store.daily_usage().used == 0 and store.daily_usage().held == 0
    with store.connect() as db:
        assert (
            db.execute("SELECT status FROM attempts WHERE application_id=?", (app_id,)).fetchone()[
                0
            ]
            == "released"
        )
