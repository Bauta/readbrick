"""Per-book actions for the detail page: list/set covers, upload custom
cover, update editable metadata fields.

Refresh-metadata (also part of this module) lives in a separate task
because it interacts with the network and the autouse test stub.
"""
from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path

from . import library
from . import metadata as md
from .config import MAX_COVER_BYTES, library_dir
from .db import connect


def _safe_book_dir(book_id: str) -> Path:
    """Return book_dir for the given id, ensuring the resolved path stays
    inside the library directory. Defends against `..` traversal in the
    route parameter."""
    root = library_dir().resolve()
    d = (library_dir() / book_id).resolve()
    if not str(d).startswith(str(root) + "/") and str(d) != str(root):
        raise ValueError(f"invalid book_id: {book_id}")
    return d


# ───── covers ─────


_COVER_SOURCES = ("epub", "pdf", "openlibrary", "google_books", "custom")


def list_covers(book_id: str) -> dict:
    """Return { active, available } for a book. `available` is the
    lexicographically-sorted list of source names whose covers/<source>.jpg
    file exists on disk."""
    book_dir = _safe_book_dir(book_id)
    covers_dir = book_dir / "covers"
    available: list[str] = []
    if covers_dir.is_dir():
        for source in _COVER_SOURCES:
            if (covers_dir / f"{source}.jpg").exists():
                available.append(source)
    available.sort()
    with connect() as c:
        row = c.execute(
            "SELECT cover_active FROM books WHERE id = ?", (book_id,)
        ).fetchone()
    active = row["cover_active"] if row else None
    return {"active": active, "available": available}


def set_active_cover(book_id: str, source: str) -> dict:
    """Copy covers/<source>.jpg to cover.jpg and persist cover_active.
    Raises ValueError if source is unknown or its file is missing."""
    if source not in _COVER_SOURCES:
        raise ValueError(f"invalid cover source: {source}")
    book_dir = _safe_book_dir(book_id)
    candidate = book_dir / "covers" / f"{source}.jpg"
    if not candidate.exists():
        raise ValueError(f"cover source '{source}' not available for this book")
    shutil.copyfile(candidate, book_dir / "cover.jpg")
    with connect() as c:
        c.execute(
            "UPDATE books SET cover_active = ? WHERE id = ?",
            (source, book_id),
        )
    return list_covers(book_id)


def upload_custom_cover(book_id: str, content: bytes, content_type: str) -> dict:
    """Validate, save as covers/custom.jpg, set as active. Returns the
    new list_covers() dict."""
    if not (content_type or "").lower().startswith("image/"):
        raise ValueError(f"unsupported content type: {content_type}")
    if len(content) > MAX_COVER_BYTES:
        raise ValueError(f"cover exceeds max size of {MAX_COVER_BYTES} bytes")
    book_dir = _safe_book_dir(book_id)
    library.save_cover_candidate(book_dir, "custom", content)
    return set_active_cover(book_id, "custom")


# ───── editable metadata ─────


_EDITABLE_FIELDS = {"title", "author", "published_year", "description"}


def update_metadata(book_id: str, patch: dict) -> dict:
    """Apply a partial update to the books row. Whitelisted fields only;
    unknown keys silently dropped. Empty strings on optional fields
    become NULL. Title required. Year must be 1..(this year + 1)."""
    clean: dict = {}
    for key in _EDITABLE_FIELDS:
        if key not in patch:
            continue
        clean[key] = patch[key]

    if "title" in clean:
        title = (clean["title"] or "").strip()
        if not title:
            raise ValueError("title required")
        clean["title"] = title

    if "author" in clean:
        author = (clean["author"] or "").strip()
        clean["author"] = author or None

    if "description" in clean:
        desc = (clean["description"] or "").strip()
        clean["description"] = desc or None

    if "published_year" in clean:
        year = clean["published_year"]
        if year is None or year == "":
            clean["published_year"] = None
        else:
            try:
                year = int(year)
            except (TypeError, ValueError):
                raise ValueError("published_year must be an integer")
            now_year = _dt.datetime.now().year
            if not (1 <= year <= now_year + 1):
                raise ValueError(f"published_year out of range (1..{now_year + 1})")
            clean["published_year"] = year

    if not clean:
        return library._book_row(book_id)

    sets = ", ".join(f"{k} = ?" for k in clean)
    values = list(clean.values()) + [book_id]
    with connect() as c:
        c.execute(f"UPDATE books SET {sets} WHERE id = ?", values)
    return library._book_row(book_id)


# ───── refresh_metadata ─────


_REFILLABLE_FIELDS = ("description", "published_year", "isbn", "genre")


def refresh_metadata(book_id: str) -> dict:
    """Re-run the enrichment cascade for an existing book. Refills only
    NULL fields (preserves user edits). Downloads new cover candidates
    when found. Returns { book, fields_filled, new_cover_sources }."""
    row = library._book_row(book_id)
    if not row:
        raise ValueError(f"book not found: {book_id}")

    enriched = md.enrich(
        row["title"], row.get("author"), row.get("language"), row.get("isbn")
    )

    new_cover_sources: list[str] = []
    fields_filled = 0

    if enriched:
        patch: dict = {}
        for k in _REFILLABLE_FIELDS:
            if row.get(k) is None and enriched.get(k):
                patch[k] = enriched[k]
        if patch:
            sets = ", ".join(f"{k} = ?" for k in patch)
            values = list(patch.values()) + [book_id]
            with connect() as c:
                c.execute(f"UPDATE books SET {sets} WHERE id = ?", values)
            fields_filled = len(patch)

        cover_url = enriched.get("cover_url")
        if cover_url:
            source = enriched["metadata_source"]
            book_dir = _safe_book_dir(book_id)
            candidate_path = book_dir / "covers" / f"{source}.jpg"
            if not candidate_path.exists():
                if library._download_cover(cover_url, source, book_dir):
                    new_cover_sources.append(source)

    return {
        "book": library._book_row(book_id),
        "fields_filled": fields_filled,
        "new_cover_sources": new_cover_sources,
    }
