"""Deterministic, evidence-led routing. Models cannot override submission gates."""

import re
from decimal import Decimal, InvalidOperation

from .answer_style import format_known_answer, numeric_field
from .location_policy import location_confirmed, location_needs_review
from .models import Evaluation, Job, Profile, Question, Settings, State

ALIASES = {
    "amazon web services": "aws",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "django rest framework": "django",
    "react.js": "react",
    "reactjs": "react",
    "rest apis": "rest",
    "rest api": "rest",
    "ci/cd": "ci/cd",
    "uk": "united kingdom",
}
TECHNOLOGIES = (
    "python",
    "fastapi",
    "django",
    "java",
    "spring boot",
    "php",
    "sql",
    "postgresql",
    "react",
    "typescript",
    "javascript",
    "aws",
    "docker",
    "terraform",
    "git",
    "github actions",
    "pytest",
    "playwright",
    "openai",
    "llm",
    "embeddings",
    "redis",
    "pandas",
    "numpy",
    "kubernetes",
    "azure",
    "c#",
    ".net",
    "go",
    "rust",
)


def normalise(value: str) -> str:
    result = " ".join(value.casefold().split())
    for alias, target in ALIASES.items():
        result = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", target, result)
    return result


def contains(text: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(normalise(term))}(?!\w)", normalise(text)))


def requirements(job: Job) -> list[str]:
    if job.requirements:
        return list(dict.fromkeys(normalise(item) for item in job.requirements))
    return [tech for tech in TECHNOLOGIES if contains(job.description, tech)]


def answer_compatible(question: Question, value: str) -> bool:
    """Known duration inputs require a number; explicit offered ranges remain valid."""
    if question.choices:
        return value in question.choices
    if numeric_field(question):
        if not re.fullmatch(r"\d+(?:\.\d+)?", value.strip(), re.ASCII):
            return False
        context = question.form_context
        if context is not None:
            try:
                number = Decimal(value.strip())
                lower = Decimal(context.constraints.get("min", "0"))
                upper = Decimal(context.constraints.get("max", "Infinity"))
                if not lower.is_finite() or upper.is_nan() or not lower <= number <= upper:
                    return False
                step = context.constraints.get("step")
                if step and step != "any":
                    increment = Decimal(step)
                    if not increment.is_finite() or increment <= 0:
                        return False
                    if (number - lower) % increment:
                        return False
            except (InvalidOperation, ValueError):
                return False
        return True
    return bool(value.strip())


def answer_questions(job: Job, profile: Profile) -> tuple[dict[str, str], list[str]]:
    answers: dict[str, str] = {}
    unresolved: list[str] = []
    known = {
        "name": profile.name,
        "email": profile.email,
        "phone": profile.phone,
        "location": profile.location,
        **profile.answers,
    }
    for question in job.questions:
        key = question.answer_key or "question:" + " ".join(question.label.casefold().split())
        value = format_known_answer(question, known.get(key, "")) or ""
        if question.sensitive or not answer_compatible(question, value):
            if question.required:
                unresolved.append(question.id)
        else:
            answers[question.id] = value
    return answers, unresolved


def route(score: int, settings: Settings) -> State:
    if score >= settings.auto_threshold:
        return State.READY
    if score >= settings.review_threshold:
        return State.REVIEW
    return State.SKIPPED


def select_evidence(job: Job, profile: Profile, evidence_ids: list[str]) -> list[str]:
    needs = requirements(job)
    eligible = [item for item in profile.evidence if item.verified and item.id in evidence_ids]
    ranked = sorted(
        eligible, key=lambda item: sum(normalise(tag) in needs for tag in item.tags), reverse=True
    )
    projects = [item.id for item in ranked if item.category == "project"][:3]
    other = [item.id for item in ranked if item.category != "project"][:3]
    return other + projects


def evaluate(job: Job, profile: Profile, settings: Settings) -> Evaluation:
    needs = requirements(job)
    matched: list[str] = []
    evidence_ids: list[str] = []
    for need in needs:
        matches = [
            item.id
            for item in profile.evidence
            if item.verified and any(normalise(tag) == need for tag in item.tags)
        ]
        if matches:
            matched.append(need)
            evidence_ids.extend(matches)
    gaps = [need for need in needs if need not in matched]
    # Technical evidence is the primary signal. Seniority/years are deliberately not vetoes.
    technical = round(70 * len(matched) / len(needs)) if needs else 0
    target = any(
        contains(job.location, country) for country in settings.allowed_countries
    ) or location_confirmed(job, profile)
    role = any(
        contains(job.title, term)
        for term in (
            "engineer",
            "developer",
            "software",
            "automation",
            "technical",
            "graduate",
            "analyst",
        )
    )
    score = min(100, technical + (15 if target else 0) + (15 if role else 0))
    reasons = [
        f"Technical evidence: {len(matched)}/{len(needs)} requirements ({technical}/70).",
        f"Target location: {'matched' if target else 'requires review'} ({15 if target else 0}/15).",
        f"Technology role: {'matched' if role else 'requires review'} ({15 if role else 0}/15).",
        "Fit is a heuristic, not a hiring probability or an ATS score.",
    ]
    blockers: list[str] = []
    incompatible = job.sponsorship == "unavailable" or bool(
        re.search(
            r"\b(no sponsorship|cannot sponsor|unable to sponsor|must have unrestricted right to work|"
            r"do not (?:offer|provide) (?:visa )?sponsorship|sponsorship is not available)\b",
            job.description,
            re.IGNORECASE,
        )
    )
    state = route(score, settings)
    if profile.sponsorship_required and incompatible:
        blockers.append("Explicit sponsorship incompatibility.")
        state = State.SKIPPED
    if not needs:
        blockers.append("No assessable requirements; review the job description.")
    if not target and not location_confirmed(job, profile):
        blockers.append("Location needs candidate confirmation.")
    if location_needs_review(job, profile, settings):
        blockers.append(
            "Distance or country requires location review; documents may still be prepared."
        )
    if any(
        contains(job.title, term)
        for term in ("staff", "principal", "director", "head", "engineering manager")
    ):
        blockers.append("Exceptional seniority needs candidate review of responsibilities.")
    conditions = {
        "security_clearance": r"(?:must (?:hold|have)|requires?|required) .{0,30}security clearance|security clearance (?:is )?required",
        "citizenship": r"(?:must be|only|requires?) .{0,30}(?:citizen|citizenship)|citizenship (?:is )?required",
        "driving_licence": r"(?:driving|driver.s) licen[cs]e (?:is )?(?:required|essential)",
        "mandatory_language": r"(?:fluent|fluency|native) (?:in )?(?:german|french|dutch|spanish|italian)",
        "doctorate": r"(?:phd|doctorate|doctoral degree) (?:is )?(?:required|essential)|(?:requires?|must have) .{0,25}(?:phd|doctorate)",
    }
    for key, pattern in conditions.items():
        if (
            re.search(pattern, job.description, re.IGNORECASE)
            and profile.answers.get("condition:" + key) != "Confirmed"
        ):
            blockers.append(f"Mandatory eligibility condition needs candidate confirmation: {key}.")
    if not profile.confirmed:
        blockers.append("Candidate profile needs confirmation.")
    _, unresolved = answer_questions(job, profile)
    blockers.extend(f"Required question needs an approved answer: {qid}." for qid in unresolved)
    if blockers and state == State.READY:
        state = State.REVIEW
    return Evaluation(
        score=score,
        state=state,
        matched=matched,
        gaps=gaps,
        reasons=reasons,
        evidence_ids=list(dict.fromkeys(evidence_ids)),
        blockers=blockers,
    )
