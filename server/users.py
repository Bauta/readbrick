from typing import Optional

from .db import connect, now


def list_users() -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT id, name, created_at FROM users ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def create_user(name: str) -> dict:
    name = name.strip()
    if not name:
        raise ValueError("name is required")
    if len(name) > 64:
        raise ValueError("name too long")
    with connect() as c:
        cur = c.execute(
            "INSERT INTO users (name, created_at) VALUES (?, ?)", (name, now())
        )
        uid = cur.lastrowid
        c.execute(
            "INSERT INTO prefs (user_id) VALUES (?)", (uid,)
        )
        row = c.execute(
            "SELECT id, name, created_at FROM users WHERE id = ?", (uid,)
        ).fetchone()
        return dict(row)


def delete_user(user_id: int) -> None:
    with connect() as c:
        c.execute("DELETE FROM users WHERE id = ?", (user_id,))


def get_prefs(user_id: int) -> dict:
    with connect() as c:
        row = c.execute("SELECT * FROM prefs WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            c.execute("INSERT INTO prefs (user_id) VALUES (?)", (user_id,))
            row = c.execute("SELECT * FROM prefs WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row)


_PREF_FIELDS = {"voice_id", "speed", "font_size", "line_height", "theme", "font_family"}


def update_prefs(user_id: int, patch: dict) -> dict:
    fields = {k: v for k, v in patch.items() if k in _PREF_FIELDS}
    if not fields:
        return get_prefs(user_id)
    get_prefs(user_id)
    with connect() as c:
        sets = ", ".join(f"{k} = ?" for k in fields)
        c.execute(
            f"UPDATE prefs SET {sets} WHERE user_id = ?",
            (*fields.values(), user_id),
        )
    return get_prefs(user_id)


def get_progress(user_id: int, book_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute(
            "SELECT paragraph_idx, char_offset, last_read_at, total_seconds FROM progress WHERE user_id = ? AND book_id = ?",
            (user_id, book_id),
        ).fetchone()
        return dict(row) if row else None


def set_progress(
    user_id: int,
    book_id: str,
    paragraph_idx: int,
    char_offset: int = 0,
    seconds_delta: int = 0,
) -> dict:
    delta = max(0, int(seconds_delta) if seconds_delta else 0)
    with connect() as c:
        c.execute(
            """
            INSERT INTO progress (user_id, book_id, paragraph_idx, char_offset, last_read_at, total_seconds)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, book_id) DO UPDATE SET
              paragraph_idx = excluded.paragraph_idx,
              char_offset = excluded.char_offset,
              last_read_at = excluded.last_read_at,
              total_seconds = total_seconds + ?
            """,
            (user_id, book_id, paragraph_idx, char_offset, now(), delta, delta),
        )
    return get_progress(user_id, book_id) or {}


def progress_for_books(user_id: int) -> dict[str, dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT book_id, paragraph_idx, char_offset, last_read_at, total_seconds FROM progress WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return {r["book_id"]: dict(r) for r in rows}
