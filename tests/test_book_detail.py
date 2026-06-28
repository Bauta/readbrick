"""Tests for the book-detail module: list/set/upload covers + update metadata."""
import pytest

from pathlib import Path


def _ingest(fixtures_dir, name="tiny.epub"):
    """Helper: ingest a fixture, return its book id."""
    from server import library
    from server.db import init_db
    init_db()
    book = library.ingest(fixtures_dir / name, name)
    return book["id"]


# ───── list_covers ─────


def test_list_covers_after_epub_ingest(fixtures_dir):
    from server import book_detail
    book_id = _ingest(fixtures_dir, "tiny.epub")
    result = book_detail.list_covers(book_id)
    assert result["active"] == "epub"
    assert "epub" in result["available"]


def test_list_covers_after_txt_ingest_is_empty(fixtures_dir):
    from server import book_detail
    book_id = _ingest(fixtures_dir, "tiny.txt")
    result = book_detail.list_covers(book_id)
    assert result["active"] is None
    assert result["available"] == []


# ───── set_active_cover ─────


def test_set_active_cover_copies_file_and_updates_column(fixtures_dir):
    """Pre-populate a second candidate, then switch active to it."""
    from server import book_detail, library
    from server.config import library_dir
    from server.db import connect

    book_id = _ingest(fixtures_dir, "tiny.epub")
    book_dir = library_dir() / book_id
    # Drop a fake OL candidate in
    library.save_cover_candidate(book_dir, "openlibrary", b"fakejpg-bytes-ol")

    book_detail.set_active_cover(book_id, "openlibrary")

    active_jpg = (book_dir / "cover.jpg").read_bytes()
    candidate_jpg = (book_dir / "covers" / "openlibrary.jpg").read_bytes()
    assert active_jpg == candidate_jpg

    with connect() as c:
        row = c.execute(
            "SELECT cover_active FROM books WHERE id = ?", (book_id,)
        ).fetchone()
    assert row["cover_active"] == "openlibrary"


def test_set_active_cover_unknown_source_raises(fixtures_dir):
    from server import book_detail
    book_id = _ingest(fixtures_dir, "tiny.epub")
    with pytest.raises(ValueError):
        book_detail.set_active_cover(book_id, "myspace")


# ───── get_book reflects DB edits (regression) ─────


def test_get_book_reflects_metadata_edits(fixtures_dir):
    """Editing metadata must show on the detail page + reader (get_book), not
    only the library list. Regression: get_book read book.json while edits wrote
    the DB books row, so the detail page and reader showed stale values."""
    from server import book_detail, library
    book_id = _ingest(fixtures_dir, "tiny.epub")
    book_detail.update_metadata(book_id, {
        "title": "Edited Title",
        "author": "Edited Author",
        "description": "Edited description.",
        "published_year": 1999,
    })
    got = library.get_book(book_id)
    assert got["title"] == "Edited Title"
    assert got["author"] == "Edited Author"
    assert got["description"] == "Edited description."
    assert got["published_year"] == 1999
    assert "chapters" in got and got["chapters"]  # content (book.json) still served


def test_get_book_reflects_active_cover_change(fixtures_dir):
    """Switching the active cover updates the DB; get_book must reflect it too."""
    from server import book_detail, library
    from server.config import library_dir
    book_id = _ingest(fixtures_dir, "tiny.epub")
    library.save_cover_candidate(library_dir() / book_id, "openlibrary", b"fakejpg")
    book_detail.set_active_cover(book_id, "openlibrary")
    assert library.get_book(book_id)["cover_active"] == "openlibrary"


def test_set_active_cover_missing_file_raises(fixtures_dir):
    """Setting a valid source name whose file doesn't exist must error."""
    from server import book_detail
    book_id = _ingest(fixtures_dir, "tiny.epub")
    with pytest.raises(ValueError):
        book_detail.set_active_cover(book_id, "openlibrary")  # no file written


# ───── upload_custom_cover ─────


def test_upload_custom_cover_writes_and_activates(fixtures_dir):
    from server import book_detail
    from server.config import library_dir
    from server.db import connect

    book_id = _ingest(fixtures_dir, "tiny.epub")
    book_dir = library_dir() / book_id

    # Tiny valid JPEG header bytes - content doesn't have to render
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"x" * 100
    book_detail.upload_custom_cover(book_id, fake_jpeg, "image/jpeg")

    assert (book_dir / "covers" / "custom.jpg").read_bytes() == fake_jpeg
    assert (book_dir / "cover.jpg").read_bytes() == fake_jpeg

    with connect() as c:
        row = c.execute(
            "SELECT cover_active FROM books WHERE id = ?", (book_id,)
        ).fetchone()
    assert row["cover_active"] == "custom"


def test_upload_custom_cover_rejects_non_image(fixtures_dir):
    from server import book_detail
    book_id = _ingest(fixtures_dir, "tiny.epub")
    with pytest.raises(ValueError):
        book_detail.upload_custom_cover(book_id, b"hello world", "text/plain")


# ───── update_metadata ─────


