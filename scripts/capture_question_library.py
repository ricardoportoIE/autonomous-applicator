"""Capture the packaged question library with fictional records and no model/provider calls."""

import secrets
from pathlib import Path
from tempfile import TemporaryDirectory

from capture_screenshots import local_server
from playwright.sync_api import expect, sync_playwright

from applicator.api import create_app
from applicator.browser import browser_options
from applicator.models import Evidence, Job, Profile, Question
from applicator.question_library import InstructionUpdate

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with TemporaryDirectory(prefix="question-library-demo-") as temporary:
        token = secrets.token_urlsafe(40)
        app = create_app(Path(temporary) / "data", token)
        store = app.state.store
        store.save_profile(
            Profile(
                name="Alex Example",
                email="alex@example.test",
                location="Dublin, Ireland",
                confirmed=True,
                evidence=[
                    Evidence(
                        id="api",
                        category="project",
                        title="Independent API project",
                        text="Built an independent Python API with automated tests.",
                        tags=["Python"],
                        source="Candidate-reviewed fictional project",
                        verified=True,
                    )
                ],
            )
        )
        questions = [
            Question(
                id="python",
                label="How many years of professional experience do you have with Python?",
            ),
            Question(id="java", label="Describe your experience with Java"),
            Question(id="salary", label="What are your salary expectations?"),
        ]
        app_id = store.add_job(
            Job(
                source_id="fictional",
                title="Backend Engineer",
                company="Example Employer",
                location="Dublin, Ireland",
                url="https://example.test/jobs/1",
                description="Build Python APIs.",
                questions=questions,
            )
        )[0]
        library = store.question_library
        for entry in library.entries():
            if entry["question"]["id"] == "python":
                library.update(
                    entry["id"],
                    InstructionUpdate(
                        prompt="I have 3 years of professional Python experience. Use 3 for a numeric field; for text, write one short, polite sentence. Do not apply this instruction to other technologies.",
                        enabled=True,
                        version=1,
                    ),
                )
            elif entry["question"]["id"] == "java":
                library.update(
                    entry["id"],
                    InstructionUpdate(
                        prompt="I have no professional Java experience. Mention my educational experience and continued learning, politely and briefly.",
                        enabled=False,
                        version=1,
                    ),
                )
        assert app_id and store.daily_usage().attempts == 0
        with local_server(app) as origin, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, **browser_options())
            context = browser.new_context(
                viewport={"width": 1440, "height": 1150}, reduced_motion="reduce", locale="en-GB"
            )
            context.route("https://**/*", lambda route: route.abort())
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin)
            page.get_by_label("Access token", exact=True).fill(token)
            page.get_by_role("button", name="Unlock workspace").click()
            page.get_by_role("button", name="Agent settings", exact=True).click()
            page.get_by_role("tab", name="Routine answers", exact=True).click()
            expect(
                page.get_by_text("Questions: 3 · Enabled instructions: 1", exact=True)
            ).to_be_visible()
            output = ROOT / "docs" / "assets"
            page.screenshot(path=output / "routine-answers.png", full_page=True)
            page.get_by_role("button", name="Edit instruction").last.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.screenshot(path=output / "question-instruction.png")
            page.get_by_role("button", name="Close dialogue").click()
            page.set_viewport_size({"width": 390, "height": 950})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors, errors
            assert store.daily_usage().attempts == 0
            context.close()
            browser.close()
    print(
        "Captured two question-library screenshots with fictional records; no model or provider calls."
    )


if __name__ == "__main__":
    main()
