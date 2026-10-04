"""The local vector mark stays available, accessible and crisp in the packaged UI."""

from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree

import pytest
from playwright.sync_api import expect
from test_frontend import dashboard as dashboard
from test_react_frontend import check_accessibility


@pytest.mark.browser
@pytest.mark.parametrize("width", [390, 1440])
def test_local_icon_matches_favicon_and_survives_lock(dashboard, width):
    page, app, origin = dashboard
    page.set_viewport_size({"width": width, "height": 900})
    brand = page.locator(".brand")
    mark = brand.locator("img")
    expect(brand).to_have_accessible_name("Autonomous Applicator")
    expect(mark).to_have_attribute("alt", "")
    expect(mark).to_have_attribute("aria-hidden", "true")
    assert mark.evaluate("image => image.complete && image.naturalWidth === 64")
    assert mark.bounding_box()["width"] == mark.bounding_box()["height"] == 44
    icon_url = mark.evaluate("image => image.src")
    favicon = urljoin(origin, page.locator('link[rel="icon"]').get_attribute("href"))
    assert favicon == icon_url == origin + "/icon.svg"
    response = page.request.get(favicon)
    assert response.ok
    assert response.headers["content-type"].startswith("image/svg+xml")
    authored = Path("frontend/public/icon.svg").read_bytes()
    assert response.body() == Path("src/applicator/static/icon.svg").read_bytes() == authored
    svg = ElementTree.fromstring(authored)  # noqa: S314 - repository-owned SVG only
    assert svg.attrib["viewBox"] == "0 0 64 64"
    assert all(
        node.tag.rsplit("}", 1)[-1] in {"svg", "g", "rect", "path", "circle"}
        and not any("href" in key or key.startswith("on") for key in node.attrib)
        for node in svg.iter()
    )
    page.get_by_role("button", name="Lock workspace", exact=True).click()
    expect(mark).to_be_visible()
    expect(brand).to_have_accessible_name("Autonomous Applicator")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert app.state.store.daily_usage().attempts == 0
    check_accessibility(page)