def test_update_metadata_changes_fields(fixtures_dir):
    from server import book_detail
    from server.db import connect

    book_id = _ingest(fixtures_dir, "tiny.epub")
    updated = book_detail.update_metadata(book_id, {
        "title": "New Title",
        "author": "New Author",
        "published_year": 2020,
        "description": "A new description.",
    })
    assert updated["title"] == "New Title"
    assert updated["author"] == "New Author"
    assert updated["published_year"] == 2020
    assert updated["description"] == "A new description."

    with connect() as c:
        row = dict(c.execute(
            "SELECT title, author, published_year, description FROM books WHERE id = ?",
            (book_id,),
        ).fetchone())
    assert row["title"] == "New Title"


def test_update_metadata_whitelists_unknown_keys(fixtures_dir):
    """Unknown keys must be silently dropped, not written."""
    from server import book_detail
    from server.db import connect

    book_id = _ingest(fixtures_dir, "tiny.epub")
    book_detail.update_metadata(book_id, {
        "title": "Allowed",
        "paragraph_count": 9999,  # not in whitelist
    })
    with connect() as c:
        row = dict(c.execute(
            "SELECT title, paragraph_count FROM books WHERE id = ?",
            (book_id,),
        ).fetchone())
    assert row["title"] == "Allowed"
    assert row["paragraph_count"] != 9999


def test_update_metadata_empty_author_becomes_null(fixtures_dir):
    from server import book_detail
    from server.db import connect

    book_id = _ingest(fixtures_dir, "tiny.epub")
    book_detail.update_metadata(book_id, {"author": ""})
    with connect() as c:
        row = c.execute(
            "SELECT author FROM books WHERE id = ?", (book_id,)
        ).fetchone()
    assert row["author"] is None


def test_update_metadata_rejects_empty_title(fixtures_dir):
    from server import book_detail
    book_id = _ingest(fixtures_dir, "tiny.epub")
    with pytest.raises(ValueError):
        book_detail.update_metadata(book_id, {"title": "   "})


def test_update_metadata_rejects_bad_year(fixtures_dir):
    from server import book_detail
    book_id = _ingest(fixtures_dir, "tiny.epub")
    with pytest.raises(ValueError):
        book_detail.update_metadata(book_id, {"published_year": 9999})
    with pytest.raises(ValueError):
        book_detail.update_metadata(book_id, {"published_year": 0})


# ───── refresh_metadata ─────


def test_refresh_does_nothing_when_enrich_returns_none(fixtures_dir):
    """Default autouse stub returns None → refresh fills 0 fields."""
    from server import book_detail
    book_id = _ingest(fixtures_dir, "tiny.txt")  # txt has NULL metadata fields

    result = book_detail.refresh_metadata(book_id)
    assert result["fields_filled"] == 0
    assert result["new_cover_sources"] == []
    assert result["book"]["description"] is None


def test_refresh_fills_only_null_fields(fixtures_dir, monkeypatch):
    """User edits are preserved; only NULL fields refill."""
    from server import book_detail

    book_id = _ingest(fixtures_dir, "tiny.txt")
    # User has manually set the description
    book_detail.update_metadata(book_id, {"description": "user-edit"})

    monkeypatch.setattr(book_detail.md, "enrich", lambda *a, **kw: {
        "metadata_source": "openlibrary",
        "description": "from openlibrary",
        "published_year": 2018,
        "isbn": None,
        "genre": None,
        "cover_url": None,
    })

    result = book_detail.refresh_metadata(book_id)
    assert result["book"]["description"] == "user-edit"   # preserved
    assert result["book"]["published_year"] == 2018       # filled
    assert result["fields_filled"] == 1


def test_refresh_downloads_new_cover_candidate(fixtures_dir, monkeypatch):
    """If enrich returns a cover_url and that source's file doesn't exist,
    a candidate gets downloaded."""
    from server import book_detail
    from server.config import library_dir

    book_id = _ingest(fixtures_dir, "tiny.txt")  # no covers/

    # Stub enrich + _download_cover (download writes the file)
    monkeypatch.setattr(book_detail.md, "enrich", lambda *a, **kw: {
        "metadata_source": "openlibrary",
        "description": None,
        "published_year": None,
        "isbn": None,
        "genre": None,
        "cover_url": "https://example/cover.jpg",
    })

    def fake_download(url, source, book_dir):
        from server import library
        library.save_cover_candidate(book_dir, source, b"\xff\xd8\xff\xe0fake")
        return True

    monkeypatch.setattr(book_detail.library, "_download_cover", fake_download)

    result = book_detail.refresh_metadata(book_id)
    assert "openlibrary" in result["new_cover_sources"]
    assert (library_dir() / book_id / "covers" / "openlibrary.jpg").exists()


def test_set_active_cover_rejects_path_traversal(fixtures_dir):
    """A book_id with .. must not allow writing outside the library dir."""
    from server import book_detail
    with pytest.raises(ValueError):
        book_detail.set_active_cover("../../../tmp/evil", "epub")


def test_upload_custom_cover_rejects_path_traversal(fixtures_dir):
    from server import book_detail
    with pytest.raises(ValueError):
        book_detail.upload_custom_cover("../../../tmp/evil", b"\xff\xd8\xff\xe0", "image/jpeg")
