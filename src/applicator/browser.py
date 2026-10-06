"""Dedicated local browser automation with fixed origins and explicit form contracts."""

import hashlib
import json
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from html import escape
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import (
    BrowserContext,
    ElementHandle,
    JSHandle,
    Locator,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import Error as BrowserError

from .documents import digest, filename_stem
from .location_policy import country, normalise_location
from .models import FormContext, Job, Profile, Question
from .photos import save_photo
from .submission_records import capture_confirmation


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
        raise ValueError(
            "LinkedIn requires login or verification in the dedicated browser session. "
            "Pause automation and run uv run python -m applicator.cli browser-login. "
            "Complete sign-in there, then press Enter to retain the session. "
            "Reprepare applications in review; reconcile uncertain submissions before retrying."
        )


@contextmanager
def linkedin_page(context: BrowserContext) -> Iterator[Page]:
    """Classify delayed authentication redirects without exposing provider diagnostics."""
    page = context.new_page()
    try:
        yield page
    except (BrowserError, ValueError):
        # LinkedIn can redirect after DOMContentLoaded, while a locator is waiting.
        # Recheck the current URL rather than reporting a missing job selector.
        ensure_linkedin(page)
        raise


def job_details(page: Page, expected_id: str, *, timeout: int = 10000) -> Job:
    """Read the primary job header and description on a verified detail URL."""
    ensure_linkedin(page)
    if linkedin_job_id(page.url) != expected_id:
        raise ReviewRequired("LinkedIn opened a different job; re-import and review")
    main = page.get_by_role("main")
    main.locator(
        '.job-details-jobs-unified-top-card__company-name, [aria-label^="Company, "]'
    ).first.wait_for(timeout=timeout)
    legacy = main.locator(".job-details-jobs-unified-top-card__company-name")
    if legacy.count():
        selectors = {
            "title": "h1",
            "company": ".job-details-jobs-unified-top-card__company-name",
            "location": ".job-details-jobs-unified-top-card__tertiary-description-container",
            "description": "#job-details",
        }
        main.locator("#job-details").wait_for(timeout=timeout)
        if any(main.locator(selector).count() != 1 for selector in selectors.values()):
            raise ReviewRequired("LinkedIn job details are ambiguous; review this job manually")
        details = {
            key: main.locator(selector).inner_text().strip() for key, selector in selectors.items()
        }
        details["location"] = details["location"].split("\u00b7")[0].strip()
    else:
        main.get_by_role("heading", name="About the job", exact=True).wait_for(timeout=timeout)
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
        "phone": profile.phone,
        "mobile phone number": profile.phone,
        "location (city)": profile.location,
    }
    return exact.get(" ".join(label.casefold().split())) or None


def application_dialog(page: Page) -> Locator:
    """Wait for one visible native or ARIA dialog and its rendered form controls."""
    dialog = page.get_by_role("dialog").filter(visible=True)
    dialog.wait_for(timeout=10000)
    controls = dialog.locator(
        'input:not([type="hidden"]), select, textarea, [role="checkbox"], [role="combobox"], [role="radio"], label[for], label:has(input)'
    )
    actions = dialog.get_by_role("button", name=re.compile(r"^(Next|Review|Submit application)$"))
    controls.or_(actions).filter(visible=True).first.wait_for(timeout=10000)
    return dialog


def application_step(dialog: Locator) -> str:
    """Identify form controls and navigation without recording personal field values."""
    return str(
        dialog.evaluate(r"""dialog => JSON.stringify({
      fields:[...dialog.querySelectorAll('input,select,textarea,[role="checkbox"],[role="combobox"],[role="radio"]')]
      .filter(el=>el.type!=='hidden' && (el.checkVisibility() || [...(el.labels || [])].some(label=>label.checkVisibility()) || el.closest('[role="checkbox"],[role="radio"]')?.checkVisibility()))
      .map(el=>{
        const text=node=>node?.textContent.trim() || '';
        const labelledBy=node=>(node?.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>text(document.getElementById(id))).join(' ');
        const label=el.labels?.[0]?.cloneNode(true);
        label?.querySelectorAll('input,select,textarea,[aria-hidden="true"]').forEach(node=>node.remove());
        const group=el.closest('fieldset,[role="radiogroup"]');
        return [el.type || el.getAttribute('role'),text(label) || el.getAttribute('aria-label') || labelledBy(el),
          text(group?.querySelector('legend')) || group?.getAttribute('aria-label') || labelledBy(group),
          el.closest('[role="radio"]')?.getAttribute('aria-label') || ''];
      }).sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b))),
      headings:[...dialog.querySelectorAll('h1,h2,h3,[role="heading"]')].filter(el=>el.checkVisibility()).map(el=>el.textContent.trim()),
      actions:[...dialog.querySelectorAll('button')].filter(el=>el.checkVisibility() && /^(Next|Review|Submit application)$/.test(el.textContent.trim())).map(el=>el.textContent.trim())
    })""")
    )


