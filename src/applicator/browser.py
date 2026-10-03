"""Dedicated local browser automation with fixed origins and explicit form contracts."""

import os
import re
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import BrowserContext, Locator, Page, Playwright, sync_playwright
from playwright.sync_api import Error as BrowserError

from .documents import filename_stem
from .models import Job, Profile, Question
from .photos import save_photo


class BrowserOptions(TypedDict, total=False):
    channel: str


class ReviewRequired(ValueError):
    """A provider stopped before attempting an irreversible submission."""


PENDING_INVITATION_NAME = re.compile(r"^(?:Pending|Invitation pending)(?:$|[,\s])")


def pending_invitation_action(card: Locator) -> Locator:
    """Read a visible pending control belonging to the verified member's card."""
    return (
        card.get_by_role("button", name=PENDING_INVITATION_NAME)
        .or_(card.get_by_role("link", name=PENDING_INVITATION_NAME))
        .filter(visible=True)
    )


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


def job_details(page: Page, expected_id: str) -> Job:
    """Read the primary job header and description on a verified detail URL."""
    ensure_linkedin(page)
    if linkedin_job_id(page.url) != expected_id:
        raise ReviewRequired("LinkedIn opened a different job; re-import and review")
    main = page.get_by_role("main")
    main.locator(
        '.job-details-jobs-unified-top-card__company-name, [aria-label^="Company, "]'
    ).first.wait_for(timeout=10000)
    legacy = main.locator(".job-details-jobs-unified-top-card__company-name")
    if legacy.count():
        selectors = {
            "title": "h1",
            "company": ".job-details-jobs-unified-top-card__company-name",
            "location": ".job-details-jobs-unified-top-card__tertiary-description-container",
            "description": "#job-details",
        }
        main.locator("#job-details").wait_for(timeout=10000)
        if any(main.locator(selector).count() != 1 for selector in selectors.values()):
            raise ReviewRequired("LinkedIn job details are ambiguous; review this job manually")
        details = {
            key: main.locator(selector).inner_text().strip() for key, selector in selectors.items()
        }
        details["location"] = details["location"].split("\u00b7")[0].strip()
    else:
        main.get_by_role("heading", name="About the job", exact=True).wait_for(timeout=10000)
        details = main.evaluate(r"""main => {
          const text = el => el?.textContent.trim() || '';
          // Current job detail pages use paragraphs and generated CSS classes.
          // The company label, its link, and the preceding title/location rows
          // identify the primary header without reading recommended jobs.
          const company = main.querySelector('[aria-label^="Company, "]');
          if (!company) return null;
          let header = company.parentElement;
          let identity = null;
          for (let depth=0; header && header!==main && depth<12; depth++,header=header.parentElement) {
            if (header.querySelectorAll('[aria-label^="Company, "]').length!==1) break;
            const rows = [...header.children];
            const metadata = rows.filter(el=>el.tagName==='P' && el.firstElementChild?.tagName==='SPAN' && text(el.firstElementChild));
            if (metadata.length!==1) continue;
            const titles = rows.slice(0,rows.indexOf(metadata[0])).filter(el=>!el.contains(company))
              .flatMap(row=>[...row.querySelectorAll('p')]);
            const links = [...company.querySelectorAll('a[href*="/company/"]')].filter(link=>text(link));
            if (titles.length!==1 || links.length!==1 || company.getAttribute('aria-label')!==`Company, ${text(links[0])}.`) return null;
            const link = new URL(links[0].href);
            if (link.origin!=='https://www.linkedin.com' || !link.pathname.startsWith('/company/')) return null;
            identity = {title:text(titles[0]),company:text(links[0]),location:text(metadata[0].firstElementChild)};
            break;
          }
          if (!identity) return null;
          const headings = [...main.querySelectorAll('h2,[role="heading"]')].filter(el=>text(el)==='About the job');
          if (headings.length!==1) return null;
          let section = headings[0].parentElement;
          for (let depth=0; section && section!==main && depth<8; depth++,section=section.parentElement) {
            const body = [...section.children].filter(el=>el.tagName==='P' && text(el));
            if (!body.length) continue;
            if (section.querySelectorAll('h1,h2,[role="heading"]').length!==1) return null;
            const clone = section.cloneNode(true);
            clone.querySelectorAll('h2,[role="heading"],button,script,style,svg').forEach(el=>el.remove());
            clone.querySelectorAll('p,li,br').forEach(el=>{el.prepend('\n');el.append('\n');});
            return {...identity,description:clone.textContent.replace(/\n[ \t]*\n(?:[ \t]*\n)*/g,'\n\n').trim()};
          }
          return null;
        }""")
    if not details or any(
        not isinstance(details.get(key), str)
        or not details[key].strip()
        or len(details[key]) > maximum
        for key, maximum in (
            ("title", 200),
            ("company", 200),
            ("location", 200),
            ("description", 40000),
        )
    ):
        raise ReviewRequired(
            "LinkedIn job details are incomplete or unsupported; review this job manually"
        )
    return Job(
        source="linkedin",
        source_id=expected_id,
        url=f"https://www.linkedin.com/jobs/view/{expected_id}/",
        title=details["title"],
        company=details["company"],
        location=details["location"],
        description=details["description"],
    )


