"""Static assets must revalidate, so a rebuilt reader reaches the browser.

The reader is left open for hours, installed as a PWA, and launched into a
dedicated desktop browser profile — three caches that each have to turn over
unaided. Responses already carry an ETag, but without a Cache-Control header a
browser applies its own heuristic freshness and may not ask whether that ETag
still matches, which is how a rebuilt reader kept showing the previous build.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from server.app import create_app
    return TestClient(create_app())


PAGES = ["/", "/web/read.html", "/web/index.html"]
ASSETS = [
    "/web/style.css",
    "/web/js/reader.js",
    "/web/js/reader/media-session.js",
    "/web/manifest.webmanifest",
]


@pytest.mark.parametrize("path", PAGES + ASSETS)
def test_asset_must_be_revalidated_before_reuse(client, path):
    r = client.get(path)
    assert r.status_code == 200, path
    cache_control = r.headers.get("cache-control", "")
    assert "no-cache" in cache_control, f"{path} sent {cache_control!r}"


@pytest.mark.parametrize("path", PAGES + ASSETS)
def test_asset_still_carries_a_validator(client, path):
    """no-cache is only cheap if the browser has something to revalidate with."""
    r = client.get(path)
    assert r.headers.get("etag"), f"{path} has no ETag"


@pytest.mark.parametrize("path", ASSETS)
def test_unchanged_asset_revalidates_to_304_without_resending_bytes(client, path):
    """Ordinary navigation must not refetch everything — that is what 304 is for."""
    first = client.get(path)
    again = client.get(path, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304, path
    assert not again.content


def test_a_changed_asset_is_not_served_from_cache(client, tmp_path, monkeypatch):
    """The failure this exists to prevent: new markup paired with an old stylesheet."""
    r = client.get("/web/style.css")
    stale_etag = "\"deadbeefdeadbeefdeadbeefdeadbeef\""
    fresh = client.get("/web/style.css", headers={"If-None-Match": stale_etag})
    assert fresh.status_code == 200
    assert fresh.content == r.content