def form_questions(page: Page) -> list[dict[str, Any]]:
    # DOM inspection is data extraction, not execution of site-supplied instructions.
    return list(
        application_dialog(page).evaluate(r"""dialog => {
      const text = el => el?.textContent.trim() || '';
      const unmark = value => value.replace(/\s*\*$/, '').trim();
      const labelledBy = el => (el?.getAttribute('aria-labelledby') || '').split(/\s+/).map(id=>text(document.getElementById(id))).filter(Boolean).join(' ');
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
      const widget = el => el.closest('[role="checkbox"]');
      const locationField = el => {
        if (!el.matches('input[data-testid="typeahead-input"][aria-autocomplete="list"]') || el.getAttribute('placeholder')!=='Enter city or location') return null;
        const row=el.closest('[componentkey^="easyApplyFieldFocus"]');
        const labels=row && [...row.children].filter(node=>node.tagName==='P' && text(node));
        if (!labels || labels.length!==1 || row.querySelectorAll('input[data-testid="typeahead-input"]').length!==1 || unmark(text(labels[0]))!=='Location (city)' ||
          [text(el.labels?.[0]),el.getAttribute('aria-label'),labelledBy(el)].some(value=>value && unmark(value)!=='Location (city)')) return null;
        return {label:unmark(text(labels[0])),required:text(labels[0]).endsWith('*')};
      };
      const active = el => el.checkVisibility({visibilityProperty:true,opacityProperty:true}) || (['checkbox','radio'].includes(el.type) &&
        ([...(el.labels || [])].some(label=>label.checkVisibility({visibilityProperty:true,opacityProperty:true})) ||
          el.closest('[role="checkbox"],[role="radio"]')?.checkVisibility({visibilityProperty:true,opacityProperty:true})));
      const required = el => el.required || el.getAttribute('aria-required') === 'true' || widget(el)?.getAttribute('aria-required') === 'true' || locationField(el)?.required || (el.type==='radio' && (groupFor(el)?.getAttribute('aria-required')==='true' || semanticGroup(el)?.required));
      const labelText = el => {
        const label=el.labels?.[0]?.cloneNode(true);
        if(label) label.querySelectorAll('input,select,textarea,[aria-hidden="true"]').forEach(n=>n.remove());
        const choice = el.type==='radio' && semanticGroup(el) ? text(el.closest('[role="radio"]')) : '';
        const value = (text(label) || el.getAttribute('aria-label') || labelledBy(el) || widget(el)?.getAttribute('aria-label') || labelledBy(widget(el)) || locationField(el)?.label || choice || '').trim();
        return required(el) ? unmark(value) : value;
      };
      const groupLabel = el => text(groupFor(el)?.querySelector('legend')) || groupFor(el)?.getAttribute('aria-label') || labelledBy(groupFor(el)) || semanticGroup(el)?.label || '';
      return [...dialog.querySelectorAll('input,select,textarea,[role="combobox"],[role="checkbox"],[role="radio"]')]
      .filter(el => active(el) && !el.matches(':disabled') && !el.closest('[aria-disabled="true"]') && el.type !== 'hidden' && el.type !== 'file' && !(el.tagName==='INPUT' && ['submit','button','reset'].includes(el.type)) &&
        (!el.matches('[role="checkbox"]') || !el.querySelector('input[type="checkbox"]')) && (!el.matches('[role="radio"]') || !el.querySelector('input[type="radio"]')))
      .map(el => ({id:el.id, tag:el.tagName.toLowerCase(), type:locationField(el) ? 'location-typeahead' : el.getAttribute('role')==='combobox' ? 'combobox' : el.type || el.getAttribute('role'), value:el.value || el.getAttribute('aria-valuetext') || (el.getAttribute('role')==='combobox' ? text(el) : ''), checked:el.checked || ['true','mixed'].includes(widget(el)?.getAttribute('aria-checked')),
        label:labelText(el),
        group:el.type === 'radio' ? (required(el) ? unmark(groupLabel(el)) : groupLabel(el).trim()) : '',
        group_choices:el.type === 'radio' && el.name ? [...(groupFor(el) || dialog).querySelectorAll('input[type=radio]')].filter(other=>active(other) && other.name===el.name && !other.matches(':disabled') && !other.closest('[aria-disabled="true"]')).map(labelText) : [],
        required:!!required(el),
        constraints:Object.fromEntries(['type','role','min','max','step','minlength','maxlength','pattern','inputmode'].filter(name=>el.hasAttribute(name)).map(name=>[name,el.getAttribute(name).slice(0,200)])),
        choices:el.tagName === 'SELECT' ? [...el.options].filter(o=>!o.disabled && !o.closest('optgroup[disabled]') && o.value!=='').map(o=>o.label.trim()) : []}));}""")
    )