def member_details(page: Page) -> dict[str, str]:
    """Read only the primary profile card, using explicit legacy or semantic contracts."""
    ensure_linkedin(page)
    profile_path = urlsplit(page.url).path.rstrip("/")
    if not re.fullmatch(r"/in/[a-zA-Z0-9%_-]+", profile_path):
        raise ReviewRequired("Expected a LinkedIn member profile before reading identity")
    main = page.get_by_role("main")
    main.locator("h1, h2").first.wait_for(timeout=10000)
    details = main.evaluate(
        r"""(main, profilePath) => {
      const text = el => el?.textContent.trim() || '';
      const name = main.querySelector('h1');
      const role = main.querySelector('.text-body-medium.break-words');
      const location = main.querySelector('.text-body-small.inline.t-black--light.break-words');
      if (name && role && location && main.querySelectorAll('h1').length===1
          && main.querySelectorAll('.text-body-medium.break-words').length===1
          && main.querySelectorAll('.text-body-small.inline.t-black--light.break-words').length===1)
        return {name:text(name), role:text(role), location:text(location)};
      if (name) return null;
      // The current profile card has an h2, direct headline paragraphs and a
      // separate location row anchored by its contact-information overlay link.
      // Generated CSS classes vary per request; do not bind to those classes.
      const heading = main.querySelector('h2');
      if (!heading) return null;
      let card = heading.parentElement;
      for (let depth=0; card && card!==main && depth<12; depth++,card=card.parentElement) {
        if (card.querySelectorAll('h1,h2').length!==1) continue;
        const headline = [...card.children].find(el=>el.tagName==='P' && text(el));
        const rows = [...card.children].filter(el=>el.tagName==='DIV' && [...el.querySelectorAll('a[href*="/overlay/contact-info/"]')].some(link=>
          new URL(link.href).pathname.replace(/\/$/,'')===profilePath+'/overlay/contact-info'));
        if (!headline || rows.length!==1) continue;
        const locations = [...rows[0].children].filter(el=>el.tagName==='P' && text(el) && !el.querySelector('a') && !/^[·•|]$/.test(text(el)));
        if (locations.length===1) return {name:text(heading),role:text(headline),location:text(locations[0])};
      }
      return null;
    }""",
        profile_path,
    )
    if not details or any(
        not isinstance(details.get(key), str)
        or not details[key].strip()
        or len(details[key]) > maximum
        for key, maximum in (("name", 150), ("role", 300), ("location", 150))
    ):
        raise ReviewRequired(
            "LinkedIn profile details are unavailable or the layout is unsupported. "
            "Review the profile manually or queue a contact with its displayed name, role and location."
        )
    return {key: str(details[key]).strip() for key in ("name", "role", "location")}


