"""PWA install: manifest, MIME type, and static icon serving."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from server.app import create_app
    return TestClient(create_app())


def test_manifest_served_with_correct_mime(client):
    r = client.get("/web/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")


def test_manifest_is_valid_json_with_required_fields(client):
    r = client.get("/web/manifest.webmanifest")
    manifest = json.loads(r.text)
    for field in ("name", "short_name", "start_url", "display", "icons"):
        assert field in manifest, f"manifest missing required field: {field}"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert isinstance(manifest["icons"], list)
    assert len(manifest["icons"]) >= 2


def test_manifest_lists_existing_icon_files(client):
    r = client.get("/web/manifest.webmanifest")
    manifest = json.loads(r.text)
    for icon in manifest["icons"]:
        # Each icon src must be served by the app.
        icon_r = client.get(icon["src"])
        assert icon_r.status_code == 200, f"icon not served: {icon['src']}"
        assert icon_r.headers["content-type"].startswith("image/png")


def test_apple_touch_icon_served(client):
    r = client.get("/web/icons/apple-touch-icon.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")


def test_icon_svg_served_as_svg_xml(client):
    r = client.get("/web/icons/icon.svg")
    assert r.status_code == 200
    # FastAPI infers image/svg+xml from the .svg extension.
    assert "svg" in r.headers["content-type"]


def _assert_pwa_tags(html: str, page_name: str) -> None:
    """Helper: every page must link the manifest, apple-touch icon, and SVG icon,
    plus carry the iOS standalone meta tags."""
    assert '/web/manifest.webmanifest' in html, f"{page_name}: missing manifest link"
    assert '/web/icons/apple-touch-icon.png' in html, f"{page_name}: missing apple-touch-icon link"
    assert '/web/icons/icon.svg' in html, f"{page_name}: missing SVG icon link"
    assert 'apple-mobile-web-app-capable' in html, f"{page_name}: missing iOS standalone meta"
    assert 'apple-mobile-web-app-status-bar-style' in html, f"{page_name}: missing iOS status bar meta"
    assert 'apple-mobile-web-app-title' in html, f"{page_name}: missing iOS app title meta"


def test_index_has_pwa_meta_tags(client):
    r = client.get("/")
    _assert_pwa_tags(r.text, "index.html")


def test_read_page_has_pwa_meta_tags(client):
    r = client.get("/read/any-book-id")
    _assert_pwa_tags(r.text, "read.html")


def test_book_page_has_pwa_meta_tags(client):
    r = client.get("/book/any-book-id")
    _assert_pwa_tags(r.text, "book.html")


def test_theme_color_has_dark_variant(client):
    r = client.get("/")
    # Both light and dark theme-color meta tags must be present.
    assert 'theme-color' in r.text
    assert '#fbfaf7' in r.text  # light bg
    assert '#15130f' in r.text  # dark bg
