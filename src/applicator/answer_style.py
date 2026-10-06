"""Present confirmed answers in the format required by the current field."""

import re

from .models import Question

NUMBER = r"\d+(?:\.\d+)?"
YEARS = re.compile(r"\b(?:years?|duration)\b", re.I)
EXPERIENCE = re.compile(
    r"(?:how many years(?: of)? (?:(?:work|professional|commercial|paid) )?experience "
    r"(?:do you have )?(?:with|using|in) |"
    r"(?:do you have (?:(?:any|professional|commercial|paid|work) )?experience (?:with|using|in)|"
    r"have you (?:used|worked with)) |"
    r"(?:(?:describe|outline|summari[sz]e) your |tell us about your )"
    r"(?:(?:professional|commercial|project) )?"
    r"experience (?:with|using|in) )(?P<target>.+)",
    re.I,
)
REVERSED_EXPERIENCE = re.compile(
    r"(?:how many years of |(?:describe|outline|summari[sz]e) your )"
    r"(?:(?:professional|commercial|work|paid) )?"
    r"(?P<target>.+?)(?: project)? experience",
    re.I,
)


def experience_target(question: Question) -> str | None:
    """Recognise an experience question, not an arbitrary numerical request."""
    label = " ".join(question.label.split()).rstrip("?.:*").strip()
    match = EXPERIENCE.fullmatch(label) or REVERSED_EXPERIENCE.fullmatch(label)
    if match is None:
        return None
    return re.sub(r"\s*\(Programming Language\)$", "", match["target"], flags=re.I)


def numeric_field(question: Question) -> bool:
    if question.choices:
        return False
    context = question.form_context
    if context is not None:
        if context.control_type == "number":
            return True
        if context.control_type == "text" and (
            context.constraints.get("inputmode") in {"numeric", "decimal"}
            or re.fullmatch(
                r"\^?(?:\\d|\[0-9\]|\[1-9\])(?:[+*?]|\{\d+(?:,\d*)?\})?\$?",
                context.constraints.get("pattern", ""),
            )
        ):
            return True
    # LinkedIn often renders a numerical years question as an ordinary text input.
    return bool(re.match(r"how many years\b", question.label.strip(), re.I))


def concise_text(value: str) -> str:
    """Remove unnecessary layout without deleting factual qualifications."""
    return " ".join(value.split())


def format_known_answer(question: Question, value: str) -> str | None:
    """Change representation only; choices/contact values retain their exact spelling."""
    if question.choices:
        return value
    target = experience_target(question)
    if numeric_field(question):
        if re.fullmatch(NUMBER, value.strip(), re.ASCII):
            return value.strip()
        if target and YEARS.search(question.label):
            # A complete approved duration statement can become its number. Dates,
            # approximations, negations and unrelated numbers are not durations.
            match = re.fullmatch(
                rf"(?:I have )?(?P<number>{NUMBER}) years?(?: of)? "
                r"(?:(?:professional|work|commercial|paid) )?experience"
                r"(?: (?:with|using|in) (?P<target>.+?))?[.!]?",
                value.strip(),
                re.I | re.ASCII,
            )
            if match and (
                match["target"] is None or match["target"].casefold() == target.casefold()
            ):
                return match["number"]
        return None
    context = question.form_context
    if context is not None and context.control_type not in {"text", "textarea"}:
        return value
    if target:
        if re.fullmatch(NUMBER, value.strip(), re.ASCII):
            # A free-text experience answer needs prose. Without a unit/provenance
            # this bare value cannot safely be expanded into a factual sentence.
            return None
        if value.strip().casefold() in {"yes", "no"}:
            scope = (
                "professional "
                if re.search(r"\b(?:professional|commercial|paid|work)\b", question.label, re.I)
                else ""
            )
            if value.strip().casefold() == "yes":
                return f"Yes, I have {scope}experience with {target}."
            return f"No, I do not have {scope}experience with {target}."
        return concise_text(value)
    return value