def question_context(field: dict[str, Any], label: str, choices: list[str]) -> FormContext:
    """Rebuild only semantic HTML; never transmit values, IDs, scripts or page markup."""
    control_type = str(field["type"])
    constraints = {
        key: str(value)[:200]
        for key, value in field.get("constraints", {}).items()
        if key
        in {"type", "role", "min", "max", "step", "minlength", "maxlength", "pattern", "inputmode"}
    }
    attributes = "".join(f' {escape(key)}="{escape(value)}"' for key, value in constraints.items())
    if field["required"]:
        attributes += ' aria-required="true"'
    tag = {"input": "input", "textarea": "textarea", "select": "select", "button": "button"}.get(
        str(field.get("tag", "")), "div"
    )
    options = "".join(f"<option>{escape(choice)}</option>" for choice in choices)
    opening = f'<{tag} data-control-type="{escape(control_type)}"{attributes}>'
    control = opening if tag == "input" else opening + options + f"</{tag}>"
    html = f"<label>{escape(label)}</label>" + control
    return FormContext(control_type=control_type, html=html, constraints=constraints)


def open_easy_apply(page: Page, progress: Callable[[str, str], None]) -> None:
    """Bounded opening recovery; never click again once a dialogue has appeared."""
    for attempt in range(3):
        ensure_linkedin(page)
        main = page.get_by_role("main")
        if main.count() == 1 and main.evaluate("""main => {
          const body=main.querySelector('#job-details') || [...main.querySelectorAll('h2,[role="heading"]')].find(el=>el.textContent.trim()==='About the job');
          return body && [...main.querySelectorAll('p,span')].some(el=>!el.children.length && el.checkVisibility() &&
            el.textContent.trim()==='No longer accepting applications' && (el.compareDocumentPosition(body)&Node.DOCUMENT_POSITION_FOLLOWING));
        }"""):
            raise ValueError("The LinkedIn opportunity is no longer accepting applications")
        if page.get_by_role("dialog").filter(visible=True).count():
            application_dialog(page)
            return
        actions = (
            main.get_by_role("button", name=re.compile(r"^Easy Apply\b"))
            .or_(main.get_by_role("link", name=re.compile(r"^Easy Apply\b")))
            .or_(main.locator("button").filter(has_text=re.compile(r"^\s*Easy Apply\s*$")))
            .filter(visible=True)
        )
        if not actions.count():
            # Some job layouts put the verified page's sticky action outside main.
            # Require one page action rather than selecting the first matching card.
            actions = (
                page.get_by_role("button", name=re.compile(r"^Easy Apply\b"))
                .or_(page.get_by_role("link", name=re.compile(r"^Easy Apply\b")))
                .or_(page.locator("button").filter(has_text=re.compile(r"^\s*Easy Apply\s*$")))
                .filter(visible=True)
            )
        try:
            actions.first.wait_for(timeout=2000)
            if actions.count() != 1:
                raise ValueError("Easy Apply controls are ambiguous; review the opportunity")
            href = actions.get_attribute("href", timeout=2000)
            if href is not None:
                target = urlsplit(actions.evaluate("el=>el.href"))
                current = urlsplit(page.url)
                if (target.scheme, target.netloc, target.path) != (
                    current.scheme,
                    current.netloc,
                    current.path,
                ):
                    raise ValueError("External application links require manual hand-off")
            actions.click(timeout=2000)
            ensure_linkedin(page)
            application_dialog(page)
            return
        except BrowserError:
            ensure_linkedin(page)
            progress("recovering_form", f"Re-reading Easy Apply controls ({attempt + 1}/3).")
    raise ValueError("Easy Apply control unavailable after three recovery passes")


