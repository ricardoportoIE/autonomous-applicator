from pathlib import Path

import pytest

from applicator.models import Evidence, Job, Profile


@pytest.fixture
def profile() -> Profile:
    return Profile(
        name="Alex Example",
        email="alex@example.test",
        phone="+353 00 000 0000",
        location="Dublin, Ireland",
        confirmed=True,
        evidence=[
            Evidence(
                id="python",
                category="project",
                title="Independent API project",
                text="Built an independent Python and FastAPI service with PostgreSQL, automated tests and Docker.",
                tags=["Python", "FastAPI", "PostgreSQL", "Docker"],
                source="Candidate-reviewed project repository",
                verified=True,
            )
        ],
        answers={"sponsorship": "Yes"},
    )


@pytest.fixture
def job() -> Job:
    return Job(
        source="fixture",
        source_id="fixture-1",
        title="Backend Engineer",
        company="Example Employer",
        location="Dublin, Ireland",
        url="http://127.0.0.1:9999/apply",
        description="Build Python APIs with FastAPI and PostgreSQL.",
        requirements=["Python", "FastAPI", "PostgreSQL"],
    )


@pytest.fixture
def data(tmp_path: Path) -> Path:
    return tmp_path / "data"
