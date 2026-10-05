"""Hostile inputs use disposable storage and controlled local transports only."""

import asyncio
import os
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from applicator.api import create_app, local_token
from applicator.discovery import greenhouse

TOKEN = "security-fixture-token-01234567890123456789"


def assert_private_headers(response):
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "base-uri 'none'" in response.headers["content-security-policy"]
    assert "form-action 'self'" in response.headers["content-security-policy"]
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert TOKEN not in response.text


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "localhost:evil"},
        {"Host": "localhost:80:90"},
        {"Host": "localhost:"},
        {"Host": "localhost:0"},
        {"Host": "localhost:65536"},
        {"Host": "localhost:00000080"},
        {"Host": "localhost.evil.test"},
        {"Host": "localhost@evil.test"},
        {"Host": "127.0.0.1:8765/path"},
        {"Host": "127.0.0.1:8765", "Origin": "null"},
        {"Host": "localhost:8765", "Origin": "https://localhost:8765"},
        [("Host", "localhost"), ("Host", "evil.test")],
        [("Host", "localhost"), ("Host", "localhost")],
        [("Origin", "http://testserver"), ("Origin", "http://testserver")],
        [("Origin", "http://testserver"), ("Origin", "https://evil.test")],
    ],
)
def test_ambiguous_authorities_are_rejected_before_body_read(data, monkeypatch, headers):
    app = create_app(data, TOKEN)
    from starlette.requests import Request

    async def forbidden_read(*_args):
        raise AssertionError("An untrusted body must not be read")
        yield b""  # Give Starlette an iterator without reading until intake starts.

    reader = Mock(side_effect=forbidden_read)
    monkeypatch.setattr(Request, "stream", reader)
    response = TestClient(app).post("/api/jobs", headers=headers, content=b"private")
    assert response.status_code == 403
    assert_private_headers(response)
    assert reader.call_count == 1  # Starlette constructs its cached iterator without consuming it.
    assert not app.state.store.applications()


@pytest.mark.parametrize("authority", ["localhost", "127.0.0.1:1", "localhost:65535"])
def test_valid_local_authorities_keep_exact_origin_matching(data, authority):
    client = TestClient(create_app(data, TOKEN))
    response = client.get(
        "/api/health", headers={"Host": authority, "Origin": "http://" + authority}
    )
    assert response.status_code == 200
    assert_private_headers(response)


# API construction and SQLite setup are included in this functional property.
# Dedicated performance and intake-deadline tests measure the timing contracts.
@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(suffix=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=40))
def test_dns_rebinding_suffixes_never_gain_local_access(data, suffix):
    response = TestClient(create_app(data, TOKEN)).get(
        "/api/settings",
        headers={"Host": "localhost." + suffix, "Authorization": "Bearer " + TOKEN},
    )
    assert response.status_code == 403
    assert_private_headers(response)


@pytest.mark.parametrize("size,status", [(500_000, 405), (500_001, 413)])
def test_body_limit_boundary_and_error_headers(data, size, status):
    response = TestClient(create_app(data, TOKEN)).post("/api/health", content=b"x" * size)
    assert response.status_code == status
    assert_private_headers(response)


@pytest.mark.parametrize("path,status", [("/api/settings", 401), ("/missing", 404)])
def test_authentication_and_missing_routes_have_private_headers(data, path, status):
    response = TestClient(create_app(data, TOKEN)).get(path)
    assert response.status_code == status
    assert_private_headers(response)


def test_slow_intake_is_cancelled_without_starting_an_operation(data, monkeypatch):
    app = create_app(data, TOKEN)
    real_timeout = asyncio.timeout
    deadline = Mock(side_effect=lambda seconds: real_timeout(0.01))
    monkeypatch.setattr("applicator.api.asyncio.timeout", deadline)

    async def body():
        yield b"{"
        await asyncio.Event().wait()

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            return await client.post(
                "/api/jobs", content=body(), headers={"Authorization": "Bearer " + TOKEN}
            )

    response = asyncio.run(request())
    assert response.status_code == 408
    assert_private_headers(response)
    deadline.assert_called_once_with(10)
    assert not app.state.store.applications()
    with app.state.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM application_runs").fetchone()[0] == 0


