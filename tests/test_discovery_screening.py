"""Low-fit discovery is durable, atomic and separate from explicit imports."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from test_job_discovery import modern_job

from applicator.api import create_app
from applicator.browser import LinkedInBrowser, browser_options
from applicator.models import Settings, State
from applicator.policy import evaluate
from applicator.service import Service
from applicator.store import Store


def setup(data, profile):
    store = Store(data / "applicator.sqlite3")
    revision = store.save_profile(profile)
    return store, Service(store, data), revision


@pytest.mark.parametrize("score", [0, 49, 50, 79, 80, 100])
def test_discovery_uses_the_exact_50_point_boundary_without_preparing_or_sending(
    data, profile, job, monkeypatch, score
):
    store, service, _ = setup(data, profile)
    service.selector = Mock(side_effect=AssertionError("Screening must not call the model"))
    settings = store.settings().model_copy(update={"review_threshold": 60})
    store.set_settings(settings)
    monkeypatch.setattr(
        "applicator.service.evaluate",
        Mock(
            return_value=evaluate(job, profile, settings).model_copy(
                update={"score": score, "state": State.REVIEW}
            )
        ),
    )
    result = service.screen_discovery([job])
    assert result == {
        "imported": int(score >= 50),
        "discarded": int(score < 50),
        "excluded": 0,
        "duplicates": 0,
    }
    assert len(store.applications()) == int(score >= 50)
    assert len(store.discovery_discards()) == int(score < 50)
    assert store.daily_usage().used == store.daily_usage().held == 0
    assert not service.selector.called and not (data / "documents").exists()


def test_real_description_assessment_logs_low_fit_without_storing_a_job_snapshot(
    data, profile, job
):
    store, service, revision = setup(data, profile)
    weak = job.model_copy(
        update={
            "title": "Backend Engineer",
            "description": "Develop Rust and Kubernetes infrastructure. PRIVATE_DESCRIPTION_MARKER",
            "requirements": ["Rust", "Kubernetes"],
        },
        deep=True,
    )
    result = service.screen_discovery([weak])
    score = evaluate(weak, profile, store.settings()).score
    assert score < 50 and result["discarded"] == 1 and store.applications() == []
    logged = store.discovery_discards()[0]
    assert logged["score"] == score and logged["profile_revision"] == revision
    assert logged["url"] == weak.url and logged["evaluation"]["gaps"]
    assert "description" not in logged and "PRIVATE_DESCRIPTION_MARKER" not in str(logged)


def test_unconfirmed_candidate_cannot_create_permanent_discovery_exclusions(data, profile, job):
    profile.confirmed = False
    store, service, _ = setup(data, profile)
    with pytest.raises(ValueError, match="Confirm candidate facts"):
        service.screen_discovery([job])
    assert store.applications() == [] and store.discovery_discards() == []


def test_known_discards_survive_restart_and_canonical_url_aliases(data, profile, job):
    store, service, _ = setup(data, profile)
    weak = job.model_copy(
        update={"requirements": ["Rust"], "description": "Rust infrastructure"}, deep=True
    )
    assert service.screen_discovery([weak])["discarded"] == 1
    restarted = Store(store.path)
    alias = weak.model_copy(
        update={"source_id": "alias", "url": weak.url.rstrip("/") + "/?tracking=changed#details"}
    )
    result = Service(restarted, data).screen_discovery([alias, weak])
    assert result == {"imported": 0, "discarded": 0, "excluded": 2, "duplicates": 0}
    assert restarted.discarded_job_ids(weak.source) == {weak.source_id}
    assert restarted.discarded_job_ids("other") == set()
    assert len(restarted.discovery_discards()) == 1 and restarted.applications() == []


def test_explicit_import_and_existing_application_are_preserved_even_when_low_fit(
    data, profile, job
):
    store, service, _ = setup(data, profile)
    weak = job.model_copy(update={"requirements": ["Rust"], "description": "Rust"}, deep=True)
    app_id, _ = store.add_job(weak)
    snapshot = store.application(app_id)
    alias = weak.model_copy(
        update={"source_id": "alias", "url": weak.url.rstrip("/") + "/?query=x"}
    )
    assert service.screen_discovery([weak, alias])["duplicates"] == 2
    assert store.application(app_id) == snapshot and store.discovery_discards() == []
    another = weak.model_copy(
        update={"source_id": "another", "url": "https://example.test/jobs/another"}
    )
    service.screen_discovery([another])
    explicit_id, created = store.add_job(another)
    assert created and store.application(explicit_id)["job"]["url"] == another.url


@pytest.mark.parametrize("change", ["profile", "settings"])
def test_changed_candidate_or_settings_reject_the_entire_assessed_batch(
    data, profile, job, monkeypatch, change
):
    store, service, _ = setup(data, profile)
    actual = evaluate

    def altered(vacancy, candidate, settings):
        result = actual(vacancy, candidate, settings)
        if change == "profile":
            store.save_profile(candidate.model_copy(update={"summary": "Updated approved facts"}))
        else:
            store.set_settings(settings.model_copy(update={"search_keywords": "Changed search"}))
        return result

    monkeypatch.setattr("applicator.service.evaluate", altered)
    with pytest.raises(ValueError, match="changed during discovery"):
        service.screen_discovery([job])
    assert store.applications() == [] and store.discovery_discards() == []


def test_batch_failure_rolls_back_new_discards_and_imports(data, profile, job, monkeypatch):
    store, service, _ = setup(data, profile)
    weak = job.model_copy(
        update={
            "source_id": "weak",
            "url": "https://example.test/weak",
            "requirements": ["Rust"],
            "description": "Rust",
        }
    )
    monkeypatch.setattr(store, "_add_job", Mock(side_effect=OSError("Fixture write failure")))
    with pytest.raises(OSError):
        service.screen_discovery([weak, job])
    assert store.discovery_discards() == [] and store.applications() == []
    with store.connect() as db:
        assert not db.execute("SELECT 1 FROM events WHERE kind LIKE 'discovery_%'").fetchone()


def test_concurrent_batches_keep_one_discard_and_one_application(data, profile, job):
    store, service, _ = setup(data, profile)
    weak = job.model_copy(
        update={
            "source_id": "weak",
            "url": "https://example.test/weak",
            "requirements": ["Rust"],
            "description": "Rust",
        }
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.screen_discovery([weak, job]), range(2)))
    assert sum(r["discarded"] for r in results) == sum(r["imported"] for r in results) == 1
    assert len(store.discovery_discards()) == len(store.applications()) == 1


def test_discard_log_is_paginated_and_rejects_invalid_bounds(data, profile, job):
    store, service, _ = setup(data, profile)
    jobs = [
        job.model_copy(
            update={
                "source_id": str(i),
                "url": f"https://example.test/weak/{i}",
                "requirements": ["Rust"],
                "description": "Rust",
            }
        )
        for i in range(3)
    ]
    service.screen_discovery(jobs)
    newest = store.discovery_discards(limit=1)[0]
    older = store.discovery_discards(limit=2, before=newest["id"])
    assert len(older) == 2 and older[0]["id"] > older[1]["id"]
    for kwargs in ({"limit": 0}, {"limit": 201}, {"before": 0}):
        with pytest.raises(ValueError):
            store.discovery_discards(**kwargs)


@pytest.mark.parametrize("provider", ["linkedin", "greenhouse", "worker"])
def test_all_discovery_entry_points_screen_jobs_and_expose_an_authenticated_separate_log(
    data, profile, job, monkeypatch, provider
):
    token = "screening-fixture-token-01234567890123456789"
    app = create_app(data, token)
    store = app.state.store
    store.save_profile(profile)
    store.set_settings(
        Settings(
            linkedin_authorised=True,
            automation_enabled=provider == "worker",
            discovery_enabled=True,
        )
    )
    weak = job.model_copy(
        update={
            "source": "linkedin",
            "source_id": "123",
            "url": "https://www.linkedin.com/jobs/view/123/",
            "requirements": ["Rust"],
            "description": "Rust",
        }
    )
    search = Mock(return_value=[weak])
    monkeypatch.setattr(LinkedInBrowser, "search", search)
    monkeypatch.setattr("applicator.api.greenhouse", Mock(return_value=[weak]))
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as session:
        route = "/api/worker/tick" if provider == "worker" else "/api/discover/" + provider
        response = session.post(
            route, json={"board": "example"} if provider == "greenhouse" else None
        )
        assert response.status_code == 200 and store.applications() == []
        if provider != "worker":
            assert response.json()["discarded"] == 1
        assert session.get("/api/discovery/discards").json()[0]["score"] < 50
        assert session.get("/api/discovery/discards?limit=201").status_code == 422
        assert (
            session.get("/api/discovery/discards", headers={"Authorization": ""}).status_code == 401
        )
        if provider != "greenhouse":
            session.post(route)
            assert search.call_args.kwargs["excluded_ids"] == {"123"}
    assert store.daily_usage().held == store.daily_usage().used == 0


@pytest.mark.browser
@pytest.mark.parametrize("all_excluded", [False, True])
def test_linkedin_search_never_opens_previously_discarded_jobs_or_consumes_the_result_limit(
    data, monkeypatch, all_excluded
):
    visits = []
    results = '<main><div class="jobs-search-results-list"><a href="https://www.linkedin.com/jobs/view/123/">Discarded</a><a href="https://www.linkedin.com/jobs/view/456/">New</a></div></main>'

    def context(self, playwright, **_):
        session = playwright.chromium.launch_persistent_context(
            str(data / "fictional-browser"), headless=True, **browser_options()
        )

        def route(request):
            path = urlsplit(request.request.url).path
            visits.append(path)
            request.fulfill(
                content_type="text/html", body=results if path == "/jobs/search/" else modern_job()
            )

        session.route("**/*", route)
        return session

    monkeypatch.setattr(LinkedInBrowser, "context", context)
    jobs = LinkedInBrowser(data).search(
        "Python", "Ireland", limit=1, excluded_ids={"123", "456"} if all_excluded else {"123"}
    )
    assert [job.source_id for job in jobs] == ([] if all_excluded else ["456"])
    assert "/jobs/view/123/" not in visits
    assert ("/jobs/view/456/" in visits) != all_excluded
