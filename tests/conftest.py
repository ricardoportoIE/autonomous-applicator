import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from applicator.models import Evidence, Job, Profile


@pytest.fixture(autouse=True)
def isolate_private_environment(monkeypatch):
    # CLI tests must not import the operator's keys, data paths or browser settings.
    # Individual tests can still set their own controlled configuration afterwards.
    for name in list(os.environ):
        if name.startswith(("OPENAI_", "APPLICATOR_")):
            monkeypatch.delenv(name)
    monkeypatch.setattr("dotenv.load_dotenv", lambda: None)
    monkeypatch.setattr("applicator.cli.load_dotenv", lambda: None)


@pytest.fixture(autouse=True)
def browser_assertion_deadline(request):
    if request.node.get_closest_marker("browser") is None:
        yield
        return
    # These are state assertions, not response-time benchmarks. Document writes,
    # SQLite commits and the authenticated refresh can exceed five seconds on CI.
    # Waiting observes the existing action; it never repeats a provider command.
    expect.set_options(timeout=15000)
    try:
        yield
    finally:
        expect.set_options(timeout=5000)


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
