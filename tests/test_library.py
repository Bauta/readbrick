"""Library ingest tests for EPUB, PDF, TXT."""
from __future__ import annotations

from pathlib import Path


def test_ingest_epub(fixtures_dir: Path):
    from server import library
    from server.db import init_db

    init_db()
    book = library.ingest(fixtures_dir / "tiny.epub", "tiny.epub")
    assert book["title"] == "Tiny English Tale"
    assert book["author"] == "Test Author"
    assert book["language"] == "en"
    assert book["format"] == "epub"
    assert book["paragraph_count"] >= 3

    full = library.get_book(book["id"])
    paragraphs = [p for ch in full["chapters"] for p in ch["paragraphs"]]
    # idx must be contiguous and start at 0
    assert [p["idx"] for p in paragraphs] == list(range(len(paragraphs)))
    texts = " ".join(p["text"] for p in paragraphs)
    assert "first paragraph" in texts
    assert "third paragraph" in texts


def test_ingest_pdf(fixtures_dir: Path):
    from server import library
    from server.db import init_db

    init_db()
    book = library.ingest(fixtures_dir / "tiny.pdf", "tiny.pdf")
    assert book["format"] == "pdf"
    assert book["paragraph_count"] >= 1

    full = library.get_book(book["id"])
    paragraphs = [p for ch in full["chapters"] for p in ch["paragraphs"]]
    texts = " ".join(p["text"] for p in paragraphs)
    assert "test-PDF" in texts
    assert "Second page" in texts


def test_ingest_txt(fixtures_dir: Path):
    from server import library
    from server.db import init_db

    init_db()
    book = library.ingest(fixtures_dir / "tiny.txt", "tiny.txt")
    assert book["format"] == "txt"
    assert book["paragraph_count"] == 4
    full = library.get_book(book["id"])
    paragraphs = [p for ch in full["chapters"] for p in ch["paragraphs"]]
    assert "Once upon a time" in paragraphs[0]["text"]
    assert "never would forget" in paragraphs[-1]["text"]


def test_ingest_unsupported_extension(fixtures_dir: Path, tmp_path: Path):
    from server import library
    from server.db import init_db
    import pytest

    init_db()
    bogus = tmp_path / "thing.xyz"
    bogus.write_text("hi")
    with pytest.raises(ValueError):
        library.ingest(bogus, "thing.xyz")


def test_delete_book(fixtures_dir: Path):
    from server import library
    from server.db import init_db

    init_db()
    book = library.ingest(fixtures_dir / "tiny.txt", "tiny.txt")
    assert library.delete_book(book["id"]) is True
    assert library.get_book(book["id"]) is None
    assert library.delete_book(book["id"]) is False


def test_ingest_computes_word_count(fixtures_dir: Path):
    """word_count is sum of words across all paragraphs."""
    from server import library
    from server.db import init_db

    init_db()
    book = library.ingest(fixtures_dir / "tiny.txt", "tiny.txt")
    # tiny.txt content is known; check word_count exists and is a positive int
    assert isinstance(book.get("word_count"), int)
    assert book["word_count"] > 0


def test_epub_chapters_use_toc_titles_and_drop_frontmatter(fixtures_dir: Path, tmp_path):
    """Chapters take their names from the EPUB TOC (not the first/generic heading)
    and front-matter is dropped. Regression for the Jocko book, whose chapter
    files each carry "SECTION N" before the real title and whose front-matter
    produced empty/junk chapters."""
    from server import library
    parsed = library.parse_epub(fixtures_dir / "two-heading-nav.epub", tmp_path)
    titles = [c["title"] for c in parsed["chapters"]]
    # Real headings win over the generic "SECTION 1" label (-> "Foundations");
    # a file with only a generic heading falls back to its TOC name
    # ("Core Tenets"); front-matter is dropped.
    assert titles == ["Introduction", "Foundations", "Core Tenets"]
    assert "" not in titles
    assert not any(t.upper().startswith(("SECTION ", "PART ")) for t in titles)
    assert not any("Contents" in t or "Index" in t for t in titles)
    # Global paragraph idx stays contiguous from 0 after dropping front-matter.
    idxs = [p["idx"] for c in parsed["chapters"] for p in c["paragraphs"]]
    assert idxs == list(range(len(idxs)))


