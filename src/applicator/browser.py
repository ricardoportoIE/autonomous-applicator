"""Dedicated local browser automation with fixed origins and explicit form contracts."""

import os
import re
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .documents import filename_stem
from .models import Job, Profile, Question


class BrowserOptions(TypedDict, total=False):
    channel: str


class ReviewRequired(ValueError):
    """A provider stopped before attempting an irreversible submission."""


def browser_options() -> BrowserOptions:
    channel = os.getenv("APPLICATOR_BROWSER_CHANNEL", "")
    if (
        not channel
        and Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe").is_file()
    ):
        channel = "msedge"
    if channel and channel not in {"chrome", "msedge", "chromium"}:
        raise ValueError("Unsupported browser channel")
    return {"channel": channel} if channel else {}


def linkedin_job_id(url: str) -> str:
    parsed = urlsplit(url)
    match = re.fullmatch(r"/jobs/view/(\d+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "www.linkedin.com" or not match:
        raise ValueError("Expected an exact LinkedIn job URL")
    return match[1]


def ensure_linkedin(page: Page) -> None:
    parsed = urlsplit(page.url)
    if parsed.scheme != "https" or parsed.netloc != "www.linkedin.com":
        raise ValueError("Browser left the approved LinkedIn origin")
    if any(term in parsed.path for term in ("login", "checkpoint", "authwall")):
        raise ValueError("Complete login or verification manually using browser-login")


def approved_answer(label: str, profile: Profile) -> str | None:
    # Exact approved label answers take precedence; never infer legal eligibility from a score.
    key = "question:" + " ".join(label.casefold().split())
    if key in profile.answers:
        return profile.answers[key]
    exact = {
        "first name": profile.name.split()[0],
        "last name": " ".join(profile.name.split()[1:]),
        "full name": profile.name,
        "email address": profile.email,
        "email": profile.email,
        "phone number": profile.phone,
        "mobile phone number": profile.phone,
    }
    return exact.get(" ".join(label.casefold().split())) or None


def form_questions(page: Page) -> list[dict[str, Any]]:
    # DOM inspection is data extraction, not execution of site-supplied instructions.
    return list(
        page.locator("[role=dialog]").evaluate("""dialog => {
      const labelText = el => {const label=el.labels?.[0]?.cloneNode(true); if(label){label.querySelectorAll('input,select,textarea').forEach(n=>n.remove());return label.textContent.trim();} return el.getAttribute('aria-label') || '';};
      return [...dialog.querySelectorAll('input,select,textarea')]
      .filter(el => el.type !== 'hidden' && el.type !== 'file' && !['submit','button'].includes(el.type))
      .map(el => ({id:el.id, type:el.type, value:el.value,
        label:labelText(el),
        group:el.type === 'radio' ? (el.closest('fieldset')?.querySelector('legend')?.textContent || el.closest('[role=radiogroup]')?.getAttribute('aria-label') || '').trim() : '',
        group_choices:el.type === 'radio' && el.name ? [...dialog.querySelectorAll('input[type=radio]')].filter(other=>other.name===el.name).map(labelText) : [],
        required:el.required || el.getAttribute('aria-required') === 'true',
        choices:el.tagName === 'SELECT' ? [...el.options].map(o=>o.text) : []}));}""")
    )


def fill_questions(page: Page, profile: Profile) -> None:
    for field in form_questions(page):
        label, field_id = str(field["label"]).strip(), str(field["id"])
        if not label or not field_id:
            raise ValueError("Unlabelled form control requires manual review")
        locator = page.locator('[id="' + field_id.replace('"', '\\"') + '"]')
        if field["type"] == "radio":
            group = field["group"]
            if not group or not field["group_choices"]:
                raise ValueError("Unlabelled radio group requires manual review")
            value = approved_answer(group, profile)
            if not value or not value.strip():
                raise ValueError(f"Approve an exact answer for: {group}")
            if value not in field["group_choices"]:
                raise ValueError(f"Approved answer does not match available choices: {group}")
            if label == value:
                locator.check()
            continue
        if field["type"] == "checkbox":
            if re.fullmatch(r"Follow .+ to stay up to date.*", label):
                locator.uncheck()
                continue
            raise ValueError(f"Explicit selection or consent requires manual review: {label}")
        value = approved_answer(label, profile)
        if not value or not value.strip():
            # Existing values also need validation; never assume a prefilled legal answer is correct.
            if field["required"] or field["value"]:
                raise ValueError(f"Approve an exact answer for: {label}")
            continue
        if field["choices"]:
            if value not in field["choices"]:
                raise ValueError(f"Approved answer does not match available choices: {label}")
            locator.select_option(label=value)
        else:
            locator.fill(value)


class LinkedInBrowser:
    """A bounded Easy Apply adapter. Site changes fail closed rather than guess."""

    def __init__(self, data: Path, profile: Profile):
        self.data, self.profile = data, profile

    def context(self, playwright: Playwright, *, headless: bool = True) -> BrowserContext:
        return playwright.chromium.launch_persistent_context(
            str(self.data / "browser" / "linkedin"),
            headless=headless,
            accept_downloads=False,
            viewport={"width": 1365, "height": 900},
            **browser_options(),
        )

    def search(self, keywords: str, location: str, limit: int = 10) -> list[Job]:
        jobs: list[Job] = []
        with sync_playwright() as playwright, self.context(playwright) as context:
            page = context.new_page()
            page.goto(
                "https://www.linkedin.com/jobs/search/?"
                + urlencode({"keywords": keywords, "location": location, "f_AL": "true"}),
                wait_until="domcontentloaded",
            )
            ensure_linkedin(page)
            page.locator('a[href*="/jobs/view/"]').first.wait_for(timeout=15000)
            links = page.locator('a[href*="/jobs/view/"]').evaluate_all(
                "nodes => nodes.map(n=>n.href)"
            )
            urls = list(dict.fromkeys(re.sub(r"\?.*$", "", link) for link in links))[:limit]
            for url in urls:
                job_id = linkedin_job_id(url)
                page.goto(url, wait_until="domcontentloaded")
                ensure_linkedin(page)
                title = page.locator("h1").first.inner_text(timeout=10000).strip()
                company = (
                    page.locator(".job-details-jobs-unified-top-card__company-name")
                    .first.inner_text(timeout=10000)
                    .strip()
                )
                description = page.locator("#job-details").inner_text(timeout=10000).strip()
                actual_location = (
                    page.locator(
                        ".job-details-jobs-unified-top-card__tertiary-description-container"
                    )
                    .first.inner_text(timeout=10000)
                    .split("·")[0]
                    .strip()
                )
                jobs.append(
                    Job(
                        source="linkedin",
                        source_id=job_id,
                        title=title,
                        company=company,
                        location=actual_location,
                        url=url,
                        description=description,
                    )
                )
        return jobs

    def contacts(self, location: str, limit: int = 3) -> list[dict[str, str]]:
        from .networking import european_location, target_url

        contacts: list[dict[str, str]] = []
        with sync_playwright() as playwright, self.context(playwright) as context:
            page = context.new_page()
            page.goto(
                "https://www.linkedin.com/search/results/people/?"
                + urlencode({"keywords": f"Technical recruiter {location}"}),
                wait_until="domcontentloaded",
            )
            ensure_linkedin(page)
            page.locator('a[href*="/in/"]').first.wait_for(timeout=15000)
            links = page.locator('a[href*="/in/"]').evaluate_all("nodes => nodes.map(n=>n.href)")
            for url in list(dict.fromkeys(links))[:limit]:
                url = target_url(url)
                page.goto(url, wait_until="domcontentloaded")
                ensure_linkedin(page)
                main = page.get_by_role("main")
                name = main.locator("h1").first.inner_text(timeout=10000).strip()
                role = (
                    main.locator(".text-body-medium.break-words")
                    .first.inner_text(timeout=10000)
                    .strip()
                )
                actual_location = (
                    main.locator(".text-body-small.inline.t-black--light.break-words")
                    .first.inner_text(timeout=10000)
                    .strip()
                )
                if any(
                    term in role.casefold() for term in ("recruit", "talent", "hiring")
                ) and european_location(actual_location):
                    contacts.append(
                        {"url": url, "name": name, "role": role, "location": actual_location}
                    )
        return contacts

    def submit(self, job: Job, answers: dict[str, str], folder: Path) -> str:
        progress = {"submitted": False}
        try:
            return self._submit(job, answers, folder, progress)
        except Exception as exc:
            if not progress["submitted"]:
                raise ReviewRequired(str(exc)[:2000]) from exc
            raise

    def _submit(
        self, job: Job, answers: dict[str, str], folder: Path, progress: dict[str, bool]
    ) -> str:
        if linkedin_job_id(job.url) != job.source_id:
            raise ValueError("LinkedIn job identifier does not match the reviewed opportunity")
        with sync_playwright() as playwright, self.context(playwright) as context:
            page = context.new_page()
            page.goto(job.url, wait_until="domcontentloaded")
            ensure_linkedin(page)
            if page.locator("h1").first.inner_text(timeout=10000).strip() != job.title:
                raise ValueError("Job title changed; re-import and review")
            company = (
                page.locator(".job-details-jobs-unified-top-card__company-name")
                .first.inner_text(timeout=10000)
                .strip()
            )
            if company != job.company:
                raise ValueError("Company changed; re-import and review")
            current_description = page.locator("#job-details").inner_text(timeout=10000).strip()
            if " ".join(current_description.split()) != " ".join(job.description.split()):
                raise ValueError("Job description changed; re-import and review")
            page.get_by_role("button", name=re.compile(r"^Easy Apply\b")).first.click(timeout=10000)
            for _step in range(10):
                ensure_linkedin(page)
                dialog = page.get_by_role("dialog")
                dialog.wait_for(timeout=10000)
                fill_questions(page, self.profile)
                uploads = dialog.locator('input[type="file"]')
                for index in range(uploads.count()):
                    upload = uploads.nth(index)
                    label = upload.evaluate(
                        "el => (el.getAttribute('aria-label') || el.labels?.[0]?.textContent || el.id || '').toLowerCase()"
                    )
                    if uploads.count() > 1 and not any(
                        term in label for term in ("cover", "resume", "cv")
                    ):
                        raise ValueError("Ambiguous upload field requires manual review")
                    is_cover = "cover" in label.casefold()
                    suffix = "_Cover_Letter.pdf" if is_cover else "_CV.pdf"
                    candidate = folder / (filename_stem(self.profile, job) + suffix)
                    if not candidate.is_file():
                        raise ValueError(
                            "Expected the verified document for this job and candidate"
                        )
                    upload.set_input_files(str(candidate))
                submit = dialog.get_by_role("button", name="Submit application", exact=True)
                if submit.count():
                    # Do not follow companies as an implicit side effect of submission.
                    follow = dialog.get_by_label(re.compile(r"^Follow .+ to stay up to date"))
                    if follow.count():
                        follow.uncheck()
                    progress["submitted"] = True
                    submit.click()
                    page.get_by_text(
                        re.compile(r"Your application was sent|Application submitted"), exact=False
                    ).first.wait_for(timeout=15000)
                    return f"linkedin:{job.source_id}:confirmed"
                next_button = dialog.get_by_role("button", name=re.compile(r"^(Next|Review)$"))
                if next_button.count() != 1:
                    raise ValueError("Unsupported Easy Apply step; review manually")
                next_button.click()
                page.wait_for_timeout(600)
            raise ValueError("Easy Apply exceeded the ten-step limit")


class FixtureBrowser:
    """A real-browser submission adapter for the explicitly local test fixture."""

    def submit(self, job: Job, answers: dict[str, str], folder: Path) -> str:
        parsed = urlsplit(job.url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("Fixture submissions must remain on loopback")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, **browser_options())
            try:
                page = browser.new_page()
                page.goto(job.url)
                if urlsplit(page.url).netloc != parsed.netloc:
                    raise ValueError("Unexpected fixture redirect")
                for key, value in answers.items():
                    page.get_by_label(key, exact=True).fill(value)
                page.get_by_label("CV", exact=True).set_input_files(
                    str(next(folder.glob("*_CV.pdf")))
                )
                page.get_by_role("button", name="Submit application", exact=True).click()
                receipt = page.locator("#receipt").inner_text(timeout=10000)
                if not receipt.startswith("fixture:"):
                    raise ValueError("Missing fixture receipt")
                return receipt
            finally:
                browser.close()


def describe_questions(fields: list[dict[str, Any]]) -> list[Question]:
    return [
        Question(
            id=f"field_{index}",
            label=field["label"],
            required=field["required"],
            choices=field["choices"],
        )
        for index, field in enumerate(fields)
    ]
