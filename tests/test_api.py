"""End-to-end FastAPI tests via TestClient."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from server.app import create_app
    return TestClient(create_app())


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Readbrick" in r.text


def test_user_lifecycle(client):
    assert client.get("/api/users").json() == []
    r = client.post("/api/users", json={"name": "Alice"})
    assert r.status_code == 201
    user = r.json()
    assert user["name"] == "Alice"

    assert len(client.get("/api/users").json()) == 1
    # duplicate
    r = client.post("/api/users", json={"name": "Alice"})
    assert r.status_code == 409
    # empty
    r = client.post("/api/users", json={"name": ""})
    assert r.status_code == 400

    r = client.delete(f"/api/users/{user['id']}")
    assert r.status_code == 204
    assert client.get("/api/users").json() == []


def test_prefs_get_and_patch(client):
    user = client.post("/api/users", json={"name": "Bob"}).json()
    p = client.get(f"/api/users/{user['id']}/prefs").json()
    assert p["speed"] == 0.9
    p2 = client.patch(
        f"/api/users/{user['id']}/prefs",
        json={"speed": 1.4, "font_size": 22, "theme": "dark"},
    ).json()
    assert p2["speed"] == 1.4
    assert p2["font_size"] == 22
    assert p2["theme"] == "dark"


def test_upload_txt_and_get(client, fixtures_dir: Path):
    user = client.post("/api/users", json={"name": "Carol"}).json()

    with open(fixtures_dir / "tiny.txt", "rb") as f:
        r = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")})
    assert r.status_code == 201
    book = r.json()
    assert book["format"] == "txt"
    assert book["paragraph_count"] == 4

    full = client.get(f"/api/books/{book['id']}").json()
    assert "chapters" in full
    paragraphs = [p for ch in full["chapters"] for p in ch["paragraphs"]]
    assert any("Once upon a time" in p["text"] for p in paragraphs)

    listed = client.get(f"/api/books?user_id={user['id']}").json()
    assert len(listed) == 1


def test_upload_epub(client, fixtures_dir: Path):
    with open(fixtures_dir / "tiny.epub", "rb") as f:
        r = client.post(
            "/api/books",
            files={"file": ("tiny.epub", f, "application/epub+zip")},
        )
    assert r.status_code == 201
    book = r.json()
    assert book["format"] == "epub"
    assert book["author"] == "Test Author"


def test_upload_unsupported(client, tmp_path):
    fake = tmp_path / "x.xyz"
    fake.write_bytes(b"junk")
    with open(fake, "rb") as f:
        r = client.post("/api/books", files={"file": ("x.xyz", f, "application/octet-stream")})
    assert r.status_code == 415


def test_progress_endpoints(client, fixtures_dir: Path):
    user = client.post("/api/users", json={"name": "Dan"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()

    # initial progress
    p = client.get(f"/api/users/{user['id']}/progress/{book['id']}").json()
    assert p["paragraph_idx"] == 0

    r = client.put(
        f"/api/users/{user['id']}/progress/{book['id']}",
        json={"paragraph_idx": 2, "char_offset": 0},
    )
    assert r.status_code == 200
    p = client.get(f"/api/users/{user['id']}/progress/{book['id']}").json()
    assert p["paragraph_idx"] == 2

    # listing books for that user now shows progress info
    listed = client.get(f"/api/books?user_id={user['id']}").json()
    assert listed[0]["progress_pct"] > 0


def test_voices_endpoint_lists_kokoro(client):
    """The Kokoro English voices are always listed (static — no container needed)."""
    voices = client.get("/api/voices").json()
    ids = [v["voice_id"] for v in voices]
    assert "kokoro:af_heart" in ids
    assert all(v["voice_id"].startswith("kokoro:") for v in voices)
    assert all("backend" in v for v in voices)


def test_books_list_includes_metadata_and_est_minutes(client, fixtures_dir: Path):
    user = client.post("/api/users", json={"name": "Eve"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()

    listed = client.get(f"/api/books?user_id={user['id']}").json()
    assert len(listed) == 1
    b = listed[0]
    # New fields exist on the response (None in offline test env)
    assert "description" in b
    assert "published_year" in b
    assert "isbn" in b
    assert "genre" in b
    assert "word_count" in b
    assert "metadata_source" in b
    # Word count is populated locally (no network needed)
    assert isinstance(b["word_count"], int) and b["word_count"] > 0
    # est_minutes is computed: round(word_count / 150)
    assert b["est_minutes"] == round(b["word_count"] / 150)
    assert b["metadata_source"] == "none"


# ───── book detail page + per-book actions ─────


def test_get_book_detail_serves_html(client):
    """GET /book/<id> serves the detail page shell."""
    r = client.get("/book/anything-nonexistent")
    assert r.status_code == 200
    assert "Readbrick" in r.text


def test_patch_book_updates_fields(client, fixtures_dir):
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.patch(f"/api/books/{book['id']}", json={
        "title": "Edited Title",
        "author": "New Author",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Edited Title"
    assert body["author"] == "New Author"


def test_patch_book_rejects_bad_year(client, fixtures_dir):
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.patch(f"/api/books/{book['id']}", json={"published_year": 9999})
    assert r.status_code == 400


def test_post_book_refresh_returns_structured_response(client, fixtures_dir):
    """Refresh returns book, fields_filled, new_cover_sources keys."""
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.post(f"/api/books/{book['id']}/refresh")
    assert r.status_code == 200
    body = r.json()
    assert "book" in body
    assert "fields_filled" in body
    assert "new_cover_sources" in body


def test_get_book_covers_default_shape(client, fixtures_dir):
    """For a TXT book with no covers, available is [], active is null."""
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.get(f"/api/books/{book['id']}/covers")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is None
    assert body["available"] == []


def test_put_book_cover_unknown_source_returns_400(client, fixtures_dir):
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.put(f"/api/books/{book['id']}/cover", json={"source": "myspace"})
    assert r.status_code == 400


def test_post_book_cover_uploads_custom(client, fixtures_dir):
    """Multipart upload writes covers/custom.jpg and makes it active."""
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()

    fake_jpeg = b"\xff\xd8\xff\xe0" + b"x" * 200
    r = client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("user.jpg", fake_jpeg, "image/jpeg")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == "custom"
    assert "custom" in body["available"]


def test_post_book_cover_rejects_non_image(client, fixtures_dir):
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("plain.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_post_book_cover_rejects_oversized(client, fixtures_dir):
    """Oversized cover upload returns 413 per spec §6 / §9."""
    from server.config import MAX_COVER_BYTES
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    too_big = b"\xff\xd8\xff\xe0" + b"x" * (MAX_COVER_BYTES + 1)
    r = client.post(
        f"/api/books/{book['id']}/cover",
        files={"file": ("huge.jpg", too_big, "image/jpeg")},
    )
    assert r.status_code == 413


def test_put_book_cover_switches_source(client, fixtures_dir):
    """PUT cover {source: 'openlibrary'} flips active to that source.
    Requires the candidate file to exist on disk first."""
    from server import library
    from server.config import library_dir

    with open(fixtures_dir / "tiny.epub", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.epub", f, "application/epub+zip")}).json()
    book_id = book["id"]
    book_dir = library_dir() / book_id

    # Pre-populate an OL candidate
    library.save_cover_candidate(book_dir, "openlibrary", b"\xff\xd8\xff\xe0ol-bytes")

    r = client.put(f"/api/books/{book_id}/cover", json={"source": "openlibrary"})
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == "openlibrary"
    assert "openlibrary" in body["available"]


# ───── quotes ─────


def test_post_quote_201_returns_row(client, fixtures_dir):
    user = client.post("/api/users", json={"name": "Quoter"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.post(
        f"/api/users/{user['id']}/quotes",
        json={"book_id": book["id"], "paragraph_idx": 0, "text": "hi", "note": "n"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["text"] == "hi"
    assert body["note"] == "n"
    assert body["paragraph_idx"] == 0


def test_post_quote_empty_text_400(client, fixtures_dir):
    user = client.post("/api/users", json={"name": "Q2"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.post(
        f"/api/users/{user['id']}/quotes",
        json={"book_id": book["id"], "paragraph_idx": 0, "text": "", "note": None},
    )
    assert r.status_code == 400


def test_get_quotes_requires_book_id(client, fixtures_dir):
    user = client.post("/api/users", json={"name": "Q3"}).json()
    r = client.get(f"/api/users/{user['id']}/quotes")
    assert r.status_code == 400


def test_get_quotes_for_book(client, fixtures_dir):
    user = client.post("/api/users", json={"name": "Q4"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    client.post(
        f"/api/users/{user['id']}/quotes",
        json={"book_id": book["id"], "paragraph_idx": 0, "text": "a", "note": None},
    )
    client.post(
        f"/api/users/{user['id']}/quotes",
        json={"book_id": book["id"], "paragraph_idx": 1, "text": "b", "note": None},
    )
    listed = client.get(f"/api/users/{user['id']}/quotes?book_id={book['id']}").json()
    assert len(listed) == 2
    assert [q["text"] for q in listed] == ["a", "b"]


def test_delete_quote_204(client, fixtures_dir):
    user = client.post("/api/users", json={"name": "Q5"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    q = client.post(
        f"/api/users/{user['id']}/quotes",
        json={"book_id": book["id"], "paragraph_idx": 0, "text": "x", "note": None},
    ).json()
    r = client.delete(f"/api/users/{user['id']}/quotes/{q['id']}")
    assert r.status_code == 204
    # Now empty
    listed = client.get(f"/api/users/{user['id']}/quotes?book_id={book['id']}").json()
    assert listed == []


def test_delete_other_user_quote_404(client, fixtures_dir):
    u1 = client.post("/api/users", json={"name": "Alice2"}).json()
    u2 = client.post("/api/users", json={"name": "Bob2"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    q = client.post(
        f"/api/users/{u1['id']}/quotes",
        json={"book_id": book["id"], "paragraph_idx": 0, "text": "alice's", "note": None},
    ).json()
    r = client.delete(f"/api/users/{u2['id']}/quotes/{q['id']}")
    assert r.status_code == 404


def test_export_returns_markdown_with_attachment_header(client, fixtures_dir):
    user = client.post("/api/users", json={"name": "QExp"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    client.post(
        f"/api/users/{user['id']}/quotes",
        json={"book_id": book["id"], "paragraph_idx": 0, "text": "hello", "note": None},
    )
    r = client.get(f"/api/users/{user['id']}/quotes/{book['id']}/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers.get("content-disposition", "").lower()
    assert ".md" in r.headers["content-disposition"]
    assert "> hello" in r.text


def test_export_with_no_quotes_404(client, fixtures_dir):
    user = client.post("/api/users", json={"name": "QEmpty"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.get(f"/api/users/{user['id']}/quotes/{book['id']}/export")
    assert r.status_code == 404


def test_progress_total_seconds_round_trip(client, fixtures_dir):
    user = client.post("/api/users", json={"name": "RTAPI"}).json()
    with open(fixtures_dir / "tiny.txt", "rb") as f:
        book = client.post("/api/books", files={"file": ("tiny.txt", f, "text/plain")}).json()
    r = client.put(
        f"/api/users/{user['id']}/progress/{book['id']}",
        json={"paragraph_idx": 0, "char_offset": 0, "seconds_delta": 15},
    )
    assert r.status_code == 200
    p = client.get(f"/api/users/{user['id']}/progress/{book['id']}").json()
    assert p["total_seconds"] == 15
    listed = client.get(f"/api/books?user_id={user['id']}").json()
    assert listed[0]["progress"]["total_seconds"] == 15


def test_prefs_patch_show_images(client):
    user = client.post("/api/users", json={"name": "Imogen"}).json()
    p = client.get(f"/api/users/{user['id']}/prefs").json()
    assert p["show_images"] == 1
    p2 = client.patch(
        f"/api/users/{user['id']}/prefs", json={"show_images": False}
    ).json()
    assert p2["show_images"] == 0


def test_book_image_path_blocks_traversal(client, tmp_path):
    from server import library
    # Escaping the images dir returns None, never a real path.
    assert library.image_path("somebook", "../../etc/passwd") is None
    assert library.image_path("somebook", "missing.png") is None


def test_book_image_endpoint_serves_bytes(client):
    from server.config import library_dir

    # Stage a book dir with one image (no real upload needed).
    book_id = "imgbook"
    images_dir = library_dir() / book_id / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "0000.png").write_bytes(b"\x89PNG\r\n\x1a\nDATA")

    r = client.get(f"/api/books/{book_id}/images/0000.png")
    assert r.status_code == 200
    assert r.content == b"\x89PNG\r\n\x1a\nDATA"

    missing = client.get(f"/api/books/{book_id}/images/nope.png")
    assert missing.status_code == 404


def test_book_image_endpoint_security_headers(client):
    """Image responses must carry CSP sandbox and X-Content-Type-Options headers
    so that a crafted SVG cannot execute script on direct navigation (FIX 1)."""
    from server.config import library_dir

    book_id = "secimgbook"
    images_dir = library_dir() / book_id / "images"
    images_dir.mkdir(parents=True)
    (images_dir / "0000.svg").write_bytes(
        b'<svg xmlns="http://www.w3.org/2000/svg"><circle r="10"/></svg>'
    )

    r = client.get(f"/api/books/{book_id}/images/0000.svg")
    assert r.status_code == 200
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_fonts_catalog_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from server.app import create_app
    c = TestClient(create_app())
    r = c.get("/api/fonts/catalog")
    assert r.status_code == 200
    body = r.json()
    assert {"bundled", "families"} <= set(body)
    assert any(b["key"] == "serif" for b in body["bundled"])


def test_fonts_ensure_rejects_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from server.app import create_app
    c = TestClient(create_app())
    r = c.post("/api/fonts/ensure", json={"family": "Not A Font 9000"})
    assert r.status_code == 400


def test_fonts_file_404_on_bad_slug(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from server.app import create_app
    c = TestClient(create_app())
    assert c.get("/api/fonts/file/nope/0.woff2").status_code == 404


def test_fonts_delete_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from server.app import create_app
    from server import fonts
    c = TestClient(create_app())
    d = fonts.fonts_cache_dir() / "merriweather"
    d.mkdir(parents=True)
    (d / "0.woff2").write_bytes(b"x")
    assert c.delete("/api/fonts/merriweather").status_code == 204
    assert not d.exists()
    # idempotent: deleting again is still 204
    assert c.delete("/api/fonts/merriweather").status_code == 204


@pytest.mark.parametrize("bad_slug", ["%2E%2E", "Merriweather", "foo.bar", "never-here"])
def test_fonts_delete_endpoint_rejects_bad_slugs(tmp_path, monkeypatch, bad_slug):
    # The endpoint is an idempotent no-op for invalid/traversal/unknown slugs:
    # it must return 204 (never 400/500) and never delete anything. A sentinel
    # OUTSIDE the cache dir must survive. Belt-and-suspenders at the HTTP layer
    # over delete_cached()'s unit-level traversal guard.
    monkeypatch.setenv("READER_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from server.app import create_app
    from server import fonts
    c = TestClient(create_app())
    outside = fonts.fonts_cache_dir().parent.parent / "outside_secret"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("keep")
    assert c.delete(f"/api/fonts/{bad_slug}").status_code == 204
    assert (outside / "keep.txt").exists()
