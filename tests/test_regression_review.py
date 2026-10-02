"""Regression tests for the complete source review, using only local fixtures."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from applicator.api import create_app, local_token
from applicator.browser import LinkedInBrowser, ReviewRequired, ensure_linkedin, linkedin_job_id
from applicator.models import Evidence, Settings, State
from applicator.networking import european_location, target_url
from applicator.service import Service
from applicator.store import Store

TOKEN = "regression-local-fixture-token-01234567890123456789"


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "1"}, {"Content-Length": "invalid"}])
def test_body_limit_counts_chunks_without_trusting_headers(data, headers):
    app = create_app(data, TOKEN)
    client = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    response = client.post(
        "/api/jobs", content=iter([b"x" * 250_001, b"y" * 250_000]), headers=headers
    )
    assert response.status_code == 413
    assert not app.state.store.applications()


def test_cached_short_token_is_rejected_without_replacement(data, monkeypatch):
    monkeypatch.delenv("APPLICATOR_TOKEN", raising=False)
    data.mkdir()
    path = data / "access-token"
    path.write_text("short", encoding="utf-8")
    with pytest.raises(ValueError, match="saved local access token"):
        local_token(data)
    assert path.read_text() == "short"


def test_profile_optimistic_concurrency_preserves_newer_facts(data, profile):
    app = create_app(data, TOKEN)
    client = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    assert (
        client.put("/api/profile", json=profile.model_dump(), headers={"If-Match": "0"}).status_code
        == 200
    )
    newer = profile.model_copy(update={"summary": "Candidate-approved new summary."})
    assert (
        client.put("/api/profile", json=newer.model_dump(), headers={"If-Match": "1"}).status_code
        == 200
    )
    assert (
        client.put("/api/profile", json=profile.model_dump(), headers={"If-Match": "1"}).status_code
        == 409
    )
    assert app.state.store.profile()[0].summary == newer.summary
    assert app.state.store.profile()[1] == 2
    assert (
        client.put(
            "/api/profile", json=profile.model_dump(), headers={"If-Match": "invalid"}
        ).status_code
        == 422
    )


def test_atomic_evidence_edits_and_api_contract(data, profile):
    app = create_app(data, TOKEN)
    client = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    evidence = profile.evidence[0]
    assert client.put("/api/evidence/python", json=evidence.model_dump()).status_code == 409
    app.state.store.save_profile(profile)
    assert client.put("/api/evidence/mismatch", json=evidence.model_dump()).status_code == 409
    changed = evidence.model_copy(update={"title": "Reviewed project"})
    assert client.put("/api/evidence/python", json=changed.model_dump()).status_code == 200
    assert app.state.store.profile()[0].evidence[0].title == changed.title

    def add(index):
        item = evidence.model_copy(update={"id": f"concurrent_{index}"})
        return app.state.store.edit_evidence(item, item.id)

    with ThreadPoolExecutor(max_workers=6) as pool:
        revisions = list(pool.map(add, range(6)))
    assert len(set(revisions)) == 6
    assert len(app.state.store.profile()[0].evidence) == 7
    assert client.delete("/api/evidence/missing").status_code == 404


def test_revoked_scope_is_rechecked_inside_reservation(data, profile, job):
    store = Store(data / "test.sqlite3")
    store.save_profile(profile)
    job.source = "linkedin"
    job.source_id = "123"
    job.url = "https://www.linkedin.com/jobs/view/123/"
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=True))
    app_id, _ = store.add_job(job)
    adapter = Mock()
    service = Service(store, data, {"linkedin": adapter})
    service.prepare(app_id)
    store.set_settings(Settings(automation_enabled=True, linkedin_authorised=False))
    with pytest.raises(ValueError, match="authorisation"):
        store.reserve(app_id, 1)
    assert store.application(app_id)["state"] == State.READY
    assert not adapter.submit.called
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_long_question_labels_remain_reviewable(data, profile, job):
    store = Store(data / "test.sqlite3")
    store.save_profile(profile)
    app_id, _ = store.add_job(job)
    label = "Please confirm " + "your approved answer " * 23
    store.hold(app_id, "Approve an exact answer for: " + label)
    row = store.application(app_id)
    question = row["job"]["questions"][0]
    assert len(question["answer_key"]) > 100
    assert question["label"] == label.strip()[:500]
    assert row["state"] == State.REVIEW
    store.hold(app_id, "Approve an exact answer for: " + label)
    assert len(store.application(app_id)["job"]["questions"]) == 1
    with pytest.raises(KeyError):
        store.hold(999, "review")


def test_finish_requires_latest_owned_attempt_and_preserves_receipts(data, profile, job):
    store = Store(data / "test.sqlite3")
    store.save_profile(profile)
    store.set_settings(Settings(automation_enabled=True))
    app_id, _ = store.add_job(job)
    service = Service(store, data)
    service.prepare(app_id)
    first = store.reserve(app_id, 1)
    with pytest.raises(ValueError):
        store.finish(app_id, first + 99, "wrong")
    store.hold(app_id, "Known safe stop before submission")
    service.prepare(app_id)
    latest = store.reserve(app_id, 1)
    with pytest.raises(ValueError):
        store.finish(app_id, first, "old")
    store.finish(app_id, latest, "confirmed")
    with pytest.raises(ValueError):
        store.finish(app_id, latest, None)
    assert store.application(app_id)["receipt"] == "confirmed"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com:8443/jobs/view/123/",
        "https://user:secret@www.linkedin.com/jobs/view/123/",
        "https://www.linkedin.com.evil.test/jobs/view/123/",
    ],
)
def test_linkedin_origin_is_exact(url):
    with pytest.raises(ValueError):
        linkedin_job_id(url)
    with pytest.raises(ValueError):
        ensure_linkedin(Mock(url=url))
    with pytest.raises(ValueError):
        target_url(url.replace("/jobs/view/123/", "/in/example/"))


def test_linkedin_job_identity_mismatch_stops_before_browser(data, profile, job):
    job.url = "https://www.linkedin.com/jobs/view/123/"
    job.source_id = "456"
    with pytest.raises(ReviewRequired, match="identifier"):
        LinkedInBrowser(data, profile).submit(job, {}, data)


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Dublin, Ireland", True),
        ("Berlin, Germany", True),
        ("Cardiff, Wales", True),
        ("Sydney, New South Wales, Australia", False),
        ("Franceville, Gabon", False),
        ("New Ireland, Papua New Guinea", False),
        ("United States", False),
    ],
)
def test_networking_location_does_not_use_partial_country_matches(location, expected):
    assert european_location(location) is expected


@pytest.mark.parametrize(
    "settings",
    [
        {"allowed_countries": []},
        {"allowed_countries": [""]},
        {"allowed_countries": [" "]},
        {"allowed_countries": ["x" * 151]},
        {"search_keywords": ""},
        {"search_location": ""},
    ],
)
def test_invalid_discovery_settings_are_rejected(settings):
    with pytest.raises(ValidationError):
        Settings(**settings)


def test_country_settings_are_normalised_and_deduplicated():
    assert Settings(allowed_countries=[" Ireland ", "Ireland"]).allowed_countries == ["Ireland"]


def test_mutated_invalid_profile_cannot_bypass_validation(data, profile):
    store = Store(data / "test.sqlite3")
    store.save_profile(profile)
    profile.evidence.append(Evidence.model_validate(profile.evidence[0].model_dump()))
    with pytest.raises(ValidationError):
        store.save_profile(profile)
    assert store.profile()[1] == 1
