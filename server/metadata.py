"""Book metadata enrichment.

Two-stage cascade: OpenLibrary first (no API key needed, wide
coverage), Google Books as fallback (broader international
catalog). Each external call has a 5-second timeout. Any failure or
empty result falls through; if both miss, the function returns None
and the book is stored with `metadata_source='none'`.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

import httpx

log = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(5.0)
_OL_URL = "https://openlibrary.org/api/books"
_OL_SEARCH = "https://openlibrary.org/search.json"
_GB_URL = "https://www.googleapis.com/books/v1/volumes"


def _google_books_key() -> Optional[str]:
    """Return the Google Books API key from env, or None if unset.

    Google removed anonymous quota for the Books API in 2026 — every request
    now requires `key=<your_api_key>`. Without a key, _try_google_books skips
    the call entirely and we rely on OpenLibrary + manual edit. See README's
    "Optional: Google Books API key" section for setup."""
    return os.environ.get("GOOGLE_BOOKS_API_KEY") or None


def clean_isbn(raw: Optional[str]) -> Optional[str]:
    """Strip non-digit/X chars and validate ISBN-10 or ISBN-13 length.
    Returns the canonical form (digits + optional X), or None if invalid.
    """
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9X]", "", raw.upper())
    if len(cleaned) in (10, 13):
        return cleaned
    return None


def enrich(
    title: str,
    author: Optional[str],
    language: Optional[str],
    isbn: Optional[str],
) -> Optional[dict]:
    """Returns dict with any of {description, published_year, isbn, genre,
    cover_url, metadata_source} when a hit is found, else None.
    """
    isbn = clean_isbn(isbn)

    # ── Stage 1: OpenLibrary ──
    ol = None
    try:
        ol = _try_openlibrary(title, author, isbn)
    except Exception as e:
        log.warning("openlibrary lookup failed: %s", e)
    if ol and ol.get("description"):
        return ol  # complete hit — cover + description

    # ── Stage 2: Google Books ──
    # Reached when OpenLibrary missed entirely OR returned a hit without a
    # description (common — many OL records have a cover but no description).
    gb = None
    try:
        gb = _try_google_books(title, author, isbn)
    except Exception as e:
        log.warning("google books lookup failed: %s", e)

    if ol:
        # Keep OpenLibrary's metadata (cover, year, …); fill the missing
        # description from Google Books if it found one.
        if gb and gb.get("description"):
            return {**ol, "description": gb["description"]}
        return ol
    return gb or None


def _try_openlibrary(
    title: str, author: Optional[str], isbn: Optional[str]
) -> Optional[dict]:
    if isbn:
        r = httpx.get(
            _OL_URL,
            params={"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"},
            timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json() or {}
            book = data.get(f"ISBN:{isbn}")
            if book:
                return _ol_normalize(book, found_isbn=isbn)
        return None

    # No ISBN — fall back to title+author search.
    params = {"title": title, "limit": "1"}
    if author:
        params["author"] = author
    r = httpx.get(_OL_SEARCH, params=params, timeout=_TIMEOUT)
    if r.status_code != 200:
        return None
    docs = (r.json() or {}).get("docs") or []
    if not docs:
        return None
    d = docs[0]
    return {
        "metadata_source": "openlibrary",
        "published_year": _first_int(d.get("first_publish_year")),
        "isbn": _first_str(d.get("isbn")),
        "genre": _join_subjects(d.get("subject")),
        # The search record has no description — it lives on the /works record.
        "description": _ol_works_description(d.get("key")),
        "cover_url": (
            f"https://covers.openlibrary.org/b/id/{d['cover_i']}-M.jpg"
            if d.get("cover_i") else None
        ),
    }


def _ol_works_description(works_key: Optional[str]) -> Optional[str]:
    """Fetch an OpenLibrary /works/{id}.json record for its description.

    The search + edition endpoints omit descriptions; only the works record has
    one. `description` is either a plain string or a {"type", "value"} object.
    Returns the trimmed string, or None on any miss/failure.
    """
    if not works_key:
        return None
    try:
        r = httpx.get(f"https://openlibrary.org{works_key}.json", timeout=_TIMEOUT)
        if r.status_code != 200:
            return None
        desc = (r.json() or {}).get("description")
        if isinstance(desc, dict):
            desc = desc.get("value")
        return desc.strip() if isinstance(desc, str) and desc.strip() else None
    except Exception:
        return None


def _ol_normalize(book: dict, *, found_isbn: str) -> dict:
    subjects = book.get("subjects") or []
    subject_names = [s["name"] for s in subjects if isinstance(s, dict) and s.get("name")]
    return {
        "metadata_source": "openlibrary",
        "published_year": _parse_year(book.get("publish_date")),
        "isbn": found_isbn,
        "genre": _join_subjects(subject_names),
        "description": book.get("notes") or _first_str(book.get("excerpts")),
        "cover_url": (book.get("cover") or {}).get("medium")
                     or (book.get("cover") or {}).get("large"),
    }


def _try_google_books(
    title: str, author: Optional[str], isbn: Optional[str]
) -> Optional[dict]:
    key = _google_books_key()
    if not key:
        # Google Books requires authenticated requests as of 2026. Skip the
        # API entirely when no key is configured rather than burn a request
        # that's guaranteed to 429.
        return None
    if isbn:
        query = f"isbn:{isbn}"
    else:
        parts = [f'intitle:"{title}"']
        if author:
            parts.append(f'inauthor:"{author}"')
        query = "+".join(parts)
    r = httpx.get(
        _GB_URL,
        params={"q": query, "maxResults": "1", "key": key},
        timeout=_TIMEOUT,
    )
    if r.status_code != 200:
        return None
    items = (r.json() or {}).get("items") or []
    if not items:
        return None
    vi = items[0].get("volumeInfo") or {}
    ids = vi.get("industryIdentifiers") or []
    isbn13 = next((i["identifier"] for i in ids if i.get("type") == "ISBN_13"), None)
    isbn10 = next((i["identifier"] for i in ids if i.get("type") == "ISBN_10"), None)
    return {
        "metadata_source": "google_books",
        "published_year": _parse_year(vi.get("publishedDate")),
        "isbn": isbn13 or isbn10 or isbn,
        "genre": _join_subjects(vi.get("categories")),
        "description": vi.get("description"),
        "cover_url": (vi.get("imageLinks") or {}).get("thumbnail"),
    }


def _parse_year(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    m = re.search(r"\d{4}", str(s))
    return int(m.group(0)) if m else None


def _join_subjects(subjects) -> Optional[str]:
    """Lowercased, comma-joined, up to 5 subjects."""
    if not subjects:
        return None
    cleaned = []
    for s in subjects:
        if isinstance(s, dict):
            s = s.get("name")
        if not s:
            continue
        cleaned.append(str(s).strip().lower())
        if len(cleaned) >= 5:
            break
    return ", ".join(cleaned) if cleaned else None


def _first_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _first_str(v) -> Optional[str]:
    if isinstance(v, list) and v:
        return str(v[0])
    if isinstance(v, str):
        return v
    return None
