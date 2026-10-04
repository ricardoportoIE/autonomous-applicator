"""Capture the actual packaged UI using disposable, fictional demonstration records.

No real workspace, environment file, provider account or model request is used.
The single demonstration submission targets an in-process loopback fixture only.
Run after `npm run build`: uv run python scripts/capture_screenshots.py
"""

import secrets
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from playwright.sync_api import expect, sync_playwright

from applicator.api import create_app
from applicator.browser import FixtureBrowser, browser_options
from applicator.models import Evidence, Job, Profile, Question, Settings

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets"


@contextmanager
def local_server(app: FastAPI) -> Iterator[str]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        runner = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        thread = threading.Thread(target=runner.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        ready = threading.Event()
        try:
            for _ in range(200):
                if runner.started:
                    break
                ready.wait(0.02)
            if not runner.started:
                raise RuntimeError("The isolated screenshot server did not start")
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            runner.should_exit = True
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("The isolated screenshot server did not stop")


def candidate() -> Profile:
    return Profile(
        name="Alex Example",
        email="alex@example.test",
        phone="+353 00 000 0000",
        location="Dublin, Ireland",
        summary="Backend developer building dependable Python APIs, clear interfaces and evidence-led automation. Fictional candidate for product demonstration.",
        links=["https://example.test/portfolio"],
        sponsorship_required=False,
        confirmed=True,
        answers={
            "email": "alex@example.test",
            "question:describe your python experience": "Built a Python API with FastAPI, PostgreSQL, automated tests and Docker.",
        },
        evidence=[
            Evidence(
                id="python",
                category="project",
                title="Order management API",
                text="Built a Python and FastAPI service with PostgreSQL, automated tests and Docker. Added transactional checks and documented recovery procedures.",
                dates="2025–2026",
                tags=["Python", "FastAPI", "PostgreSQL", "Docker", "SQL", "Git"],
                source="Fictional candidate-approved project",
                verified=True,
            ),
            Evidence(
                id="react",
                category="project",
                title="Accessible operations dashboard",
                text="Built a React and TypeScript dashboard with accessible dialogues, keyboard tabs and automated browser tests.",
                dates="2026",
                tags=["React", "TypeScript", "Testing", "Git"],
                source="Fictional candidate-approved project",
                verified=True,
            ),
            Evidence(
                id="degree",
                category="education",
                title="BSc Computing",
                text="Studied software development, database design and distributed systems.",
                dates="2022–2025",
                source="Fictional qualification",
                verified=True,
            ),
        ],
    )


def employer_fixture() -> FastAPI:
    fixture = FastAPI()

    @fixture.get("/apply", response_class=HTMLResponse)
    def apply() -> str:
        return """<!doctype html><html lang="en-GB"><meta charset="utf-8"><title>Local provider fixture</title>
        <style>body{font:20px system-ui;margin:60px;background:#f6f8fb;color:#162d3d}main{max-width:800px;margin:auto;padding:44px;background:white;border:1px solid #dae4eb;border-radius:20px}label{display:block;margin:22px 0}input{display:block;margin-top:8px}button{padding:14px 22px;background:#176b62;color:white;border:0;border-radius:10px}#receipt{font-weight:600;color:#176b62}</style>
        <main><p>FICTIONAL LOCAL DEMONSTRATION</p><h1>Northstar Example · Backend Engineer</h1><p>No real employer or provider account is involved.</p>
        <form><label>Email<input type="email" required></label><label>CV<input type="file" required></label><button>Submit application</button></form><p id="receipt"></p></main>
        <script>document.querySelector('form').onsubmit=e=>{e.preventDefault();document.querySelector('form').hidden=true;document.querySelector('#receipt').textContent='fixture:demonstration-confirmed';}</script></html>"""

    return fixture


def seed(app: FastAPI, provider: str) -> int:
    store, service = app.state.store, app.state.service
    store.save_profile(candidate())
    store.set_settings(
        Settings(automation_enabled=True, linkedin_authorised=False, daily_connection_limit=5)
    )
    questions = [
        Question(
            id="experience",
            label="Describe your Python experience",
            answer_key="question:describe your python experience",
        )
    ]
    jobs = [
        (
            "Backend Engineer",
            "Northstar Example",
            "Dublin, Ireland",
            ["Python", "FastAPI", "PostgreSQL"],
            "fixture",
        ),
        (
            "Python Platform Engineer",
            "Harbour Example",
            "Dublin, Ireland",
            ["Python", "Docker", "SQL"],
            "manual",
        ),
        (
            "Full Stack Developer",
            "Meridian Example",
            "Dublin, Ireland",
            ["Python", "React", "TypeScript"],
            "manual",
        ),
        (
            "Data Engineer",
            "Oak Example",
            "London, United Kingdom",
            ["Python", "SQL", "Spark"],
            "manual",
        ),
        ("API Engineer", "Cedar Example", "Cork, Ireland", ["Python", "FastAPI", "Git"], "manual"),
        (
            "Cloud Engineer",
            "Atlas Example",
            "Dublin, Ireland",
            ["Terraform", "AWS", "Kubernetes"],
            "manual",
        ),
    ]
    ids = []
    for index, (title, company, location, requirements, source) in enumerate(jobs, 1):
        job = Job(
            source=source,
            source_id=f"demo-{index}",
            title=title,
            company=company,
            location=location,
            url=provider + "/apply"
            if source == "fixture"
            else f"https://example.test/jobs/{index}",
            description=f"Join {company} to build well-tested services with {', '.join(requirements)}. Own technical decisions, collaborate across disciplines and document dependable operations. This vacancy is fictional demonstration data.",
            requirements=requirements,
            sponsorship="available",
            questions=[Question(id="Email", label="Email", answer_key="email")]
            if source == "fixture"
            else questions,
            cover_letter_required=index == 2,
        )
        app_id, _ = store.add_job(job)
        service.prepare(app_id, use_ai=False)
        ids.append(app_id)
    service.adapters["fixture"] = FixtureBrowser()
    assert service.submit(ids[0]) == "fixture:demonstration-confirmed"
    store.set_settings(Settings(daily_connection_limit=5))
    for slug, name, role, location in [
        (
            "demo-jamie",
            "Jamie Example",
            "Technical recruiter · Backend & platform",
            "Dublin, Ireland",
        ),
        ("demo-sam", "Sam Example", "Talent acquisition · Engineering", "London, United Kingdom"),
        ("demo-robin", "Robin Example", "Technology recruitment", "Amsterdam, Netherlands"),
    ]:
        app.state.network.add(f"https://www.linkedin.com/in/{slug}/", name, role, location)
    return ids[0]


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    token = secrets.token_urlsafe(32)
    with (
        TemporaryDirectory(prefix="applicator-screenshots-") as temporary,
        local_server(employer_fixture()) as provider,
    ):
        app = create_app(Path(temporary) / "data", token)
        app_id = seed(app, provider)
        with local_server(app) as origin, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, **browser_options())
            context = browser.new_context(
                viewport={"width": 1440, "height": 1500},
                reduced_motion="reduce",
                locale="en-GB",
                timezone_id="Europe/London",
            )
            page = context.new_page()
            errors, external = [], []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def local_only(route):
                if urlsplit(route.request.url).hostname != "127.0.0.1":
                    external.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", local_only)
            page.goto(origin)
            page.get_by_label("Access token", exact=True).fill(token)
            page.get_by_role("button", name="Unlock workspace").click()
            expect(page.locator("#notice")).to_have_text("Local workspace unlocked.")
            page.screenshot(path=OUTPUT / "dashboard.png")
            page.get_by_role("button", name="Applications", exact=True).click()
            page.get_by_role("article", name="Application queue", exact=True).screenshot(
                path=OUTPUT / "application-queue.png"
            )
            page.get_by_role(
                "button", name="Open Python Platform Engineer at Harbour Example"
            ).click()
            page.get_by_role("tab", name="Questions (1)").click()
            page.locator("#application-detail").scroll_into_view_if_needed()
            page.locator("#application-detail").screenshot(path=OUTPUT / "question-review.png")
            page.get_by_role("button", name="Networking", exact=True).click()
            page.get_by_role("article", name="Connection queue", exact=True).screenshot(
                path=OUTPUT / "networking.png"
            )
            page.goto(origin + f"/#/applications/{app_id}")
            expect(page.get_by_role("button", name="Refresh record", exact=True)).to_be_visible()
            page.set_viewport_size({"width": 1440, "height": 1100})
            page.locator(".record-navigation").evaluate(
                "element => element.scrollIntoView({block: 'start'})"
            )
            page.screenshot(path=OUTPUT / "application-record.png")
            page.get_by_role(
                "article", name="Provider confirmation", exact=True
            ).scroll_into_view_if_needed()
            expect(
                page.get_by_role(
                    "img",
                    name=f"Provider submission confirmation for application {app_id}, attempt 1",
                )
            ).to_be_visible()
            page.get_by_role("article", name="Provider confirmation", exact=True).screenshot(
                path=OUTPUT / "confirmation-evidence.png"
            )
            page.set_viewport_size({"width": 390, "height": 950})
            page.get_by_role("button", name="Applications", exact=True).click()
            page.get_by_role(
                "article", name="Application queue", exact=True
            ).scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.get_by_role("article", name="Application queue", exact=True).screenshot(
                path=OUTPUT / "mobile-queue.png"
            )
            assert not errors, errors
            assert not external, "The demonstration must make no external requests"
            assert store_usage(app) == 1
            context.close()
            browser.close()
    print(
        "Captured seven current UI screenshots using fictional data and one local provider fixture; no external or AI requests."
    )


def store_usage(app: FastAPI) -> int:
    return app.state.store.daily_usage().used


if __name__ == "__main__":
    main()
