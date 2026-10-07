"""Manual decisions reach the real final sending gate without bypassing mutable checks."""

import copy
import html

import pytest
from test_browser import LINKEDIN_HTML

from applicator.application_management import experience_reviewable
from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options
from applicator.models import Question, Settings, State
from applicator.question_adviser import question_key
from applicator.service import Service
from applicator.store import Store


def prepare_decision(data, profile, job, decision):
    job.source, job.source_id, job.url = (
        "linkedin",
        "123",
        "https://www.linkedin.com/jobs/view/123/",
    )
    if decision == "years":
        profile.answers[
            question_key(
                Question(
                    id="years", label="How many years of work experience do you have with Python?"
                )
            )
        ] = "3"
        job.description += "\nMinimum 5 years of professional Python experience"
    elif decision == "unmapped":
        job.description += "\n5+ years of commercial software development experience"
    elif decision == "production":
        profile.answers["condition:production_ml"] = "No"
        job.description += "\nExperience in deploying ML models into production"
    else:
        job.requirements = ["Python", "AWS"]
    store = Store(data / "gate.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True))
    adapter = LinkedInBrowser(data, profile)
    service = Service(store, data, {"linkedin": adapter})
    app_id, _ = store.add_job(job)
    service.prepare(app_id)
    assert store.application(app_id)["state"] == State.REVIEW
    report = service.preflight(app_id)
    store.management.accept(
        app_id,
        1,
        job,
        [value for value in report.evaluation.blockers if experience_reviewable(value)],
        decision == "fit",
    )
    service.refresh_readiness(app_id)
    assert service.preflight(app_id).can_submit
    return store, service, adapter, app_id


@pytest.mark.parametrize("decision", ["years", "unmapped", "production", "fit"])
def test_review_decision_is_respected_at_irreversible_click_boundary(
    data, profile, job, monkeypatch, decision
):
    store, service, adapter, app_id = prepare_decision(data, profile, job, decision)
    original = copy.deepcopy(store.application(app_id))
    clicks = []

    def form(vacancy, answers, folder, progress):
        assert not clicks
        adapter.before_submit()
        with store.connect() as db:
            assert db.execute(
                "SELECT sent_day FROM attempts WHERE application_id=?", (app_id,)
            ).fetchone()[0]
            assert db.execute(
                "SELECT sent_at FROM submission_records WHERE application_id=?", (app_id,)
            ).fetchone()[0]
        progress["submitted"] = True
        clicks.append("submit")
        return "fixture:review-confirmed"

    monkeypatch.setattr(adapter, "_submit", form)
    assert service.submit(app_id) == "fixture:review-confirmed"
    assert clicks == ["submit"] and store.application(app_id)["state"] == State.SUBMITTED
    assert store.profile()[0] == profile
    assert store.application(app_id)["manifest"] == original["manifest"]
    assert store.application(app_id)["evaluation"]["score"] == original["evaluation"]["score"]
    assert store.daily_usage().used == 1 and store.daily_usage().held == 0


@pytest.mark.parametrize(
    "change",
    [
        "decision_removed",
        "pause",
        "scope",
        "revision",
        "job",
        "capacity",
        "candidate_confirmation",
        "location",
    ],
)
def test_approved_experience_does_not_override_last_moment_changes(
    data, profile, job, monkeypatch, change
):
    store, service, adapter, app_id = prepare_decision(data, profile, job, "production")
    clicks = []
    if change == "capacity":
        other_id, _ = store.add_job(
            job.model_copy(
                update={"source_id": "456", "url": "https://www.linkedin.com/jobs/view/456/"}
            )
        )

    def form(vacancy, answers, folder, progress):
        if change == "pause":
            store.set_settings(store.settings().model_copy(update={"automation_enabled": False}))
        elif change == "scope":
            store.set_settings(store.settings().model_copy(update={"linkedin_authorised": False}))
        elif change == "revision":
            store.save_profile(profile.model_copy(update={"summary": "Updated confirmed facts"}))
        elif change == "capacity":
            store.set_settings(store.settings().model_copy(update={"daily_limit": 1}))
            with store.connect(True) as db:
                db.execute(
                    "INSERT INTO attempts(application_id,day,started,status) VALUES(?,?,?,'held')",
                    (other_id, "2026-10-07", "fixture"),
                )
        else:
            with store.connect(True) as db:
                if change == "decision_removed":
                    db.execute(
                        "DELETE FROM application_review_decisions WHERE application_id=?", (app_id,)
                    )
                elif change == "job":
                    db.execute(
                        "UPDATE applications SET job=? WHERE id=?",
                        (
                            job.model_copy(
                                update={"title": "Changed opportunity"}
                            ).model_dump_json(),
                            app_id,
                        ),
                    )
                else:
                    changed = profile.model_copy(
                        update={"confirmed": False}
                        if change == "candidate_confirmation"
                        else {"location": "Cork, Ireland"}
                    )
                    db.execute(
                        "UPDATE config SET value=? WHERE key='profile'",
                        (changed.model_dump_json(),),
                    )
        adapter.before_submit()
        progress["submitted"] = True
        clicks.append("submit")
        return "fixture:must-not-send"

    monkeypatch.setattr(adapter, "_submit", form)
    with pytest.raises(ReviewRequired, match="changed before sending"):
        service.submit(app_id)
    assert not clicks and store.application(app_id)["state"] == State.REVIEW
    assert store.daily_usage().used == 0
    with store.connect() as db:
        assert all(row[0] is None for row in db.execute("SELECT sent_day FROM attempts"))
        assert all(row[0] is None for row in db.execute("SELECT sent_at FROM submission_records"))


@pytest.mark.browser
@pytest.mark.parametrize("decision", ["years", "production"])
@pytest.mark.parametrize("revoked", [False, True])
def test_intercepted_browser_click_respects_current_review_decision(
    data, profile, job, monkeypatch, decision, revoked
):
    job.description = "Python FastAPI PostgreSQL"
    store, service, adapter, app_id = prepare_decision(data, profile, job, decision)
    clicks = []
    provider = LINKEDIN_HTML.replace(
        "Python FastAPI PostgreSQL", html.escape(job.description).replace("\n", "<br>")
    )

    def context(self, playwright, **_):
        session = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )
        session.route("**/*", lambda route: route.fulfill(content_type="text/html", body=provider))
        session.expose_binding("recordClick", lambda *_: clicks.append("submit"))
        session.add_init_script(
            "document.addEventListener('click', event => {if(event.target.id === 'submit') window.recordClick();}, true)"
        )
        return session

    actual_gate = store.mark_sending

    def gate(*args):
        assert not clicks
        if revoked:
            with store.connect(True) as db:
                db.execute(
                    "DELETE FROM application_review_decisions WHERE application_id=?", (app_id,)
                )
        actual_gate(*args)

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    monkeypatch.setattr(store, "mark_sending", gate)
    if revoked:
        with pytest.raises(ReviewRequired, match="Submission policy changed before sending"):
            service.submit(app_id)
        assert not clicks and store.application(app_id)["state"] == State.REVIEW
        assert store.daily_usage().used == 0 and store.daily_usage().held == 0
    else:
        assert service.submit(app_id) == "linkedin:123:confirmed"
        assert clicks == ["submit"] and store.application(app_id)["state"] == State.SUBMITTED
        assert store.daily_usage().used == 1
    assert store.profile()[0] == profile
