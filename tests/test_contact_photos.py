"""Private portrait capture, bounded caches and authenticated image delivery."""

import base64
from io import BytesIO
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from playwright.sync_api import sync_playwright
from test_contact_discovery import modern_profile

from applicator.api import create_app
from applicator.browser import browser_options, capture_member_photo
from applicator.photos import MAX_PHOTO_BYTES, photo_path, save_photo, stored_photo, valid_photo

TOKEN = "photo-fixture-token-0123456789012345678901234567"
URL = "https://www.linkedin.com/in/example/"


def example_photo():
    stream = BytesIO()
    Image.new("RGB", (64, 64), (110, 70, 180)).save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize(
    "case", ["valid", "empty", "wrong_type", "too_large", "oversized_dimensions"]
)
def test_photo_cache_accepts_only_small_png_images(data, case):
    content = example_photo()
    if case == "empty":
        content = b""
    elif case == "wrong_type":
        content = b"<svg onload='alert(1)'></svg>"
    elif case == "too_large":
        content += b"x" * MAX_PHOTO_BYTES
    elif case == "oversized_dimensions":
        content = content[:16] + (4096).to_bytes(4, "big") + content[20:]
    assert save_photo(data, URL, content) == (case == "valid")
    assert (stored_photo(data, URL) is not None) == (case == "valid")
    if case == "valid":
        assert stored_photo(data, URL).read_bytes() == content
        assert photo_path(data, URL).name.endswith(".png")
        assert not list(photo_path(data, URL).parent.glob("*.tmp"))


def test_missing_corrupt_and_oversized_photo_files_are_not_served(data):
    assert stored_photo(data, URL) is None
    path = photo_path(data, URL)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not an image")
    assert stored_photo(data, URL) is None
    path.write_bytes(example_photo() + b"x" * MAX_PHOTO_BYTES)
    assert stored_photo(data, URL) is None


def test_photo_cache_cannot_escape_private_data_and_io_failures_are_optional(data, monkeypatch):
    import applicator.photos as module

    outside = data.parent / "outside.png"
    monkeypatch.setattr(module, "photo_path", Mock(return_value=outside))
    assert not save_photo(data, URL, example_photo())
    assert stored_photo(data, URL) is None
    assert not outside.exists()
    monkeypatch.undo()
    monkeypatch.setattr(module.Path, "write_bytes", Mock(side_effect=OSError("cache unavailable")))
    assert not save_photo(data, URL, example_photo())


def test_photo_delivery_requires_authentication_and_retains_private_headers(data):
    app = create_app(data, TOKEN)
    app.state.network.add(URL, "Example Recruiter", "Recruiter", "Ireland")
    session = TestClient(app, headers={"Authorization": "Bearer " + TOKEN})
    assert not session.get("/api/connections").json()[0]["photo_available"]
    assert session.get("/api/connections/1/photo").status_code == 404
    assert session.get("/api/connections/999/photo").status_code == 404
    content = example_photo()
    assert save_photo(data, URL, content)
    assert session.get("/api/connections").json()[0]["photo_available"]
    assert session.get("/api/connections/1/status").json()["photo_available"]
    response = session.get("/api/connections/1/photo")
    assert response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "blob:" in response.headers["content-security-policy"]
    assert (
        session.get("/api/connections/1/photo", headers={"Authorization": "invalid"}).status_code
        == 401
    )


@pytest.mark.browser
@pytest.mark.parametrize(
    "case",
    [
        "portrait",
        "delayed_portrait",
        "cover_only",
        "duplicate",
        "recommended_only",
        "unloaded",
        "wrong_name",
        "redirect",
        "broken_cache",
    ],
)
def test_portrait_capture_is_bound_to_verified_primary_identity(data, case, monkeypatch):
    import applicator.browser as module

    encoded = base64.b64encode(example_photo()).decode()
    portrait = (
        f'<img alt="" style="width:152px;height:152px" src="data:image/png;base64,{encoded}">'
    )
    cover = f'<img alt="" style="width:240px;height:80px" src="data:image/png;base64,{encoded}">'
    logo = f'<img alt="" style="width:32px;height:32px" src="data:image/png;base64,{encoded}">'
    html = modern_profile() + ""
    primary = cover + logo
    if case not in {"cover_only", "recommended_only"}:
        primary += portrait * (2 if case == "duplicate" else 1)
    html = html.replace("</article>", primary + "</article>")
    if case == "delayed_portrait":
        html = html.replace(
            portrait,
            portrait.replace(
                f"data:image/png;base64,{encoded}", "https://www.linkedin.com/__test/portrait.png"
            ),
        )
        html += f"<script>setTimeout(()=>document.querySelector('img[src*=\"__test/portrait\"]').src='data:image/png;base64,{encoded}',500)</script>"
    if case == "recommended_only":
        html = html.replace("</aside>", portrait + "</aside>")
    if case == "unloaded":
        html = html.replace(f"data:image/png;base64,{encoded}", "data:image/png;base64,invalid")
    if case == "broken_cache":
        monkeypatch.setattr(
            module, "save_photo", Mock(side_effect=OSError("private cache failure"))
        )
    details = {
        "name": "Different Member" if case == "wrong_name" else "Example Recruiter",
        "role": "Technical Recruiter",
        "location": "Dublin, Ireland",
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        page = browser.new_page()
        page.route(
            "**/*",
            lambda route: (
                None
                if route.request.url.endswith("__test/portrait.png")
                else route.fulfill(content_type="text/html", body=html)
            ),
        )
        page.goto("https://www.linkedin.com/in/other/" if case == "redirect" else URL)
        expected = case in {"portrait", "delayed_portrait"}
        assert capture_member_photo(page, data, URL, details) == expected
        assert (stored_photo(data, URL) is not None) == expected
        if expected:
            assert valid_photo(stored_photo(data, URL).read_bytes())
        browser.close()
