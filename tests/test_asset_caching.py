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


def test_an_asset_the_browser_has_not_seen_is_sent_in_full(client):
    """A validator that does not match must produce the bytes, not a 304."""
    current = client.get("/web/style.css")
    stale = client.get("/web/style.css",
                       headers={"If-None-Match": '"deadbeefdeadbeefdeadbeefdeadbeef"'})
    assert stale.status_code == 200
    assert stale.content == current.content


def test_an_edited_file_is_never_answered_with_a_304(client, tmp_path, monkeypatch):
    """The failure this exists to prevent: new markup paired with an old stylesheet."""
    from server import app as app_module
    asset = tmp_path / "style.css"
    asset.write_text("a{color:red}")
    monkeypatch.setattr(app_module, "WEB_DIR", tmp_path)

    from server.app import create_app
    fresh_client = TestClient(create_app())
    first = fresh_client.get("/web/style.css")

    asset.write_text("a{color:blue} /* edited */")
    after = fresh_client.get("/web/style.css",
                             headers={"If-None-Match": first.headers["etag"]})
    assert after.status_code == 200, "an edited file must not be answered with a 304"
    assert b"blue" in after.content


def test_weak_validators_still_revalidate(client):
    """RFC 9110 §13.1.2: If-None-Match compares weakly.

    An intermediary that weakens the validator must not silently downgrade
    every request to a full 200 forever.
    """
    etag = client.get("/web/style.css").headers["etag"]
    weak = client.get("/web/style.css", headers={"If-None-Match": f"W/{etag}"})
    assert weak.status_code == 304


def test_wildcard_if_none_match_matches_any_representation(client):
    r = client.get("/web/style.css", headers={"If-None-Match": "*"})
    assert r.status_code == 304


def test_one_matching_etag_among_several_is_enough(client):
    etag = client.get("/web/style.css").headers["etag"]
    r = client.get("/web/style.css",
                   headers={"If-None-Match": f'"nope", {etag}, "also-nope"'})
    assert r.status_code == 304