def member_action_scope(page: Page, details: dict[str, str]) -> Locator:
    """Find the primary card's actions, excluding recommendation sections."""
    main = page.get_by_role("main")
    action_name = re.compile(
        r"^Connect$|^Invite .+ to connect$|^More(?: options| actions(?: for .+)?)?$|^Follow(?:ing)?(?: .+)?$|^Message(?: .+)?$|"
        + PENDING_INVITATION_NAME.pattern
    )
    main.get_by_role("button", name=action_name).or_(
        main.get_by_role(
            "link",
            name=re.compile(r"^Connect$|^Invite .+ to connect$|" + PENDING_INVITATION_NAME.pattern),
        )
    ).filter(visible=True).first.wait_for(timeout=10000)
    card = main.locator("h1, h2").first
    fallback = None
    for _depth in range(12):
        card = card.locator("xpath=..")
        if card.evaluate("el => el.tagName === 'MAIN'"):
            break
        if card.locator("h1, h2").count() != 1:
            continue
        text = " ".join(card.inner_text().casefold().split())
        if not all(
            " ".join(details[key].casefold().split()) in text for key in ("role", "location")
        ):
            continue
        primary_action = (
            card.get_by_role(
                "button",
                name=re.compile(
                    r"^Connect$|^Invite .+ to connect$|^More(?: options| actions(?: for .+)?)?$"
                ),
            )
            .or_(card.get_by_role("link", name=re.compile(r"^Connect$|^Invite .+ to connect$")))
            .filter(visible=True)
        )
        if primary_action.count():
            return card
        if (
            card.get_by_role("button", name=action_name).filter(visible=True).count()
            or pending_invitation_action(card).count()
        ):
            fallback = card
    if fallback is not None:
        return fallback
    raise ReviewRequired(
        "The primary member's connection controls are unavailable. Review this profile."
    )


def capture_member_photo(page: Page, data: Path, url: str, details: dict[str, str]) -> bool:
    """Capture one square portrait in the verified primary member section only."""
    try:
        ensure_linkedin(page)
        if page.url.rstrip("/") != url.rstrip("/"):
            return False
        main = page.get_by_role("main")
        card = main.locator("h1, h2").first
        for _depth in range(12):
            card = card.locator("xpath=..")
            if card.evaluate("el => el.tagName === 'MAIN'"):
                break
            if card.locator("h1, h2").count() != 1:
                continue
            headings = card.locator("h1, h2")
            if headings.first.inner_text().strip() != details["name"]:
                continue
            text = " ".join(card.inner_text().casefold().split())
            if not all(
                " ".join(details[key].casefold().split()) in text for key in ("role", "location")
            ):
                continue
            images = card.locator("img").filter(visible=True)
            candidates = []
            for index in range(images.count()):
                image = images.nth(index)
                size = image.bounding_box()
                if (
                    size
                    and 56 <= size["width"] <= 512
                    and 56 <= size["height"] <= 512
                    and abs(size["width"] - size["height"]) <= 2
                ):
                    candidates.append(image)
            if len(candidates) > 1:
                return False
            if len(candidates) == 1:
                image = candidates[0]
                if not image.evaluate("image => image.complete"):
                    page.wait_for_function(
                        "image => image.complete",
                        arg=image.element_handle(),
                        timeout=2000,
                    )
                if not image.evaluate("image => image.complete && image.naturalWidth > 0"):
                    return False
                return save_photo(
                    data, url, image.screenshot(type="png", timeout=3000, animations="disabled")
                )
    except (BrowserError, ValueError, OSError):
        return False
    return False


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


def application_dialog(page: Page) -> Locator:
    """Wait for one visible native or ARIA dialog and its rendered form controls."""
    dialog = page.get_by_role("dialog").filter(visible=True)
    dialog.wait_for(timeout=10000)
    controls = dialog.locator('input:not([type="hidden"]), select, textarea')
    actions = dialog.get_by_role("button", name=re.compile(r"^(Next|Review|Submit application)$"))
    controls.or_(actions).filter(visible=True).first.wait_for(timeout=10000)
    return dialog


