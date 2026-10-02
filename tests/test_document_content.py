import pytest

from applicator.documents import chronology, selected_lines
from applicator.models import Evidence


def test_tailoring_uses_job_technologies_only(profile, job):
    profile.summary = "Independent software project experience."
    profile.evidence.append(
        Evidence(
            id="skills",
            category="skill",
            title="Skills",
            text="Python, Kubernetes and Docker",
            tags=["Python", "Docker", "Kubernetes"],
            source="reviewed",
            verified=True,
        )
    )
    lines = selected_lines(profile, job, ["python", "skills"])
    assert ("body", "Python.") in lines
    assert not any("Kubernetes" in text for _, text in lines)
    assert ("body", profile.summary) in lines


@pytest.mark.parametrize(
    ("date", "key"),
    [
        ("Sep 2025 - Mar 2026", (2026, 3)),
        ("2024 - 2026", (2026, 0)),
        ("", (0, 0)),
        ("2014 - Dec 2017", (2017, 12)),
    ],
)
def test_confirmed_dates_are_ordered_without_inventing_months(date, key):
    assert chronology(date) == key
