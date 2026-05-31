import pytest


def test_create_and_list_user():
    from server import users
    from server.db import init_db

    init_db()
    u = users.create_user("Alice")
    assert u["name"] == "Alice"
    assert u["id"] > 0

    rows = users.list_users()
    assert len(rows) == 1
    assert rows[0]["name"] == "Alice"


def test_duplicate_user_raises():
    from server import users
    from server.db import init_db

    init_db()
    users.create_user("Bob")
    with pytest.raises(Exception):  # sqlite UNIQUE constraint
        users.create_user("Bob")


def test_empty_name_rejected():
    from server import users
    from server.db import init_db

    init_db()
    with pytest.raises(ValueError):
        users.create_user("")
    with pytest.raises(ValueError):
        users.create_user("   ")


def test_prefs_defaults_and_update():
    from server import users
    from server.db import init_db

    init_db()
    u = users.create_user("Carol")
    prefs = users.get_prefs(u["id"])
    assert prefs["speed"] == 0.9
    assert prefs["font_size"] == 18
    assert prefs["theme"] == "auto"

    updated = users.update_prefs(u["id"], {"speed": 1.5, "font_size": 22, "ignored": "x"})
    assert updated["speed"] == 1.5
    assert updated["font_size"] == 22
    # unknown field ignored
    assert "ignored" not in updated


def test_progress_save_and_get():
    from server import users
    from server.db import init_db

    init_db()
    u = users.create_user("Dave")
    # need a book row to satisfy FK
    from server.db import connect, now

    with connect() as c:
        c.execute(
            "INSERT INTO books (id, title, format, paragraph_count, added_at) VALUES (?, ?, ?, ?, ?)",
            ("bk1", "Book", "txt", 100, now()),
        )

    assert users.get_progress(u["id"], "bk1") is None
    users.set_progress(u["id"], "bk1", 42, 7)
    p = users.get_progress(u["id"], "bk1")
    assert p["paragraph_idx"] == 42
    assert p["char_offset"] == 7

    # update
    users.set_progress(u["id"], "bk1", 50)
    p = users.get_progress(u["id"], "bk1")
    assert p["paragraph_idx"] == 50


def test_delete_user_cascades():
    from server import users
    from server.db import connect, init_db, now

    init_db()
    u = users.create_user("Eve")
    with connect() as c:
        c.execute(
            "INSERT INTO books (id, title, format, paragraph_count, added_at) VALUES (?, ?, ?, ?, ?)",
            ("bk1", "Book", "txt", 100, now()),
        )
    users.set_progress(u["id"], "bk1", 5)
    users.delete_user(u["id"])
    with connect() as c:
        rows = c.execute("SELECT COUNT(*) AS n FROM progress").fetchone()
        assert rows["n"] == 0
        rows = c.execute("SELECT COUNT(*) AS n FROM prefs").fetchone()
        assert rows["n"] == 0


def _make_book_row(book_id="bk1"):
    from server.db import connect
    with connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO books (id, title, format, paragraph_count, added_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (book_id, "Test Book", "txt", 5, 1700000000),
        )


def test_set_progress_increments_total_seconds():
    from server import users
    from server.db import init_db
    init_db()
    user = users.create_user("RT-1")
    _make_book_row("bk1")
    users.set_progress(user["id"], "bk1", 0, 0, seconds_delta=30)
    p = users.get_progress(user["id"], "bk1")
    assert p["total_seconds"] == 30
    users.set_progress(user["id"], "bk1", 1, 0, seconds_delta=20)
    p = users.get_progress(user["id"], "bk1")
    assert p["total_seconds"] == 50
    users.set_progress(user["id"], "bk1", 2, 0, seconds_delta=0)
    p = users.get_progress(user["id"], "bk1")
    assert p["total_seconds"] == 50
    users.set_progress(user["id"], "bk1", 3, 0)
    p = users.get_progress(user["id"], "bk1")
    assert p["total_seconds"] == 50


def test_set_progress_negative_delta_clamped_to_zero():
    from server import users
    from server.db import init_db
    init_db()
    user = users.create_user("RT-2")
    _make_book_row("bk1")
    users.set_progress(user["id"], "bk1", 0, 0, seconds_delta=10)
    users.set_progress(user["id"], "bk1", 1, 0, seconds_delta=-5)
    p = users.get_progress(user["id"], "bk1")
    assert p["total_seconds"] == 10