def application_step(dialog: Locator) -> str:
    """Identify form controls and navigation without recording personal field values."""
    return str(
        dialog.evaluate(r"""dialog => JSON.stringify({
      fields:[...dialog.querySelectorAll('input,select,textarea')].map(el=>[el.id,el.type]),
      actions:[...dialog.querySelectorAll('button')].filter(el=>el.checkVisibility() && /^(Next|Review|Submit application)$/.test(el.textContent.trim())).map(el=>el.textContent.trim())
    })""")
    )


def form_questions(page: Page) -> list[dict[str, Any]]:
    # DOM inspection is data extraction, not execution of site-supplied instructions.
    return list(
        application_dialog(page).evaluate(r"""dialog => {
      const text = el => el?.textContent.trim() || '';
      const unmark = value => value.replace(/\s*\*$/, '').trim();
      const groupFor = el => el.closest('fieldset,[role="radiogroup"]');
      const semanticGroup = el => {
        const group = groupFor(el);
        if (!group || group.getAttribute('role')!=='radiogroup') return null;
        const siblings = [...group.parentElement.children];
        const labels = siblings.slice(0,siblings.indexOf(group)).filter(node=>node.tagName==='P' && text(node));
        if (labels.length!==1) return null;
        const label = unmark(text(labels[0]));
        const cards = [...group.querySelectorAll('[role="radio"]')];
        const inputs = [...group.querySelectorAll('input[type="radio"]')];
        if (!label || cards.length<2 || cards.length!==inputs.length || cards.some(card=>card.querySelectorAll('input[type="radio"]').length!==1 || unmark(card.getAttribute('aria-label') || '')!==label)) return null;
        return {label,required:text(labels[0]).endsWith('*')};
      };
      const widget = el => el.type==='checkbox' ? el.closest('[role="checkbox"]') : null;
      const required = el => el.required || el.getAttribute('aria-required') === 'true' || widget(el)?.getAttribute('aria-required') === 'true' || (el.type==='radio' && (groupFor(el)?.getAttribute('aria-required')==='true' || semanticGroup(el)?.required));
      const labelText = el => {
        const label=el.labels?.[0]?.cloneNode(true);
        if(label) label.querySelectorAll('input,select,textarea,[aria-hidden="true"]').forEach(n=>n.remove());
        const choice = el.type==='radio' && semanticGroup(el) ? text(el.closest('[role="radio"]')) : '';
        const value = (text(label) || el.getAttribute('aria-label') || widget(el)?.getAttribute('aria-label') || choice || '').trim();
        return required(el) ? unmark(value) : value;
      };
      const groupLabel = el => text(groupFor(el)?.querySelector('legend')) || groupFor(el)?.getAttribute('aria-label') || semanticGroup(el)?.label || '';
      return [...dialog.querySelectorAll('input,select,textarea')]
      .filter(el => el.type !== 'hidden' && el.type !== 'file' && !['submit','button'].includes(el.type))
      .map(el => ({id:el.id, type:el.type, value:el.value, checked:el.checked || ['true','mixed'].includes(widget(el)?.getAttribute('aria-checked')),
        label:labelText(el),
        group:el.type === 'radio' ? (required(el) ? unmark(groupLabel(el)) : groupLabel(el).trim()) : '',
        group_choices:el.type === 'radio' && el.name ? [...(groupFor(el) || dialog).querySelectorAll('input[type=radio]')].filter(other=>other.name===el.name).map(labelText) : [],
        required:!!required(el),
        choices:el.tagName === 'SELECT' ? [...el.options].map(o=>o.text) : []}));}""")
    )