def test_ingest_extracts_isbn_from_epub(fixtures_dir: Path):
    """EPUB DC:identifier with ISBN scheme should populate book['isbn'] (or None
    if absent in the fixture). Today's fixture has no ISBN, so we expect None."""
    from server import library
    from server.db import init_db

    init_db()
    book = library.ingest(fixtures_dir / "tiny.epub", "tiny.epub")
    # Fixture has no ISBN — assert None, not missing
    assert "isbn" in book
    assert book["isbn"] is None


def test_ingest_inserts_new_metadata_columns(fixtures_dir: Path):
    """After ingest, the DB row should have metadata_source set (likely 'none'
    in the test env with no network) and word_count populated."""
    from server import library
    from server.db import connect, init_db

    init_db()
    book = library.ingest(fixtures_dir / "tiny.txt", "tiny.txt")
    with connect() as c:
        row = dict(c.execute(
            "SELECT word_count, metadata_source, description, "
            "published_year, isbn, genre "
            "FROM books WHERE id = ?",
            (book["id"],),
        ).fetchone())

    assert isinstance(row["word_count"], int) and row["word_count"] > 0
    assert row["metadata_source"] in ("openlibrary", "google_books", "none")
    # Either NULL (no network/no hit) or a string (lookup landed something).
    assert row["description"] is None or isinstance(row["description"], str)


def test_ingest_epub_writes_candidate_and_active_cover(fixtures_dir: Path):
    """EPUB ingest writes covers/epub.jpg AND copies it to cover.jpg AND
    sets cover_active='epub' on the row."""
    from pathlib import Path as _Path
    from server import library
    from server.db import connect, init_db
    from server.config import library_dir

    init_db()
    book = library.ingest(fixtures_dir / "tiny.epub", "tiny.epub")
    book_dir = library_dir() / book["id"]

    candidate = book_dir / "covers" / "epub.jpg"
    active = book_dir / "cover.jpg"

    assert candidate.exists(), "covers/epub.jpg should be written"
    assert active.exists(), "cover.jpg (active) should be written"
    assert candidate.read_bytes() == active.read_bytes()

    with connect() as c:
        row = dict(c.execute(
            "SELECT cover_active FROM books WHERE id = ?", (book["id"],)
        ).fetchone())
    assert row["cover_active"] == "epub"


def test_ingest_pdf_writes_page_1_candidate(fixtures_dir: Path):
    """PDF ingest renders page 1 to covers/pdf.jpg and sets it active."""
    from server import library
    from server.db import connect, init_db
    from server.config import library_dir

    init_db()
    book = library.ingest(fixtures_dir / "tiny.pdf", "tiny.pdf")
    book_dir = library_dir() / book["id"]

    candidate = book_dir / "covers" / "pdf.jpg"
    active = book_dir / "cover.jpg"

    assert candidate.exists()
    assert active.exists()
    assert candidate.read_bytes() == active.read_bytes()

    with connect() as c:
        row = dict(c.execute(
            "SELECT cover_active FROM books WHERE id = ?", (book["id"],)
        ).fetchone())
    assert row["cover_active"] == "pdf"


def test_ingest_txt_has_no_cover(fixtures_dir: Path):
    """TXT has no embedded cover source. covers/ may or may not exist; cover_active is NULL."""
    from server import library
    from server.db import connect, init_db
    from server.config import library_dir

    init_db()
    book = library.ingest(fixtures_dir / "tiny.txt", "tiny.txt")
    book_dir = library_dir() / book["id"]

    assert not (book_dir / "cover.jpg").exists()

    with connect() as c:
        row = dict(c.execute(
            "SELECT cover_active FROM books WHERE id = ?", (book["id"],)
        ).fetchone())
    assert row["cover_active"] is None
