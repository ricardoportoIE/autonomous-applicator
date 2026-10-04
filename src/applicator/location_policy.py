"""Conservative location matching without geocoding or inferred travel preferences."""

import re

from .models import Job, Profile, Settings


def normalise_location(value: str) -> str:
    return " ".join(value.casefold().split())


def country(value: str) -> str:
    if re.search(
        r"\b(?:united kingdom|uk|england|scotland|wales|northern ireland|great britain)\b",
        value,
        re.I,
    ):
        return "united kingdom"
    if re.search(r"\b(?:republic of ireland|ireland)\b", value, re.I):
        return "ireland"
    return normalise_location(value.split(",")[-1])


def location_confirmed(job: Job, profile: Profile) -> bool:
    return (
        profile.answers.get("condition:location:" + normalise_location(job.location)) == "Confirmed"
    )


def location_needs_review(job: Job, profile: Profile, settings: Settings) -> bool:
    if location_confirmed(job, profile):
        return False
    if settings.automatic_location_policy == "configured_countries":
        return False  # The existing configured-country gate still applies.
    current_country = country(profile.location)
    vacancy_country = country(job.location)
    if not profile.location or not current_country or vacancy_country != current_country:
        return True
    if settings.automatic_location_policy == "same_country":
        return False
    city = normalise_location(profile.location.split(",")[0])
    if not city or city == current_country:
        return True
    location = normalise_location(job.location)
    # A country-qualified remote opportunity requires no inferred relocation.
    if re.search(r"\bremote\b", location):
        return False
    return not re.search(r"(?<!\w)" + re.escape(city) + r"(?!\w)", location)
