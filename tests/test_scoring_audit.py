"""Scoring regressions use fictional jobs and verified capability, never model guesses."""

import httpx
import pytest

from applicator.discovery import greenhouse
from applicator.models import Question, Settings, State
from applicator.policy import evaluate, required_experience_holds, requirements, select_evidence
from applicator.question_adviser import question_key


def inferred(job, description):
    job.requirements = []
    job.description = description
    return job


@pytest.mark.parametrize(
    "heading",
    [
        "Preferred qualifications",
        "Preferred skills and experience",
        "Desirable experience",
        "Nice-to-have qualifications",
        "### Optional skills",
        "**Preferred skills**",
    ],
)
def test_optional_headings_do_not_turn_following_skills_into_mandatory_gaps(job, profile, heading):
    inferred(job, "Required skills\nPython\n" + heading + "\nAzure")
    assert requirements(job) == ["python"]
    assert evaluate(job, profile, Settings()).score == 100


@pytest.mark.parametrize(
    "description",
    [
        "JavaScript or TypeScript",
        "JavaScript, TypeScript or Python",
        "Python or Java",
        "Django or FastAPI",
        "Python or Java or Rust",
    ],
)
def test_explicit_technical_alternatives_are_one_capability_requirement(job, profile, description):
    inferred(job, description)
    profile.evidence[0].tags = [description.split(" ")[0].rstrip(",")]
    result = evaluate(job, profile, Settings())
    assert len(requirements(job)) == 1 and result.score == 100 and not result.gaps


@pytest.mark.parametrize("description", ["Python/Java", "Django/FastAPI", "AWS/Azure/GCP"])
def test_slashes_are_alternatives_only_within_supported_peer_families(job, profile, description):
    inferred(job, description)
    profile.evidence[0].tags = [description.split("/")[0]]
    assert len(requirements(job)) == 1
    assert evaluate(job, profile, Settings()).score == 100


@pytest.mark.parametrize("description", ["Python/Django", "Python and Java", "Python, Java"])
def test_stacks_and_conjunctions_do_not_become_alternatives(job, profile, description):
    inferred(job, description)
    profile.evidence[0].tags = ["Python"]
    assert len(requirements(job)) == 2
    assert evaluate(job, profile, Settings()).score == 65


def test_independently_required_member_is_retained_and_selected_evidence_agrees(job, profile):
    inferred(job, "Python or Java\nJava required")
    profile.evidence[0].tags = ["Python"]
    result = evaluate(job, profile, Settings())
    assert result.score == 65 and result.gaps == ["java"]
    assert select_evidence(job, profile, result.evidence_ids) == ["python"]


def test_explicit_metadata_normalises_only_known_alternatives_and_keeps_unknowns(job, profile):
    job.requirements = ["Python or Java", "Java or Python", " ", "Custom requirement"]
    assert len(requirements(job)) == 2
    result = evaluate(job, profile, Settings())
    assert result.score == 65 and result.gaps == ["custom requirement"]


@pytest.mark.parametrize(
    "location",
    ["Belfast, Northern Ireland", "London, England", "Edinburgh, Scotland", "Cardiff, Wales"],
)
def test_country_credit_uses_country_identity_instead_of_a_substring(job, profile, location):
    job.location = location
    excluded = evaluate(job, profile, Settings(allowed_countries=["Ireland"]))
    included = evaluate(
        job,
        profile,
        Settings(allowed_countries=["UK"], automatic_location_policy="configured_countries"),
    )
    assert excluded.score == 85 and excluded.state == State.REVIEW
    assert included.score == 100 and included.state == State.READY


@pytest.mark.parametrize(
    "title",
    [
        "Technical Recruiter",
        "Graduate Sales Assistant",
        "Civil Engineer",
        "Structural Engineer",
        "Sales Representative",
    ],
)
def test_irrelevant_or_ambiguous_titles_cannot_auto_apply_from_technology_tags_alone(
    job, profile, title
):
    job.title = title
    result = evaluate(job, profile, Settings())
    assert result.score == 85 and result.state == State.REVIEW
    assert "Role relevance needs candidate review." in result.blockers


