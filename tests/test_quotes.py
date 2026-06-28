"""Tests for the quotes module: create, list_for_book."""
import pytest
from pathlib import Path


def _make_user(name="Eve"):
    from server import users
    from server.db import init_db
    init_db()
    return users.create_user(name)


def _ingest(fixtures_dir, name="tiny.txt"):
    from server import library
    from server.db import init_db
    init_db()
    book = library.ingest(fixtures_dir / name, name)
    return book["id"]


# ───── create ─────


def test_create_persists_row(fixtures_dir):
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    row = quotes.create(user["id"], book_id, 1, "Once upon a time.", "remember this")
    assert row["id"] > 0
    assert row["user_id"] == user["id"]
    assert row["book_id"] == book_id
    assert row["paragraph_idx"] == 1
    assert row["text"] == "Once upon a time."
    assert row["note"] == "remember this"
    assert row["created_at"] > 0


def test_create_empty_text_raises(fixtures_dir):
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    with pytest.raises(ValueError):
        quotes.create(user["id"], book_id, 0, "", None)
    with pytest.raises(ValueError):
        quotes.create(user["id"], book_id, 0, "   ", None)


def test_create_oversized_text_raises(fixtures_dir):
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    big = "a" * 5001
    with pytest.raises(ValueError):
        quotes.create(user["id"], book_id, 0, big, None)


def test_create_oversized_note_raises(fixtures_dir):
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    big_note = "b" * 2001
    with pytest.raises(ValueError):
        quotes.create(user["id"], book_id, 0, "hello", big_note)


def test_create_empty_note_becomes_null(fixtures_dir):
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    r1 = quotes.create(user["id"], book_id, 0, "hello", "")
    r2 = quotes.create(user["id"], book_id, 0, "world", "   ")
    assert r1["note"] is None
    assert r2["note"] is None


# ───── list_for_book ─────


def test_list_for_book_ordering(fixtures_dir):
    import time
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    # Insert in scrambled order
    quotes.create(user["id"], book_id, 2, "second-paragraph quote", None)
    time.sleep(0.01)
    quotes.create(user["id"], book_id, 0, "first-A", None)
    time.sleep(0.01)
    quotes.create(user["id"], book_id, 0, "first-B", None)
    listed = quotes.list_for_book(user["id"], book_id)
    assert [q["paragraph_idx"] for q in listed] == [0, 0, 2]
    assert [q["text"] for q in listed] == ["first-A", "first-B", "second-paragraph quote"]


def test_list_for_book_empty_returns_empty_list(fixtures_dir):
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    assert quotes.list_for_book(user["id"], book_id) == []


def test_list_for_book_isolated_by_user(fixtures_dir):
    from server import quotes
    user1 = _make_user("Alice")
    user2 = _make_user("Bob")
    book_id = _ingest(fixtures_dir)
    quotes.create(user1["id"], book_id, 0, "alice quote", None)
    quotes.create(user2["id"], book_id, 0, "bob quote", None)
    a = quotes.list_for_book(user1["id"], book_id)
    b = quotes.list_for_book(user2["id"], book_id)
    assert [q["text"] for q in a] == ["alice quote"]
    assert [q["text"] for q in b] == ["bob quote"]


# ───── delete ─────


def test_delete_returns_true_when_owned(fixtures_dir):
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    q = quotes.create(user["id"], book_id, 0, "to be removed", None)
    assert quotes.delete(user["id"], q["id"]) is True
    assert quotes.list_for_book(user["id"], book_id) == []


def test_delete_returns_false_when_not_owned(fixtures_dir):
    from server import quotes
    user1 = _make_user("Alice")
    user2 = _make_user("Bob")
    book_id = _ingest(fixtures_dir)
    q = quotes.create(user1["id"], book_id, 0, "alice's", None)
    # Bob tries to delete Alice's quote
    assert quotes.delete(user2["id"], q["id"]) is False
    # Quote still there for Alice
    assert len(quotes.list_for_book(user1["id"], book_id)) == 1


def test_delete_returns_false_for_missing_id(fixtures_dir):
    from server import quotes
    user = _make_user()
    assert quotes.delete(user["id"], 99999) is False


# ───── render_export ─────


def test_render_export_format(fixtures_dir):
    """Build a multi-quote Markdown and assert structure."""
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir, "tiny.epub")  # has title + author
    quotes.create(user["id"], book_id, 0, "Once upon a time.", "first quote note")
    quotes.create(user["id"], book_id, 1, "He lived in a green valley.", None)
    md, filename = quotes.render_export(user["id"], book_id)
    # Filename
    assert filename.endswith(".md")
    # Title heading
    assert md.startswith("# ")
    # Each quote rendered as a blockquote
    assert "> Once upon a time." in md
    assert "> He lived in a green valley." in md
    # Note shows up
    assert "first quote note" in md
    # Separators between quotes
    assert md.count("\n---\n") >= 2  # one under header, at least one between quotes


def test_render_export_empty_raises(fixtures_dir):
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    with pytest.raises(ValueError):
        quotes.render_export(user["id"], book_id)


def test_render_export_filename_slugified(fixtures_dir):
    """Title with special chars gets sanitised."""
    from server import quotes
    from server.db import connect, init_db
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    # Update title to something with bad filename chars
    with connect() as c:
        c.execute(
            "UPDATE books SET title = ? WHERE id = ?",
            ("Tricky / Title: with ? chars", book_id),
        )
    quotes.create(user["id"], book_id, 0, "anything", None)
    _, filename = quotes.render_export(user["id"], book_id)
    # No slashes, colons, question marks in filename
    for bad in "/:?<>|*\\":
        assert bad not in filename
    assert filename.endswith(".md")


def test_render_export_omits_missing_author_year(fixtures_dir):
    """When author/year are NULL, the header lines are omitted."""
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir, "tiny.txt")  # tiny.txt has no author/year
    quotes.create(user["id"], book_id, 0, "hello", None)
    md, _ = quotes.render_export(user["id"], book_id)
    assert "**Author:** None" not in md
    assert "**Year:** None" not in md


def test_render_export_multiline_text_blockquoted_per_line(fixtures_dir):
    """A quote with newlines becomes a multi-line blockquote."""
    from server import quotes
    user = _make_user()
    book_id = _ingest(fixtures_dir)
    quotes.create(user["id"], book_id, 0, "line one\nline two", None)
    md, _ = quotes.render_export(user["id"], book_id)
    assert "> line one" in md
    assert "> line two" in md
