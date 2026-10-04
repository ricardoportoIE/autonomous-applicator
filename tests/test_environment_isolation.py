"""CLI fixtures cannot load a workspace's private runtime configuration."""

import os
from unittest.mock import Mock

import applicator.cli as cli


def test_cli_fixture_ignores_local_dotenv_credentials_and_paths(tmp_path, monkeypatch):
    assert not any(name.startswith(("OPENAI_", "APPLICATOR_")) for name in os.environ)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=fixture-only-never-sent\n"
        "APPLICATOR_HOST=0.0.0.0\n"
        "APPLICATOR_DATA_DIR=private-workspace\n",
        encoding="utf-8",
    )
    data = tmp_path / "disposable"
    monkeypatch.setenv("APPLICATOR_DATA_DIR", str(data))
    monkeypatch.setattr("sys.argv", ["applicator", "serve"])
    runner = Mock()
    monkeypatch.setattr(cli.uvicorn, "run", runner)
    cli.main()
    assert runner.call_args.kwargs["host"] == "127.0.0.1"
    assert os.getenv("OPENAI_API_KEY") is None
    assert os.getenv("APPLICATOR_DATA_DIR") == str(data)
    assert not (tmp_path / "private-workspace").exists()
    assert (data / "access-token").is_file()