def advance_application(
    page: Page,
    profile: Profile,
    *,
    resume_field_ids: set[str] | None,
    resolver: Callable[[Question], str | None] | None,
    progress: Callable[[str, str], None],
    memory: Callable[[str, str | None], str | None],
) -> None:
    """Retry an unchanged reversible Next/Review step, without repeating uploads."""
    original = application_step(application_dialog(page))
    for attempt in range(3):
        ensure_linkedin(page)
        dialog = application_dialog(page)
        if application_step(dialog) != original:
            return
        next_button = dialog.get_by_role("button", name=re.compile(r"^(Next|Review)$"))
        if next_button.count() != 1:
            raise ValueError("Unsupported Easy Apply step; review manually")
        next_button.click(timeout=2000)
        for _poll in range(10):
            page.wait_for_timeout(200)
            ensure_linkedin(page)
            dialog = application_dialog(page)
            if application_step(dialog) != original:
                return
        invalid = dialog.evaluate("""dialog => [...dialog.querySelectorAll('input,select,textarea,[aria-invalid="true"]')]
          .filter(el=>el.checkVisibility() && (el.getAttribute('aria-invalid')==='true' || el.checkValidity && !el.checkValidity()))
          .map(el=>{
            const label=el.labels?.[0]?.cloneNode(true);
            label?.querySelectorAll('input,select,textarea,[aria-hidden="true"]').forEach(node=>node.remove());
            return (label?.textContent.trim() || el.getAttribute('aria-label') || 'Unlabelled field').slice(0,500);
          })""")
        invalid.extend(
            dialog.evaluate("""dialog => [...dialog.querySelectorAll('[componentkey^="easyApplyFieldFocus"]')]
          .filter(row=>[...row.children].some(node=>['status','alert'].includes(node.getAttribute('role')) && node.checkVisibility() && node.textContent.trim()))
          .map(row=>[...row.children].find(node=>node.tagName==='P')?.textContent.trim().replace(/\\s*\\*$/,'') || 'Unlabelled field')""")
        )
        if invalid:
            raise ValueError(
                "The application did not advance; invalid fields: "
                + ", ".join(dict.fromkeys(invalid))
            )
        progress(
            "recovering_form", f"Re-reading and verifying unchanged form step ({attempt + 1}/3)."
        )
        fill_questions(
            page,
            profile,
            resume_field_ids=resume_field_ids,
            resolver=resolver,
            progress=progress,
            memory=memory,
        )
    raise ValueError(
        "The application did not advance after three recovery passes; inspect provider validation"
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
        if str(field["label"]).casefold() in {"phone", "phone number", "mobile phone number"}
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


def upload_resume(
    page: Page, dialog: Locator, document: Path, *, verified: dict[str, JSHandle] | None = None
) -> set[str] | None:
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
    named_cards = scope.locator('[role="radio"]').filter(
        has=page.get_by_text(document.name, exact=True).filter(visible=True)
    )
    selected = named_cards.locator('xpath=self::*[@aria-checked="true"]').filter(visible=True)
    native = selected.locator('input[type="radio"]')
    document_hash = digest(document)
    reused = (
        verified is not None
        and document_hash in verified
        and selected.count() == 1
        and native.count() == 1
        and native.is_checked()
        and native.evaluate("(el, previous) => el===previous", verified[document_hash])
    )
    previously_selected: list[ElementHandle] = []
    if not reused:
        previously_selected = named_cards.locator('input[type="radio"]:checked').element_handles()
        with page.expect_file_chooser(timeout=10000) as chooser:
            button.click()
        chooser.value.set_files(str(document))
        scope.get_by_text(document.name, exact=True).filter(visible=True).first.wait_for(
            timeout=10000
        )
        if not named_cards.count():
            raise ValueError("The uploaded resume selection is unsupported; review manually")
    selected.first.wait_for(timeout=10000)
    if selected.count() != 1 or selected.locator('input[type="radio"]').count() != 1:
        raise ValueError("The uploaded resume selection is ambiguous; review manually")
    if not native.is_checked():
        raise ValueError("The uploaded resume is not selected; review manually")
    if any(
        native.evaluate("(el, previous) => el===previous", previous)
        for previous in previously_selected
    ):
        raise ValueError(
            "The resume upload did not replace the previous selection; review manually"
        )
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
    if verified is not None:
        verified[document_hash] = native.evaluate_handle("el=>el")
    return set(ids)


def field_locator(dialog: Locator, field: dict[str, Any]) -> Locator:
    """Resolve one labelled control within the current application dialogue."""
    locator = (
        dialog.locator("[id=" + json.dumps(str(field["id"])) + "]")
        if field["id"]
        else dialog.get_by_label(str(field["label"]), exact=True)
    )
    if locator.count() != 1:
        raise ValueError("Ambiguous form control identifiers require manual review")
    return locator


def current_field(page: Page, field: dict[str, Any]) -> dict[str, Any]:
    matches = [
        item
        for item in form_questions(page)
        if (item["type"], item["label"], item["group"])
        == (field["type"], field["label"], field["group"])
    ]
    if len(matches) != 1 or matches[0]["group_choices"] != field["group_choices"]:
        raise ValueError("Form control identity or choices changed during recovery")
    return matches[0]


def set_boolean_control(
    page: Page,
    field: dict[str, Any],
    target: bool,
    *,
    progress: Callable[[str, str], None] | None = None,
    memory: Callable[[str, str | None], str | None] | None = None,
) -> None:
    """Try three verified interaction strategies, reacquiring by semantic identity."""
    methods = ["native", "label", "aria"]
    shape = ""
    for attempt in range(3):
        current = current_field(page, field)
        dialog = page.get_by_role("dialog").filter(visible=True)
        locator = field_locator(dialog, current)
        try:
            state = locator.evaluate("""el => {
              const card=el.closest('[role="checkbox"],[role="radio"]');
              return {native:el.tagName==='INPUT', checked:el.checked,
                aria:card?.getAttribute('aria-checked') ?? null,
                visible:el.checkVisibility(), labels:[...(el.labels || [])].filter(l=>l.checkVisibility()).length,
                role:!!card, enabled:!el.matches(':disabled') && !el.closest('[aria-disabled="true"]'),
                valid:el.checkValidity ? el.checkValidity() : true};
            }""")
            if not state["enabled"]:
                raise ValueError("Control became disabled during recovery")
            if not state["native"] and state["aria"] is None:
                raise ValueError("An accessible control needs an explicit checked state")
            native_ok = not state["native"] or state["checked"] == target
            aria_ok = state["aria"] is None or state["aria"] == str(target).lower()
            if native_ok and aria_ok and state["valid"]:
                if not field["required"] or target or field["type"] == "radio":
                    return
            if native_ok and aria_ok:
                raise ValueError(
                    f"The approved {field['type']} answer was not selected: invalid constraint"
                )
            if not shape:
                shape = (
                    field["type"]
                    + "-"
                    + "".join(str(int(bool(state[key]))) for key in ("visible", "labels", "role"))
                )
                preferred = memory(shape, None) if memory else None
                if preferred in methods:
                    methods.remove(preferred)
                    methods.insert(0, preferred)
            method = methods[attempt]
            if progress:
                progress(
                    "recovering_form",
                    f"Trying {method} interaction ({attempt + 1}/3) for {field['type']}: {field['group'] or field['label']}.",
                )
            if method == "native":
                if not state["native"] or not state["visible"]:
                    continue
                locator.set_checked(target, timeout=2000)
            else:
                clickable = (
                    dialog.locator("label[for=" + json.dumps(str(current["id"])) + "]").or_(
                        locator.locator("xpath=ancestor::label[1]")
                    )
                    if method == "label"
                    else locator.locator(
                        "xpath=ancestor-or-self::*[@role='checkbox' or @role='radio'][1]"
                    )
                ).filter(visible=True)
                if clickable.count() != 1:
                    continue
                clickable.click(timeout=2000)
            # Re-read after a click: React may replace the input, its ID or its wrapper.
            fresh = current_field(page, field)
            verified = field_locator(dialog, fresh).evaluate(
                """(el, target) => {
                  const card=el.closest('[role="checkbox"],[role="radio"]');
                  const aria=card?.getAttribute('aria-checked');
                  return !el.matches(':disabled') && !el.closest('[aria-disabled="true"]') &&
                    (el.tagName!=='INPUT' || el.checked===target && el.checkValidity()) &&
                    (aria==null || aria===String(target));
                }""",
                target,
            )
            if verified and (not field["required"] or target or field["type"] == "radio"):
                if memory:
                    memory(shape, method)
                if progress:
                    progress(
                        "form_recovered", f"Verified {method} interaction for {field['type']}."
                    )
                return
        except BrowserError:
            # Retry only a reversible control action, never a submission click.
            continue
    raise ValueError(
        f"The approved {field['type']} answer was not selected: {field['group'] or field['label']}; three recovery strategies exhausted"
    )


def fill_location_typeahead(page: Page, field: dict[str, Any], profile: Profile) -> None:
    """Select a uniquely offered city in the candidate's confirmed current country."""
    city = profile.location.split(",")[0].strip()
    nation = country(profile.location)
    if not profile.confirmed or not city or not nation or normalise_location(city) == nation:
        raise ValueError("Approve an exact answer for: Location (city)")
    dialog = application_dialog(page)
    field_locator(dialog, current_field(page, field)).fill(city)
    # React may replace the input and its generated identifier after typing.
    locator = field_locator(dialog, current_field(page, field))
    root = locator.locator('xpath=ancestor::*[starts-with(@componentkey,"easyApplyFieldFocus")][1]')
    listbox = root.locator('[role="listbox"][data-testid="typeahead-results-container"]')
    listbox.wait_for(state="visible", timeout=10000)
    if listbox.get_attribute("aria-labelledby") != locator.get_attribute("id"):
        raise ValueError("Unmapped city suggestions require manual review")
    options = (
        listbox.get_by_role("option")
        .filter(visible=True)
        .locator("xpath=self::*[not(@disabled) and not(@aria-disabled='true')]")
    )
    choices = options.all_text_contents()
    matches = [
        index
        for index, choice in enumerate(choices)
        if normalise_location(choice.split(",")[0]) == normalise_location(city)
        and country(choice) == nation
    ]
    if len(matches) != 1:
        raise ValueError("City suggestions do not uniquely match the approved location")
    selected = choices[matches[0]].strip()
    options.nth(matches[0]).click(timeout=2000)
    locator = field_locator(dialog, current_field(page, field))
    if (
        locator.input_value() != selected
        or not locator.evaluate("el => el.checkValidity()")
        or listbox.is_visible()
    ):
        raise ValueError("The approved city suggestion was not selected")


def fill_questions(
    page: Page,
    profile: Profile,
    *,
    resume_field_ids: set[str] | None = None,
    resolver: Callable[[Question], str | None] | None = None,
    progress: Callable[[str, str], None] | None = None,
    memory: Callable[[str, str | None], str | None] | None = None,
) -> None:
    fields = form_questions(page)
    phone_answers = contact_phone_answers(fields, profile)
    dialog = page.get_by_role("dialog").filter(visible=True)
    resolved: dict[tuple[str, tuple[str, ...], str], str | None] = {}

    def answer(label: str, choices: list[str], required: bool) -> str | None:
        approved = approved_answer(label, profile)
        if resolver is None or (approved and (not choices or approved in choices)):
            return approved
        context = question_context(field, label, choices)
        key = (label, tuple(choices), context.html)
        if key not in resolved:
            question_id = "q_" + hashlib.sha256(label.casefold().encode()).hexdigest()[:16]
            resolved[key] = resolver(
                Question(
                    id=question_id,
                    label=label,
                    choices=choices,
                    required=required,
                    form_context=context,
                )
            )
        return resolved[key]

    for field in fields:
        label, field_id = str(field["label"]).strip(), str(field["id"])
        if resume_field_ids and field_id in resume_field_ids:
            continue
        if (
            field["type"] == "checkbox"
            and not field["required"]
            and not field.get("checked")
            and not label
        ):
            continue
        if not label:
            raise ValueError("Unlabelled form control requires manual review")
        field = current_field(page, field)
        locator = field_locator(dialog, field)
        if progress:
            progress(
                "answering_questions",
                f"Checking {field['type']} field: {field.get('group') or label}.",
            )
        if field["type"] == "select-multiple":
            raise ValueError(f"Multiple selections require an explicit approved mapping: {label}")
        if field["type"] == "location-typeahead":
            fill_location_typeahead(page, field, profile)
            continue
        if field["type"] == "radio":
            group = field["group"]
            if not group or not field["group_choices"]:
                raise ValueError("Unlabelled radio group requires manual review")
            value = answer(group, field["group_choices"], field["required"])
            if not value or not value.strip():
                raise ValueError(f"Approve an exact answer for: {group}")
            if value not in field["group_choices"]:
                raise ValueError(f"Approved answer does not match available choices: {group}")
            if label == value:
                set_boolean_control(page, field, True, progress=progress, memory=memory)
            continue
        if field["type"] == "checkbox":
            if re.fullmatch(r"Follow .+ to stay up to date.*", label):
                set_boolean_control(page, field, False, progress=progress, memory=memory)
                continue
            value = answer(label, ["Yes", "No"], field["required"])
            if not value:
                if not field["required"] and not field.get("checked"):
                    continue
                if resolver is not None:
                    raise ValueError(f"Approve an exact answer for: {label}")
                raise ValueError(f"Explicit selection or consent requires manual review: {label}")
            if value not in {"Yes", "No"}:
                raise ValueError(f"Approved answer does not match available choices: {label}")
            target = value == "Yes"
            set_boolean_control(page, field, target, progress=progress, memory=memory)
            continue
        if field["type"] == "combobox":
            locator.click()
            controlled = locator.get_attribute("aria-controls") or ""
            if not controlled or len(controlled.split()) != 1:
                raise ValueError(f"Unmapped dropdown options require manual review: {label}")
            listbox = page.locator('[id="' + controlled.replace('"', '\\"') + '"][role="listbox"]')
            if listbox.count() != 1:
                raise ValueError(f"Unmapped dropdown options require manual review: {label}")
            listbox.wait_for(state="visible", timeout=10000)
            options = (
                listbox.get_by_role("option")
                .filter(visible=True)
                .locator("xpath=self::*[not(@disabled) and not(@aria-disabled='true')]")
            )
            choices = options.evaluate_all(
                "els => els.map(el => (el.getAttribute('aria-label') || el.textContent).trim())"
            )
            value = answer(label, choices, field["required"])
            if not value:
                raise ValueError(f"Approve an exact answer for: {label}")
            selection = (
                listbox.get_by_role("option", name=value, exact=True)
                .filter(visible=True)
                .locator("xpath=self::*[not(@disabled) and not(@aria-disabled='true')]")
            )
            if not choices or value not in choices or selection.count() != 1:
                raise ValueError(f"Approved answer does not match available choices: {label}")
            selection.click()
            if (
                locator.evaluate(
                    "el => (el.getAttribute('aria-valuetext') || el.value || el.textContent).trim()"
                )
                != value
            ):
                raise ValueError(f"The approved dropdown answer was not selected: {label}")
            continue
        value = phone_answers.get(label) or answer(label, field["choices"], field["required"])
        if not value or not value.strip():
            # Existing values also need validation; never assume a prefilled legal answer is correct.
            if field["required"] or field["value"]:
                raise ValueError(f"Approve an exact answer for: {label}")
            continue
        if field["type"] == "select-one":
            indices = locator.evaluate(
                """(el, label) => [...el.options].flatMap((option, index) =>
                !option.disabled && !option.closest('optgroup[disabled]') && option.value!=='' &&
                option.label.trim()===label ? [index] : [])""",
                value,
            )
            if len(indices) != 1:
                raise ValueError(f"Approved answer does not match available choices: {label}")
            locator.select_option(index=indices[0])
            if not locator.evaluate(
                """(el, label) => {
                const option=el.selectedOptions[0];
                return option && !option.disabled && !option.closest('optgroup[disabled]') &&
                  option.value!=='' && option.label.trim()===label;
            }""",
                value,
            ):
                raise ValueError(f"The approved dropdown answer was not selected: {label}")
        else:
            if field["type"] not in {
                "text",
                "textarea",
                "email",
                "tel",
                "url",
                "search",
                "number",
                "date",
                "month",
                "week",
                "time",
                "datetime-local",
            }:
                raise ValueError(f"Unsupported input type requires manual review: {label}")
            if (
                re.match(r"how many years\b", label, re.I)
                or (
                    field["type"] in {"text", "number"}
                    and locator.get_attribute("inputmode") in {"numeric", "decimal"}
                )
            ) and not re.fullmatch(r"\d+(?:\.\d+)?", value):
                raise ValueError(f"Approve an exact answer for: {label}")
            if not locator.evaluate(
                """(el, value) => {
                const probe=el.cloneNode(true); probe.value=value;
                return probe.value===value && probe.checkValidity() &&
                  (el.maxLength==null || el.maxLength<0 || value.length<=el.maxLength) &&
                  (el.minLength==null || el.minLength<0 || value.length>=el.minLength);
            }""",
                value,
            ):
                raise ValueError(f"Approved answer does not satisfy field constraints: {label}")
            locator.fill(value)
        if not locator.evaluate("el => el.checkValidity()"):
            raise ValueError(f"Approved answer does not satisfy field constraints: {label}")


class LinkedInBrowser:
    """A bounded Easy Apply adapter. Site changes fail closed rather than guess."""

    def __init__(self, data: Path, profile: Profile | None = None):
        self.data, self.profile = data, profile
        self.progress: Callable[[str, str], None] | None = None
        self.question_resolver: Callable[[Question], str | None] | None = None
        self.before_submit: Callable[[], None] | None = None
        self.observe_fields: Callable[[list[dict[str, Any]]], None] | None = None
        self.confirmation_folder: Path | None = None
        self.confirmation_evidence: dict[str, Any] = {}

    def report(self, stage: str, detail: str) -> None:
        if self.progress:
            self.progress(stage, detail)

    @contextmanager
    def discovery_step(self, stage: str, detail: str) -> Iterator[None]:
        """Persist the precise read step and controlled failure advice, never raw errors."""
        self.report(stage, detail)
        try:
            yield
        except BrowserError:
            self.report(
                stage,
                detail + " LinkedIn did not complete this read step. Check the dedicated browser "
                "session and page layout before retrying. Discovery has not sent any applications.",
            )
            raise

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
        with (
            sync_playwright() as playwright,
            self.context(playwright) as context,
            linkedin_page(context) as page,
        ):
            with self.discovery_step("opening_job_search", "Opening the LinkedIn job search."):
                page.goto(
                    "https://www.linkedin.com/jobs/search/?"
                    + urlencode({"keywords": keywords, "location": location, "f_AL": "true"}),
                    wait_until="domcontentloaded",
                    timeout=60000,
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
            with self.discovery_step("reading_job_results", "Reading the LinkedIn search results."):
                links_locator.or_(empty).filter(visible=True).first.wait_for(timeout=30000)
                ensure_linkedin(page)
                if not links_locator.count() and empty.filter(visible=True).count():
                    return []
                results = main.locator(".jobs-search-results-list, .scaffold-layout__list")
                if results.count():
                    links_locator = results.locator('a[href*="/jobs/view/"]')
                    links_locator.first.wait_for(timeout=30000)
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
            for index, job_id in enumerate(ids[:limit], start=1):
                url = f"https://www.linkedin.com/jobs/view/{job_id}/"
                identity = f"Opportunity {index}/{min(len(ids), limit)}: {url}"
                with self.discovery_step("opening_discovered_job", identity + " Opening the page."):
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                with self.discovery_step(
                    "reading_discovered_job", identity + " Reading job details."
                ):
                    jobs.append(job_details(page, job_id, timeout=30000))
        return jobs

    def read_opportunity(self, url: str) -> Job:
        """Import one verified job without opening an application form."""
        job_id = linkedin_job_id(url)
        with (
            sync_playwright() as playwright,
            self.context(playwright, headless=False) as context,
            linkedin_page(context) as page,
        ):
            with self.discovery_step("opening_opportunity", "Opening the LinkedIn opportunity."):
                page.goto(
                    f"https://www.linkedin.com/jobs/view/{job_id}/",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
            with self.discovery_step("extracting_opportunity", "Reading the job details."):
                return job_details(page, job_id, timeout=30000)

    def contacts(
        self, location: str, limit: int = 3, *, exclude_urls: set[str] | None = None
    ) -> list[dict[str, str]]:
        from .networking import european_location, target_url

        if not 1 <= limit <= 10:
            raise ValueError("Recruiter discovery limit must be between 1 and 10")
        contacts: list[dict[str, str]] = []
        with (
            sync_playwright() as playwright,
            self.context(playwright) as context,
            linkedin_page(context) as page,
        ):
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
        from .store import Store

        recovery = Store(self.data / "applicator.sqlite3")
        with (
            sync_playwright() as playwright,
            self.context(playwright) as context,
            linkedin_page(context) as page,
        ):
            self.report("opening_opportunity", "Opening the reviewed LinkedIn opportunity.")
            page.goto(job.url, wait_until="domcontentloaded")
            self.report(
                "verifying_opportunity",
                "Checking the live title, company, location and description against the reviewed vacancy.",
            )
            current_job = job_details(page, job.source_id)
            if current_job.title != job.title:
                raise ValueError("Job title changed; re-import and review")
            if current_job.company != job.company:
                raise ValueError("Company changed; re-import and review")
            if current_job.location != job.location:
                raise ValueError("Job location changed; re-import and review")
            if " ".join(current_job.description.split()) != " ".join(job.description.split()):
                raise ValueError("Job description changed; re-import and review")
            self.report("opening_application", "Opening the Easy Apply form.")
            open_easy_apply(page, self.report)
            seen_steps: set[str] = set()
            verified_resumes: dict[str, JSHandle] = {}
            for _step in range(10):
                ensure_linkedin(page)
                dialog = application_dialog(page)
                if application_step(dialog) in seen_steps:
                    raise ValueError(
                        "The application did not advance; review the form's validation messages"
                    )
                cv = folder / (filename_stem(self.profile, job) + "_CV.pdf")
                self.report(
                    "uploading_documents",
                    f"Checking and uploading the verified CV: form step {_step + 1}.",
                )
                resume_fields = upload_resume(page, dialog, cv, verified=verified_resumes)
                if resume_fields is not None and self.observe_fields:
                    self.observe_fields(
                        [{"label": "CV", "type": "file", "value": cv.name, "step": _step + 1}]
                    )
                self.report(
                    "answering_questions",
                    f"Completing form step {_step + 1} using approved answers only.",
                )
                fill_questions(
                    page,
                    self.profile,
                    resume_field_ids=resume_fields,
                    resolver=self.question_resolver,
                    progress=self.report,
                    memory=recovery.recovery_strategy,
                )
                self.report(
                    "uploading_documents",
                    f"Checking remaining document fields: form step {_step + 1}.",
                )
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
                    if self.observe_fields:
                        self.observe_fields(
                            [
                                {
                                    "label": "Cover letter" if is_cover else "CV",
                                    "type": "file",
                                    "value": candidate.name,
                                    "step": _step + 1,
                                }
                            ]
                        )
                submit = dialog.get_by_role("button", name="Submit application", exact=True)
                if self.observe_fields:
                    self.observe_fields(
                        [{**field, "step": _step + 1} for field in form_questions(page)]
                    )
                if submit.count():
                    # Do not follow companies as an implicit side effect of submission.
                    for field in form_questions(page):
                        if field["type"] == "checkbox" and re.fullmatch(
                            r"Follow .+ to stay up to date.*", field["label"]
                        ):
                            set_boolean_control(
                                page,
                                field,
                                False,
                                progress=self.report,
                                memory=recovery.recovery_strategy,
                            )
                    self.report("submitting", "Sending the application to LinkedIn.")
                    if self.before_submit:
                        self.before_submit()
                    progress["submitted"] = True
                    submit.click()
                    self.report(
                        "awaiting_confirmation",
                        "Waiting for LinkedIn's submission confirmation; do not retry.",
                    )
                    page.get_by_text(
                        re.compile(r"Your application was sent|Application submitted"), exact=False
                    ).first.wait_for(timeout=15000)
                    if self.confirmation_folder:
                        self.report(
                            "capturing_confirmation",
                            "Saving a private screenshot of the provider's submission confirmation.",
                        )
                    self.confirmation_evidence = capture_confirmation(
                        page, self.confirmation_folder
                    )
                    return f"linkedin:{job.source_id}:confirmed"
                seen_steps.add(application_step(dialog))
                self.report("advancing_form", f"Validating and advancing form step {_step + 1}.")
                advance_application(
                    page,
                    self.profile,
                    resume_field_ids=resume_fields,
                    resolver=self.question_resolver,
                    progress=self.report,
                    memory=recovery.recovery_strategy,
                )
            raise ValueError("Easy Apply exceeded the ten-step limit")


class FixtureBrowser:
    """A real-browser submission adapter for the explicitly local test fixture."""

    def __init__(self) -> None:
        self.observe_fields: Callable[[list[dict[str, Any]]], None] | None = None
        self.confirmation_folder: Path | None = None
        self.confirmation_evidence: dict[str, Any] = {}

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
                if self.observe_fields:
                    self.observe_fields(
                        [
                            {
                                "label": "CV",
                                "type": "file",
                                "value": next(folder.glob("*_CV.pdf")).name,
                            }
                        ]
                    )
                    self.observe_fields(
                        page.locator("input:not([type=file]),textarea,select").evaluate_all(
                            "nodes => nodes.map(el=>({label:[...el.labels].map(label=>label.textContent.trim()).join(' '),type:el.type,value:el.value,checked:el.checked}))"
                        )
                    )
                page.get_by_role("button", name="Submit application", exact=True).click()
                receipt = page.locator("#receipt").inner_text(timeout=10000)
                if not receipt.startswith("fixture:"):
                    raise ValueError("Missing fixture receipt")
                self.confirmation_evidence = capture_confirmation(page, self.confirmation_folder)
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
