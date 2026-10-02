"""Single-contact invitations, visible-browser intent and durable progress contracts."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import Error as BrowserError
from test_contact_discovery import modern_profile

from applicator.api import create_app
from applicator.browser import LinkedInBrowser, ReviewRequired, browser_options
from applicator.models import Settings
from applicator.networking import Networking
from applicator.store import Store

TOKEN = "manual-networking-fixture-token-01234567890123456789"


def network_fixture(data):
    store = Store(data / "applicator.sqlite3")
    store.set_settings(Settings(linkedin_authorised=True))
    network = Networking(store, data)
    network.add(
        "https://www.linkedin.com/in/example/",
        "Example Recruiter",
        "Technical Recruiter",
        "Dublin, Ireland",
    )
    network.add("https://www.linkedin.com/in/other/", "Other", "Recruiter", "Ireland")
    return store, network


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "direct",
        "direct_link",
        "menu",
        "menu_popup",
        "delayed_actions",
        "follow_only",
        "recommendation",
        "duplicate",
        "redirect",
        "authwall",
        "identity",
        "location",
        "no_dialog",
        "no_receipt",
        "revoked",
        "no_controls",
    ],
)
def test_manual_invitation_uses_only_connect_and_selected_profile(data, monkeypatch, case):
    import applicator.networking as module

    store, network = network_fixture(data)
    html = modern_profile(
        heading="Different Member" if case == "identity" else "Example Recruiter",
        location="Germany" if case == "location" else "Dublin, Ireland",
    )
    connect = '<button onclick="connectMember()">Connect</button>'
    controls = "<button onclick=\"console.log('action:follow')\">Follow</button>"
    if case == "menu":
        controls += """<button onclick="document.querySelector('#menu').hidden=false">More</button><div id="menu" role="menu" hidden><button role="menuitem" onclick="connectMember()">Connect</button></div>"""
    elif case == "menu_popup":
        controls += """<button onclick="setTimeout(()=>document.querySelector('#menu').hidden=false,300)">More options</button><div id="menu" hidden><button onclick="connectMember()">Connect</button></div>"""
    elif case == "direct_link":
        controls += '<a href="#" onclick="event.preventDefault();connectMember()">Connect</a>'
    elif case not in {"follow_only", "recommendation"}:
        controls += connect * (2 if case == "duplicate" else 1)
    script = """<script>
    function connectMember() {
      console.log('action:connect');
      document.querySelector('#dialog').hidden=false;
    }
    function sendInvitation() {
      console.log('action:send');
      document.querySelector('#dialog').hidden=true;
      const pending=document.createElement('button'); pending.textContent='Pending';
      document.querySelector('article').append(pending);
    }
    </script>
    <div id="dialog" role="dialog" aria-labelledby="invitation-heading" hidden>
      <h2 id="invitation-heading">Add a note to your invitation?</h2>
      <p>Personalise your invitation to Example Recruiter by adding a note.</p>
      <button onclick="console.log('action:add-note')">Add a note</button>
      <button onclick="sendInvitation()">Send without a note</button>
    </div>"""
    if case == "no_dialog":
        script = script.replace("document.querySelector('#dialog').hidden=false;", "")
    if case == "no_receipt":
        script = script.replace("document.querySelector('article').append(pending);", "")
    html = html.replace("</article>", controls + "</article>") + script
    if case == "recommendation":
        html = html.replace("</aside>", connect + "</aside>")
    if case == "delayed_actions":
        html = (
            html.replace(controls, '<div id="actions" hidden>' + controls + "</div>")
            + '<script>setTimeout(()=>document.querySelector("#actions").hidden=false,500)</script>'
        )
    if case == "no_controls":
        html = html.replace(controls, "").replace("</aside>", "<button>Follow</button></aside>")
    visited, actions, modes = [], [], []

    def fixture_context(self, playwright, *, headless=True):
        modes.append(headless)
        context = playwright.chromium.launch_persistent_context(
            str(data / "fixture-browser"), headless=True, **browser_options()
        )

        def route(request):
            visited.append(request.request.url)
            if case in {"redirect", "authwall"} and request.request.url.endswith("/in/example/"):
                request.fulfill(
                    status=302,
                    headers={
                        "Location": "https://www.linkedin.com/"
                        + ("in/other/" if case == "redirect" else "checkpoint/")
                    },
                )
            else:
                request.fulfill(content_type="text/html", body=html)

        context.route("**/*", route)
        context.on(
            "page",
            lambda page: page.on(
                "console",
                lambda message: (
                    actions.append(message.text) if message.text.startswith("action:") else None
                ),
            ),
        )
        return context

    monkeypatch.setattr(LinkedInBrowser, "context", fixture_context)
    if case == "revoked":
        original = module.member_details

        def revoke(page):
            result = original(page)
            store.set_settings(Settings())
            return result

        monkeypatch.setattr(module, "member_details", revoke)
    if case in {"direct", "direct_link", "menu", "menu_popup", "delayed_actions"}:
        assert network.send(1, manual=True) == "linkedin:invitation-pending"
        assert network.status(1)["run_status"] == "done"
        assert actions == ["action:connect", "action:send"]
    else:
        with pytest.raises((ValueError, BrowserError)):
            network.send(1, manual=True)
        assert network.status(1)["run_status"] == (
            "uncertain" if case in {"no_dialog", "no_receipt"} else "failed"
        )
        if case not in {"no_dialog", "no_receipt"}:
            assert not actions
    assert "action:follow" not in actions
    assert "action:add-note" not in actions
    assert visited[0] == "https://www.linkedin.com/in/example/"
    assert all("/jobs/" not in url and "/search/" not in url for url in visited)
    assert modes == [False]
    assert network.status(2)["state"] == "queued"
    assert network.status(2)["day"] is None
    assert store.applications() == []
    assert not store.settings().automation_enabled
    assert not store.settings().connections_enabled
    with pytest.raises(ValueError, match="not queued"):
        store.set_settings(Settings(linkedin_authorised=True))
        network.send(1, manual=True)


def test_manual_scope_quota_and_duplicate_are_checked_before_browser(data, monkeypatch):
    store, network = network_fixture(data)
    launch = Mock()
    monkeypatch.setattr(LinkedInBrowser, "context", launch)
    store.set_settings(Settings())
    with pytest.raises(ValueError, match="scope"):
        network.send(1, manual=True)
    assert network.status(1)["day"] is None
    store.set_settings(Settings(linkedin_authorised=True, daily_connection_limit=1))
    network.reserve(1, manual=True)
    for target in [1, 2]:
        with pytest.raises(ValueError, match="not queued|daily limit"):
            network.send(target, manual=True)
    launch.assert_not_called()


@pytest.mark.parametrize(
    "error", [BrowserError("private-cookie-and-member-url"), RuntimeError("private-runtime-data")]
)
def test_pre_browser_failure_has_a_sanitised_durable_failed_status(data, monkeypatch, error):
    _, network = network_fixture(data)
    monkeypatch.setattr(LinkedInBrowser, "context", Mock(side_effect=error))
    with pytest.raises(type(error)):
        network.send(1, manual=True)
    row = network.status(1)
    assert row["state"] == row["run_status"] == "failed"
    assert "private-cookie" not in row["run_message"]
    assert "private-runtime-data" not in row["run_message"]
    assert row["receipt"] is None
    assert row["day"] is not None


def test_existing_database_migrates_and_interrupted_runs_are_owned(data):
    store = Store(data / "applicator.sqlite3")
    with store.connect() as db:
        db.execute(
            "CREATE TABLE connections (id INTEGER PRIMARY KEY,url TEXT UNIQUE NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL,location TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'queued',day TEXT,receipt TEXT)"
        )
        db.execute(
            "INSERT INTO connections(id,url,name,role,location) VALUES(1,'https://www.linkedin.com/in/example/','Example','Recruiter','Ireland')"
        )
        db.execute(
            "INSERT INTO connections(id,url,name,role,location,state) VALUES(2,'https://www.linkedin.com/in/uncertain/','Example','Recruiter','Ireland','uncertain')"
        )
        db.execute(
            "INSERT INTO connections(id,url,name,role,location,state,receipt) VALUES(3,'https://www.linkedin.com/in/sent/','Example','Recruiter','Ireland','sent','fixture:pending')"
        )
    network = Networking(store, data)
    assert network.status(1)["run_status"] == "idle"
    assert network.status(2)["run_status"] == "uncertain"
    assert network.status(3)["run_status"] == "done"
    store.set_settings(Settings(linkedin_authorised=True))
    row = network.reserve(1, manual=True)
    with pytest.raises(ValueError, match="run changed"):
        network.progress(1, "wrong-run", "Unowned update")
    with pytest.raises(ValueError, match="run changed"):
        network.finish(1, "unowned receipt", run_id="wrong-run")
    assert network.status(1)["run_message"] == "Starting the selected invitation."
    recovered = Networking(store, data)
    assert recovered.status(1)["run_status"] == "uncertain"
    with pytest.raises(ValueError, match="run changed"):
        recovered.finish(1, "old receipt", run_id=row["run_id"])
    assert recovered.status(1)["receipt"] is None


def test_manual_api_keeps_status_readable_and_rejects_busy_browser(data, monkeypatch):
    app = create_app(data, TOKEN)
    app.state.store.set_settings(Settings(linkedin_authorised=True))
    app.state.network.add("https://www.linkedin.com/in/example/", "Example", "Recruiter", "Ireland")
    session = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    started, release = threading.Event(), threading.Event()
    automatic = Mock()
    monkeypatch.setattr(app.state.service, "tick", automatic)

    def send(connection_id, *, manual):
        row = app.state.network.reserve(connection_id, manual=manual)
        app.state.network.progress(connection_id, row["run_id"], "Opening selected profile.")
        started.set()
        assert release.wait(timeout=15)
        app.state.network.finish(connection_id, "fixture:pending", run_id=row["run_id"])
        return "fixture:pending"

    monkeypatch.setattr(app.state.network, "send", send)
    assert session.get("/api/connections/999/status").status_code == 404
    assert (
        session.get("/api/connections/1/status", headers={"Authorization": "invalid"}).status_code
        == 401
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(session.post, "/api/connections/1/send")
        try:
            assert started.wait(timeout=5)
            assert session.get("/api/connections/1/status").json()["run_status"] == "running"
            busy = session.post("/api/connections/1/send")
            assert busy.status_code == 409
            assert "browser is busy" in busy.json()["detail"]
        finally:
            release.set()
        assert future.result().status_code == 200
    assert session.get("/api/connections/1/status").json()["run_status"] == "done"
    automatic.assert_not_called()


def test_application_adapter_still_requires_candidate_facts(data, job):
    job.source_id = "123"
    job.url = "https://www.linkedin.com/jobs/view/123/"
    with pytest.raises(ReviewRequired, match="candidate profile"):
        LinkedInBrowser(data).submit(job, {}, data)