def test_operation_timeout_is_not_mislabelled_as_body_timeout(data):
    app = create_app(data, TOKEN)

    @app.get("/api/fixture-timeout")
    def operation():
        raise TimeoutError("fixture operation budget")

    app.router.routes.insert(0, app.router.routes.pop())
    with pytest.raises(TimeoutError, match="operation budget"):
        TestClient(app).get("/api/fixture-timeout")


def test_token_creation_is_exclusive_and_owner_only_on_posix(data, monkeypatch):
    monkeypatch.delenv("APPLICATOR_TOKEN", raising=False)
    token = local_token(data)
    assert len(token) >= 32 and local_token(data) == token
    if os.name == "posix":
        assert (data / "access-token").stat().st_mode & 0o777 == 0o600


def test_concurrent_token_creator_is_never_overwritten(data, monkeypatch):
    monkeypatch.delenv("APPLICATOR_TOKEN", raising=False)

    def won_creation(*args):
        (data / "access-token").write_text(TOKEN, encoding="utf-8")
        raise FileExistsError

    monkeypatch.setattr("applicator.api.os.open", won_creation)
    assert local_token(data) == TOKEN


@pytest.mark.parametrize("fault", ["link", "directory", "oversized", "late_link"])
def test_unsafe_token_files_are_refused_without_reading_or_replacing(data, monkeypatch, fault):
    monkeypatch.delenv("APPLICATOR_TOKEN", raising=False)
    data.mkdir()
    path = data / "access-token"
    if fault == "directory":
        path.mkdir()
    else:
        path.write_text(TOKEN if fault != "oversized" else "x" * 4097, encoding="utf-8")
    if fault in {"link", "late_link"}:
        check = Mock(side_effect=[True] if fault == "link" else [False, True])
        monkeypatch.setattr(Path, "is_symlink", check)
    read = Mock(side_effect=AssertionError("Unsafe token must not be read"))
    monkeypatch.setattr(Path, "read_text", read)
    with pytest.raises(ValueError, match="regular file"):
        local_token(data)
    read.assert_not_called()
    assert path.exists()


class EndlessBoard(httpx.SyncByteStream):
    def __init__(self):
        self.read_bytes = 0
        self.closed = False

    def __iter__(self):
        while True:
            self.read_bytes += 65536
            yield b"x" * 65536

    def close(self):
        self.closed = True


def test_board_limit_stops_an_endless_stream_and_closes_transport():
    stream = EndlessBoard()
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    ) as client:
        with pytest.raises(ValueError, match="size limit"):
            greenhouse("fixture", client)
    assert 5_000_000 < stream.read_bytes <= 5_000_000 + 65536
    assert stream.closed


def test_board_size_boundary_accepts_valid_json_without_trusting_content_length():
    payload = b'{"jobs": []}'
    payload += b" " * (5_000_000 - len(payload))

    def respond(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(200, content=payload, headers={"Content-Length": "1"})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert greenhouse("fixture", client) == []


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "unknown"])
def test_board_rejects_unsolicited_compression_before_consuming_bytes(encoding):
    stream = EndlessBoard()
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, stream=stream, headers={"Content-Encoding": encoding}
            )
        )
    ) as client:
        with pytest.raises(ValueError, match="content encoding"):
            greenhouse("fixture", client)
    assert stream.read_bytes == 0 and stream.closed


@pytest.mark.parametrize("status", [301, 302, 307, 308, 500])
def test_external_board_errors_do_not_follow_redirects_or_parse_bodies(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "http://127.0.0.1/private"})

    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        with pytest.raises(httpx.HTTPStatusError):
            greenhouse("fixture", client)
    assert len(requests) == 1
    assert requests[0].url.host == "boards-api.greenhouse.io"