def contact_phone_answers(fields: list[dict[str, Any]], profile: Profile) -> dict[str, str]:
    """Split an approved international phone only against the form's country choices."""
    countries = [
        field for field in fields if str(field["label"]).casefold() == "phone country code"
    ]
    if not countries:
        return {}
    phones = [
        field
        for field in fields
        if str(field["label"]).casefold() in {"phone number", "mobile phone number"}
    ]
    if len(countries) != 1 or len(phones) != 1:
        raise ValueError("Ambiguous phone controls require manual review")
    country, phone = countries[0], phones[0]
    country_label, phone_label = str(country["label"]), str(phone["label"])
    number = approved_answer(phone_label, profile)
    country_answer = approved_answer(country_label, profile)
    if not number:
        raise ValueError(f"Approve an exact answer for: {phone_label}")
    if country_answer and country_answer not in country["choices"]:
        raise ValueError(f"Approved answer does not match available choices: {country_label}")
    if country_answer and not number.startswith("+"):
        return {country_label: country_answer, phone_label: number}
    digits = re.sub(r"[ ()-]", "", number)
    if not re.fullmatch(r"\+[1-9]\d{7,14}", digits):
        raise ValueError(f"Approve an exact answer for: {country_label}")
    matches = []
    for choice in country["choices"]:
        match = re.search(r"\(\+(\d{1,4})\)$", choice)
        if match and digits[1:].startswith(match[1]) and len(digits[1:]) > len(match[1]):
            matches.append((choice, match[1]))
    if country_answer:
        matches = [item for item in matches if item[0] == country_answer]
        if not matches:
            raise ValueError(
                "Approved phone country code does not match the approved international phone number"
            )
    else:
        longest = max((len(item[1]) for item in matches), default=0)
        matches = [item for item in matches if len(item[1]) == longest]
    if len(matches) != 1:
        raise ValueError(f"Approve an exact answer for: {country_label}")
    choice, prefix = matches[0]
    return {country_label: choice, phone_label: digits[1 + len(prefix) :]}


def upload_resume(page: Page, dialog: Locator, document: Path) -> set[str] | None:
    """Upload the verified CV through the current résumé widget and confirm selection."""
    button = dialog.get_by_role("button", name="Upload resume", exact=True).filter(visible=True)
    if not button.count():
        return None
    if button.count() != 1:
        raise ValueError("Ambiguous resume upload controls require manual review")
    if not document.is_file():
        raise ValueError("Expected the verified document for this job and candidate")
    scope = button
    for _depth in range(8):
        scope = scope.locator("xpath=..")
        if scope.evaluate("el => el.tagName==='DIALOG' || el.getAttribute('role')==='dialog'"):
            raise ValueError("The resume upload section is unsupported; review manually")
        if scope.get_by_text(re.compile(r"^Resume\s*\*?$"), exact=True).count() == 1:
            break
    else:
        raise ValueError("The resume upload section is unsupported; review manually")
    if dialog.locator('input[type="file"]').count() != scope.locator('input[type="file"]').count():
        raise ValueError("Additional upload fields require manual mapping")
    with page.expect_file_chooser(timeout=10000) as chooser:
        button.click()
    chooser.value.set_files(str(document))
    filename = scope.get_by_text(document.name, exact=True)
    filename.wait_for(timeout=10000)
    card = filename
    for _depth in range(8):
        card = card.locator("xpath=..")
        if (
            card.locator('[role="radio"]').count() == 1
            and card.locator('input[type="radio"]').count() == 1
        ):
            break
        if card.evaluate("(el, root) => el===root", scope.element_handle()):
            raise ValueError("The uploaded resume selection is ambiguous; review manually")
    else:
        raise ValueError("The uploaded resume selection is unsupported; review manually")
    card.locator('[role="radio"][aria-checked="true"]').wait_for(timeout=10000)
    if not card.locator('input[type="radio"]').is_checked():
        raise ValueError("The uploaded resume is not selected; review manually")
    ids = scope.locator('input[type="radio"]').evaluate_all("""inputs => {
      const documentLabel = text => !text.trim() || /\\.(?:pdf|docx?)\\b/i.test(text);
      const resumeLabel = text => !text.trim() || /^Resume\\s*\\*?$/i.test(text.trim());
      if (inputs.some(el=>{
        const group = el.closest('fieldset,[role="radiogroup"]');
        const groupLabel = group?.querySelector('legend')?.textContent || group?.getAttribute('aria-label') ||
          (group?.getAttribute('aria-labelledby') || '').split(/\\s+/).map(id=>document.getElementById(id)?.textContent || '').join(' ');
        return !el.id || !el.closest('[role="radio"]') || !resumeLabel(groupLabel) ||
          !documentLabel(el.getAttribute('aria-label') || '') || [...el.labels].some(label=>!documentLabel(label.textContent));
      })) return null;
      return inputs.map(el=>el.id);
    }""")
    if (
        not ids
        or len(set(ids)) != len(ids)
        or dialog.locator("input,select,textarea").evaluate_all(
            "(inputs, ids) => inputs.filter(el=>ids.includes(el.id)).length", ids
        )
        != len(ids)
    ):
        raise ValueError("Resume controls overlap with questionnaire fields; review manually")
    return set(ids)


