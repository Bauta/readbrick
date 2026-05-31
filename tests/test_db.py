"""Schema migration tests."""
import sqlite3

from server.db import connect, init_db


def test_init_db_is_idempotent():
    """Running init_db twice in a row must not error."""
    init_db()
    init_db()


def test_new_columns_present_after_migration():
    init_db()
    with connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(books)").fetchall()}
    expected = {
        "description", "published_year", "isbn",
        "genre", "word_count", "metadata_source",
        "cover_active",
    }
    assert expected <= cols, f"missing: {expected - cols}"


def test_migration_preserves_existing_rows():
    """Pre-existing rows survive the migration and read back with NULLs for new columns."""
    init_db()
    with connect() as c:
        c.execute(
            "INSERT INTO books (id, title, format, paragraph_count, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("preexisting-id", "Old Book", "txt", 5, 1700000000),
        )
    init_db()  # second migration pass
    with connect() as c:
        row = c.execute(
            "SELECT id, title, description, published_year, word_count, metadata_source "
            "FROM books WHERE id = ?",
            ("preexisting-id",),
        ).fetchone()
    assert row["title"] == "Old Book"
    assert row["description"] is None
    assert row["published_year"] is None
    assert row["word_count"] is None
    assert row["metadata_source"] is None


def test_quotes_table_present_after_migration():
    init_db()
    with connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(quotes)").fetchall()}
    expected = {"id", "user_id", "book_id", "paragraph_idx", "text", "note", "created_at"}
    assert expected <= cols, f"missing: {expected - cols}"


def test_quotes_index_present():
    init_db()
    with connect() as c:
        indexes = {r[1] for r in c.execute("PRAGMA index_list(quotes)").fetchall()}
    assert "idx_quotes_user_book" in indexes


def test_progress_total_seconds_present_after_migration():
    init_db()
    with connect() as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(progress)").fetchall()}
    assert "total_seconds" in cols
