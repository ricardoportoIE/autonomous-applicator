from unittest.mock import MagicMock, Mock

import pytest

from applicator.models import Settings
from applicator.networking import Networking, target_url
from applicator.store import Store


def test_networking_scope_duplicate_budget_and_recovery(data, profile):
    store = Store(data / "db.sqlite3")
    store.save_profile(profile)
    network = Networking(store, data)
    with pytest.raises(ValueError):
        target_url("https://evil.test/in/someone")
    with pytest.raises(ValueError):
        network.add("https://www.linkedin.com/in/example/", "Alex", "Engineer", "Ireland")
    with pytest.raises(ValueError):
        network.add("https://www.linkedin.com/in/example/", "Alex", "Recruiter", "Brazil")
    network.add("https://www.linkedin.com/in/example/?trk=1", "Alex", "Recruiter", "Ireland")
    network.add("https://www.linkedin.com/in/example/", "Alex", "Recruiter", "Ireland")
    assert len(network.list()) == 1
    with pytest.raises(ValueError):
        network.reserve(1)
    store.set_settings(
        Settings(
            automation_enabled=True,
            linkedin_authorised=True,
            connections_enabled=True,
            daily_connection_limit=1,
        )
    )
    network.reserve(1)
    assert Networking(store, data).list()[0]["state"] == "uncertain"
    network.add("https://www.linkedin.com/in/another/", "Another", "Recruiter", "Ireland")
    with pytest.raises(ValueError):
        network.reserve(2)
    network.finish(1, "confirmed")
    assert network.list()[1]["state"] == "sent"


def test_networking_browser_receipt_and_failure(data, profile, monkeypatch):
    import applicator.networking as module

    store = Store(data / "db.sqlite3")
    profile.confirmed = False
    store.save_profile(profile)
    network = Networking(store, data)
    network.add("https://www.linkedin.com/in/example/", "Alex", "Recruiter", "Ireland")
    with pytest.raises(ValueError, match="Confirm"):
        network.send(1)
    profile.confirmed = True
    store.save_profile(profile)
    store.set_settings(
        Settings(
            automation_enabled=True,
            linkedin_authorised=True,
            connections_enabled=True,
            daily_connection_limit=10,
        )
    )
    context = MagicMock()
    page = context.__enter__.return_value.new_page.return_value
    page.url = "https://www.linkedin.com/in/example/"
    main = page.get_by_role.return_value
    main.get_by_role.return_value.filter.return_value.count.return_value = 1
    main.get_by_role.return_value.or_.return_value.filter.return_value.count.return_value = 1
    monkeypatch.setattr(module.LinkedInBrowser, "context", Mock(return_value=context))
    monkeypatch.setattr(module, "member_action_scope", Mock(return_value=main))
    monkeypatch.setattr(
        module,
        "member_details",
        Mock(return_value={"name": "Alex", "role": "Recruiter", "location": "Ireland"}),
    )
    assert network.send(1) == "linkedin:invitation-pending"
    network.add("https://www.linkedin.com/in/another/", "Another", "Recruiter", "Ireland")
    page.url = "https://www.linkedin.com/in/another/"
    with pytest.raises(ValueError, match="identity"):
        network.send(2)
    network.add("https://www.linkedin.com/in/alex2/", "Alex", "Recruiter", "Germany")
    page.url = "https://www.linkedin.com/in/alex2/"
    with pytest.raises(ValueError, match="location"):
        network.send(3)
    network.add("https://www.linkedin.com/in/alex3/", "Alex", "Recruiter", "Ireland")
    page.url = "https://www.linkedin.com/in/alex3/"
    main.get_by_role.return_value.filter.return_value.count.return_value = 2
    with pytest.raises(ValueError, match="ambiguous"):
        network.send(4)
    network.add("https://www.linkedin.com/in/redirected/", "Alex", "Recruiter", "Ireland")
    button_checks = main.get_by_role.call_count
    with pytest.raises(ValueError, match="identity"):
        network.send(5)
    assert main.get_by_role.call_count == button_checks


def test_cli_import_serve_loopback_and_login(data, profile, monkeypatch):
    import applicator.cli as module

    monkeypatch.setenv("APPLICATOR_DATA_DIR", str(data))
    path = data.parent / "profile.json"
    path.write_text(profile.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["applicator", "import-profile", str(path)])
    module.main()
    assert Store(data / "applicator.sqlite3").profile()[0].name == profile.name
    monkeypatch.setattr("sys.argv", ["applicator", "serve"])
    runner = Mock()
    monkeypatch.setattr(module.uvicorn, "run", runner)
    module.main()
    assert runner.call_args.kwargs["host"] == "127.0.0.1"
    assert runner.call_args.kwargs["proxy_headers"] is False
    monkeypatch.setenv("APPLICATOR_HOST", "0.0.0.0")
    with pytest.raises(ValueError):
        module.main()
    monkeypatch.setattr("sys.argv", ["applicator", "browser-login"])
    context = MagicMock()
    monkeypatch.setattr(module.LinkedInBrowser, "context", Mock(return_value=context))
    monkeypatch.setattr("builtins.input", Mock(return_value=""))
    module.main()
    context.__enter__.return_value.new_page.return_value.goto.assert_called_once_with(
        "https://www.linkedin.com/login"
    )


@pytest.mark.parametrize(
    "failure", ["closed_after_confirmation", "closed_during_navigation", "unrelated_cleanup"]
)
def test_browser_login_handles_only_confirmed_window_closure(
    data, profile, monkeypatch, capsys, failure
):
    from playwright.sync_api import Error

    import applicator.cli as module

    Store(data / "applicator.sqlite3").save_profile(profile)
    monkeypatch.setenv("APPLICATOR_DATA_DIR", str(data))
    monkeypatch.setattr("sys.argv", ["applicator", "browser-login"])
    monkeypatch.setattr(module, "sync_playwright", MagicMock())
    confirmation = Mock(return_value="")
    monkeypatch.setattr("builtins.input", confirmation)
    context = MagicMock()
    monkeypatch.setattr(module.LinkedInBrowser, "context", Mock(return_value=context))
    closed = Error("Target page, context or browser has been closed")
    if failure == "closed_during_navigation":
        context.__enter__.return_value.new_page.return_value.goto.side_effect = closed
    else:
        context.__exit__.side_effect = (
            closed
            if failure == "closed_after_confirmation"
            else Error("Unexpected browser cleanup failure")
        )
    if failure == "closed_after_confirmation":
        module.main()
        confirmation.assert_called_once()
        assert "local browser profile has been retained" in capsys.readouterr().out
    else:
        with pytest.raises(Error):
            module.main()
        assert "Sign-in step finished" not in capsys.readouterr().out
        if failure == "closed_during_navigation":
            confirmation.assert_not_called()
