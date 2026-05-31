"""Quotes module: per-user saved highlights from books, optional notes,
and a Markdown export shaped for Obsidian (or any vault tool).

Public functions: create, list_for_book, delete, render_export.
The latter two are added in Tasks 3 and 4.
"""
from __future__ import annotations

import re
from typing import Optional

from .db import connect, now


MAX_TEXT_LEN = 5000
MAX_NOTE_LEN = 2000


def create(
    user_id: int,
    book_id: str,
    paragraph_idx: int,
    text: str,
    note: Optional[str],
) -> dict:
    """Validate, INSERT, return the created row."""
    text = (text or "").strip()
    if not text:
        raise ValueError("quote text required")
    if len(text) > MAX_TEXT_LEN:
        raise ValueError(f"quote text exceeds {MAX_TEXT_LEN} chars")
    cleaned_note: Optional[str] = None
    if note is not None:
        n = note.strip()
        if len(n) > MAX_NOTE_LEN:
            raise ValueError(f"quote note exceeds {MAX_NOTE_LEN} chars")
        cleaned_note = n or None
    with connect() as c:
        cur = c.execute(
            """
            INSERT INTO quotes (user_id, book_id, paragraph_idx, text, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, book_id, int(paragraph_idx), text, cleaned_note, now()),
        )
        return _row(cur.lastrowid)


def list_for_book(user_id: int, book_id: str) -> list[dict]:
    """Return quotes for (user, book), sorted by (paragraph_idx, created_at)."""
    with connect() as c:
        rows = c.execute(
            """
            SELECT id, user_id, book_id, paragraph_idx, text, note, created_at
            FROM quotes
            WHERE user_id = ? AND book_id = ?
            ORDER BY paragraph_idx ASC, created_at ASC
            """,
            (user_id, book_id),
        ).fetchall()
        return [dict(r) for r in rows]


def delete(user_id: int, quote_id: int) -> bool:
    """Delete a quote owned by user_id. Returns True if deleted, False
    if not found or not owned by this user. No information leak about
    other users' quotes."""
    with connect() as c:
        cur = c.execute(
            "DELETE FROM quotes WHERE id = ? AND user_id = ?",
            (int(quote_id), int(user_id)),
        )
        return cur.rowcount > 0


def render_export(user_id: int, book_id: str) -> tuple[str, str]:
    """Build the Markdown export. Returns (markdown_text, filename).
    Raises ValueError if no quotes exist for this (user, book)."""
    import datetime as _dt

    rows = list_for_book(user_id, book_id)
    if not rows:
        raise ValueError("no quotes to export")

    # Fetch book metadata
    with connect() as c:
        book = c.execute(
            "SELECT title, author, published_year FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
    title = (book["title"] if book else book_id) or book_id
    author = book["author"] if book else None
    year = book["published_year"] if book else None

    today = _dt.date.today().isoformat()

    lines: list[str] = [f"# {title}", ""]
    if author:
        lines.append(f"**Author:** {author}")
    if year:
        lines.append(f"**Year:** {year}")
    lines.append("**Source:** Reader (https://github.com/Bauta/readbrick)")
    lines.append(f"**Exported:** {today}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for q in rows:
        # Blockquote every line of the quote text
        for line in q["text"].splitlines() or [""]:
            lines.append(f"> {line}")
        lines.append("")
        if q["note"]:
            lines.append(f"*{q['note']}*")
            lines.append("")
        lines.append("---")
        lines.append("")

    md = "\n".join(lines)
    filename = _slugify_title(title) + ".md"
    return md, filename


_FILENAME_BAD = re.compile(r"[^\w\s-]", flags=re.UNICODE)
_FILENAME_WS = re.compile(r"\s+")


def _slugify_title(title: str) -> str:
    """Strip filesystem-unfriendly characters from a title. Keeps unicode
    letters (so accented characters survive), strips slashes/colons/question
    marks/etc., collapses whitespace to single spaces, caps length."""
    cleaned = _FILENAME_BAD.sub("", title or "").strip()
    cleaned = _FILENAME_WS.sub(" ", cleaned)
    if not cleaned:
        cleaned = "quotes"
    return cleaned[:120]


def _row(quote_id: int) -> dict:
    with connect() as c:
        row = c.execute(
            """
            SELECT id, user_id, book_id, paragraph_idx, text, note, created_at
            FROM quotes WHERE id = ?
            """,
            (quote_id,),
        ).fetchone()
        return dict(row) if row else None