def fill_questions(
    page: Page, profile: Profile, *, resume_field_ids: set[str] | None = None
) -> None:
    fields = form_questions(page)
    phone_answers = contact_phone_answers(fields, profile)
    dialog = page.get_by_role("dialog").filter(visible=True)
    for field in fields:
        label, field_id = str(field["label"]).strip(), str(field["id"])
        if resume_field_ids and field_id in resume_field_ids:
            continue
        if field["type"] == "checkbox" and not field["required"] and not field.get("checked"):
            continue
        if not label or not field_id:
            raise ValueError("Unlabelled form control requires manual review")
        locator = dialog.locator('[id="' + field_id.replace('"', '\\"') + '"]')
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
                card = locator.locator("xpath=ancestor::*[@role='radio'][1]")
                if card.count() == 1 and card.is_visible():
                    if card.get_attribute("aria-checked") != "true":
                        card.click()
                    if card.get_attribute("aria-checked") != "true" or not locator.is_checked():
                        raise ValueError(
                            "The approved radio answer was not selected; review manually"
                        )
                else:
                    locator.check()
            continue
        if field["type"] == "checkbox":
            if re.fullmatch(r"Follow .+ to stay up to date.*", label):
                locator.uncheck()
                continue
            raise ValueError(f"Explicit selection or consent requires manual review: {label}")
        value = phone_answers.get(label) or approved_answer(label, profile)
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

    def __init__(self, data: Path, profile: Profile | None = None):
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
        if not 1 <= limit <= 10:
            raise ValueError("Job discovery limit must be between 1 and 10")
        jobs: list[Job] = []
        with sync_playwright() as playwright, self.context(playwright) as context:
            page = context.new_page()
            page.goto(
                "https://www.linkedin.com/jobs/search/?"
                + urlencode({"keywords": keywords, "location": location, "f_AL": "true"}),
                wait_until="domcontentloaded",
            )
            ensure_linkedin(page)
            main = page.get_by_role("main")
            links_locator = main.locator('a[href*="/jobs/view/"]')
            empty = main.get_by_role(
                "heading",
                name=re.compile(
                    r"^(?:No (?:matching )?jobs found|No (?:matching )?results found)[.!]?$", re.I
                ),
            )
            links_locator.or_(empty).filter(visible=True).first.wait_for(timeout=15000)
            ensure_linkedin(page)
            if not links_locator.count() and empty.filter(visible=True).count():
                return []
            results = main.locator(".jobs-search-results-list, .scaffold-layout__list")
            if results.count():
                links_locator = results.locator('a[href*="/jobs/view/"]')
                links_locator.first.wait_for(timeout=10000)
            links = links_locator.evaluate_all("nodes => nodes.map(n=>n.href)")
            ids: list[str] = []
            for link in links:
                try:
                    job_id = linkedin_job_id(link)
                except ValueError:
                    continue
                if job_id not in ids:
                    ids.append(job_id)
            if not ids:
                raise ReviewRequired(
                    "LinkedIn search has no supported job links; review the search manually"
                )
            for job_id in ids[:limit]:
                url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                page.goto(url, wait_until="domcontentloaded")
                jobs.append(job_details(page, job_id))
        return jobs

    def contacts(
        self, location: str, limit: int = 3, *, exclude_urls: set[str] | None = None
    ) -> list[dict[str, str]]:
        from .networking import european_location, target_url

        if not 1 <= limit <= 10:
            raise ValueError("Recruiter discovery limit must be between 1 and 10")
        contacts: list[dict[str, str]] = []
        with sync_playwright() as playwright, self.context(playwright) as context:
            page = context.new_page()
            page.goto(
                "https://www.linkedin.com/search/results/people/?"
                + urlencode({"keywords": f"Technical recruiter {location}"}),
                wait_until="domcontentloaded",
            )
            ensure_linkedin(page)
            main = page.get_by_role("main")
            main.locator('a[href*="/in/"]').first.wait_for(timeout=15000)
            cards = main.locator('[role="listitem"]')
            if cards.count():
                # Each result card can also link to mutual connections. Only its
                # primary member link belongs to the searched result.
                links = cards.evaluate_all(
                    "cards => cards.map(card=>card.querySelector('a[href*=\"/in/\"]')?.href).filter(Boolean)"
                )
            else:
                links = main.locator('a[href*="/in/"]').evaluate_all(
                    "nodes => nodes.map(n=>n.href)"
                )
            urls: list[str] = []
            for link in links:
                try:
                    url = target_url(link)
                except ValueError:
                    continue
                if url not in urls and url not in (exclude_urls or set()):
                    urls.append(url)
            # Review at most ten new primary results to fill the requested
            # number of eligible contacts, rather than counting rejected ones.
            for url in urls[:10]:
                page.goto(url, wait_until="domcontentloaded")
                ensure_linkedin(page)
                if target_url(page.url) != url:
                    raise ReviewRequired(
                        "LinkedIn member identity changed; review the search result"
                    )
                details = member_details(page)
                role, actual_location = details["role"], details["location"]
                if any(
                    term in role.casefold() for term in ("recruit", "talent", "hiring")
                ) and european_location(actual_location):
                    contacts.append({"url": url, **details})
                    capture_member_photo(page, self.data, url, details)
                    if len(contacts) >= limit:
                        break
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
        if self.profile is None:
            raise ReviewRequired("Configure a candidate profile before submitting applications")
        if linkedin_job_id(job.url) != job.source_id:
            raise ValueError("LinkedIn job identifier does not match the reviewed opportunity")
        with sync_playwright() as playwright, self.context(playwright) as context:
            page = context.new_page()
            page.goto(job.url, wait_until="domcontentloaded")
            current_job = job_details(page, job.source_id)
            if current_job.title != job.title:
                raise ValueError("Job title changed; re-import and review")
            if current_job.company != job.company:
                raise ValueError("Company changed; re-import and review")
            if current_job.location != job.location:
                raise ValueError("Job location changed; re-import and review")
            if " ".join(current_job.description.split()) != " ".join(job.description.split()):
                raise ValueError("Job description changed; re-import and review")
            page.get_by_role("button", name=re.compile(r"^Easy Apply\b")).first.click(timeout=10000)
            seen_steps: set[str] = set()
            for _step in range(10):
                ensure_linkedin(page)
                dialog = application_dialog(page)
                if application_step(dialog) in seen_steps:
                    raise ValueError(
                        "The application did not advance; review the form's validation messages"
                    )
                cv = folder / (filename_stem(self.profile, job) + "_CV.pdf")
                resume_fields = upload_resume(page, dialog, cv)
                fill_questions(page, self.profile, resume_field_ids=resume_fields)
                uploads = dialog.locator('input[type="file"]')
                for index in range(uploads.count() if resume_fields is None else 0):
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
                seen_steps.add(application_step(dialog))
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
