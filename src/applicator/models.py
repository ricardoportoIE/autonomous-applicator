"""Validated contracts shared by policy, persistence and the API."""

from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    category: Literal["skill", "project", "experience", "education", "language", "award"]
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=1500)
    tags: list[str] = Field(default_factory=list, max_length=40)
    source: str = Field(min_length=1, max_length=500)
    verified: bool = False
    dates: str = Field(default="", max_length=80)


class Profile(Contract):
    name: str = Field(min_length=1, max_length=150)
    summary: str = Field(default="", max_length=800)
    email: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=80)
    location: str = Field(default="", max_length=150)
    links: list[str] = Field(default_factory=list, max_length=5)
    sponsorship_required: bool = True
    confirmed: bool = False
    evidence: list[Evidence] = Field(default_factory=list, max_length=150)
    answers: dict[str, str] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def unique_ids(self) -> "Profile":
        if len({item.id for item in self.evidence}) != len(self.evidence):
            raise ValueError("Evidence identifiers must be unique")
        if any(len(value) > 3000 for value in self.answers.values()):
            raise ValueError("Approved answers must be at most 3,000 characters")
        return self


class Question(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    label: str = Field(min_length=1, max_length=500)
    answer_key: str = Field(default="", max_length=1000)
    required: bool = True
    choices: list[str] = Field(default_factory=list, max_length=100)
    sensitive: bool = False


class Job(Contract):
    source: Literal["manual", "greenhouse", "linkedin", "fixture", "permitted"] = "manual"
    source_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=200)
    url: str = Field(max_length=2000)
    description: str = Field(min_length=1, max_length=40000)
    requirements: list[str] = Field(default_factory=list, max_length=50)
    sponsorship: Literal["unknown", "available", "unavailable"] = "unknown"
    questions: list[Question] = Field(default_factory=list, max_length=100)
    cover_letter_required: bool = False

    @field_validator("url")
    @classmethod
    def public_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("An HTTP(S) URL without embedded credentials is required")
        return value

    @model_validator(mode="after")
    def unique_questions(self) -> "Job":
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("Question identifiers must be unique")
        return self


class Settings(Contract):
    automation_enabled: bool = False
    ai_document_preparation: bool = False
    routine_answers_enabled: bool = True
    automatic_location_policy: Literal["same_city", "same_country", "configured_countries"] = (
        "same_city"
    )
    daily_limit: int = Field(default=10, ge=1, le=50)
    auto_threshold: int = Field(default=80, ge=80, le=100)
    review_threshold: int = Field(default=50, ge=50, le=79)
    allowed_countries: list[str] = Field(
        default_factory=lambda: ["Ireland", "United Kingdom"], min_length=1, max_length=30
    )
    poll_seconds: int = Field(default=60, ge=10, le=3600)
    linkedin_authorised: bool = False
    connections_enabled: bool = False
    discovery_enabled: bool = False
    daily_connection_limit: int = Field(default=3, ge=1, le=10)
    search_keywords: str = Field(default="Python Backend Engineer", min_length=1, max_length=200)
    search_location: str = Field(default="Ireland", min_length=1, max_length=200)

    @field_validator("allowed_countries")
    @classmethod
    def nonempty_countries(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 150 for value in values):
            raise ValueError(
                "Target countries must contain non-empty names of at most 150 characters"
            )
        return list(dict.fromkeys(value.strip() for value in values))


class State(StrEnum):
    READY = "ready"
    REVIEW = "review"
    SKIPPED = "skipped"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    UNCERTAIN = "uncertain"


class Evaluation(Contract):
    score: int = Field(ge=0, le=100)
    state: State
    matched: list[str]
    gaps: list[str]
    reasons: list[str]
    evidence_ids: list[str]
    blockers: list[str]


class Advice(Contract):
    evidence_ids: list[str] = Field(max_length=6)
    explanation: str = Field(max_length=1500)


class DailyUsage(Contract):
    day: str
    timezone: Literal["Europe/London"] = "Europe/London"
    used: int = Field(ge=0)
    held: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    limit: int = Field(ge=1)
    remaining: int = Field(ge=0)


class SubmissionCheck(Contract):
    code: str
    label: str
    passed: bool
    detail: str


class Preflight(Contract):
    checked_at: str
    can_submit: bool
    evaluation: Evaluation | None = None
    checks: list[SubmissionCheck]


PositiveId = Annotated[int, Field(gt=0)]