@pytest.mark.parametrize(
    "title",
    [
        "Graduate Software Engineer",
        "AI Engineer",
        "Technical Lead",
        "Data Analyst",
        "Automation Engineer",
        "Electrical Software Engineer",
    ],
)
def test_recognised_technology_roles_keep_the_same_credit(job, profile, title):
    job.title = title
    assert evaluate(job, profile, Settings()).score == 100


@pytest.mark.parametrize(
    "description",
    [
        "Python required. No AWS experience is required.",
        "Python required; no prior experience with AWS required",
        "Python required and Azure preferred",
    ],
)
def test_explicit_optional_or_negated_technology_does_not_reduce_required_fit(
    job, profile, description
):
    inferred(job, description)
    assert requirements(job) == ["python"]
    assert evaluate(job, profile, Settings()).score == 100


@pytest.mark.parametrize(
    "technology,description",
    [
        ("GCP", "Google Cloud Platform required"),
        ("Go", "Golang required"),
        ("C++", "C++ programming required"),
        ("RAG", "RAG pipelines required"),
        ("machine learning", "Machine learning required"),
        ("RAG", "Retrieval-augmented generation required"),
    ],
)
def test_supported_nonambiguous_technology_names_are_assessable(
    job, profile, technology, description
):
    inferred(job, description)
    profile.evidence[0].tags = [technology]
    assert evaluate(job, profile, Settings()).score == 100


def test_ordinary_go_verb_does_not_create_a_programming_language_gap(job, profile):
    inferred(job, "Python required. We go above and beyond for our customers.")
    assert requirements(job) == ["python"]
    assert evaluate(job, profile, Settings()).score == 100


@pytest.mark.parametrize("minimum,expected", [("0.5", False), ("2.5", True), ("1.5–3.5", False)])
def test_decimal_professional_minima_do_not_read_the_fraction_as_whole_years(
    job, profile, minimum, expected
):
    job.description = minimum + " years of professional Python experience"
    profile.answers[
        question_key(
            Question(id="years", label="How many years of work experience do you have with Python?")
        )
    ] = "2"
    assert bool(required_experience_holds(job, profile)) is expected


def test_fractional_score_uses_explicit_half_up_rounding(job, profile):
    job.requirements = ["Python", "FastAPI", "PostgreSQL", "Rust"]
    assert evaluate(job, profile, Settings()).score == 83


def test_greenhouse_block_boundaries_preserve_optional_section_scope(profile):
    body = {
        "jobs": [
            {
                "id": 1,
                "title": "Backend Engineer",
                "absolute_url": "https://example.test/jobs/1",
                "location": {"name": "Dublin, Ireland"},
                "content": "<h2>Required skills</h2><p><strong>Python</strong></p><h2>Preferred qualifications</h2><ul><li>Azure</li></ul>",
            }
        ]
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        job = greenhouse("example", client)[0]
    assert requirements(job) == ["python"]
    assert evaluate(job, profile, Settings()).score == 100


def test_greenhouse_layout_correction_retains_the_encoded_response_guard():
    response = httpx.Response(
        200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"not-decoded")
    )
    with httpx.Client(transport=httpx.MockTransport(lambda _: response)) as client:
        with pytest.raises(ValueError, match="content encoding"):
            greenhouse("example", client)


@pytest.mark.parametrize(
    "description",
    [
        "Python and Azure are required or preferred",
        "AWS or an unspecified platform",
        "Python/Django or Java",
        "Python required; AWS required",
    ],
)
def test_ambiguous_operators_or_optional_scopes_do_not_invent_equivalences(job, description):
    inferred(job, description)
    assert all(" or " not in item for item in requirements(job))


@pytest.mark.parametrize(
    "description",
    [
        "Go",
        "Go required",
        "Use Go for services",
        "Go programming",
        "Go, Python",
        "Python and Go",
        "`Go` modules",
    ],
)
def test_explicit_go_language_context_keeps_the_requirement(job, description):
    inferred(job, description)
    assert "go" in requirements(job)


def test_repeated_mentions_do_not_add_weight_and_unverified_tags_cannot_match(job, profile):
    inferred(job, "Python Python PYTHON required")
    assert requirements(job) == ["python"]
    assert evaluate(job, profile, Settings()).score == 100
    profile.evidence[0].verified = False
    result = evaluate(job, profile, Settings())
    assert result.score == 30 and result.state == State.SKIPPED
    assert not result.evidence_ids and result.gaps == ["python"]
