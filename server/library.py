"""Book ingest: detect format, parse to canonical book.json, persist."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from .config import IMAGE_EXTS, SUPPORTED_FORMATS, library_dir
from .db import connect, now
from . import metadata as md


# ───────────────────────── public API ─────────────────────────


def ingest(src_path: Path, original_filename: str) -> dict:
    """Detect format, parse, enrich, persist a book. Returns the DB row.

    Phases:
      1. _stage_upload  — validate ext, allocate book_id + dir, copy original
      2. _parse_by_format — dispatch to format-specific parser
      3. _assemble_book  — flatten paragraphs, derive word_count, build dict
      4. _enrich_metadata — call OpenLibrary/Google Books cascade
      5. _initialize_active_cover — pick highest-priority cover candidate
      6. _persist_book   — write book.json + INSERT row
    """
    book_id, book_dir, stored_original, ext = _stage_upload(src_path, original_filename)
    try:
        parsed, fmt = _parse_by_format(ext, stored_original, book_dir)
    except Exception:
        shutil.rmtree(book_dir, ignore_errors=True)
        raise

    paragraphs = [p for ch in parsed["chapters"] for p in ch["paragraphs"]]
    if not paragraphs:
        shutil.rmtree(book_dir, ignore_errors=True)
        raise ValueError("Parsed book has no paragraphs")

    book = _assemble_book(book_id, parsed, original_filename, fmt, paragraphs)
    _enrich_metadata(book, book_dir)
    _initialize_active_cover(book_dir, book)
    _persist_book(book, paragraph_count=len(paragraphs))
    return _book_row(book_id)


# ───────────────────────── ingest phases ─────────────────────────


def _stage_upload(src_path: Path, original_filename: str) -> tuple[str, Path, Path, str]:
    """Validate extension, allocate book_id + book_dir, copy the upload in.
    Returns (book_id, book_dir, stored_original_path, lowercase_ext)."""
    ext = Path(original_filename).suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: {ext}")

    book_id = uuid.uuid4().hex
    book_dir = library_dir() / book_id
    book_dir.mkdir(parents=True, exist_ok=False)

    stored_original = book_dir / f"original{ext}"
    shutil.copy(src_path, stored_original)
    return book_id, book_dir, stored_original, ext


def _parse_by_format(ext: str, stored_original: Path, book_dir: Path) -> tuple[dict, str]:
    """Dispatch to the format-specific parser. Also renders the PDF page-1
    cover candidate. MOBI/AZW3 are first converted to EPUB then EPUB-parsed.
    Returns (parsed_dict, normalized_format_label)."""
    if ext == ".epub":
        return parse_epub(stored_original, book_dir), "epub"
    if ext == ".pdf":
        # Render page 1 as a cover candidate. Silent on failure.
        pdf_cover = book_dir / "covers" / "pdf.jpg"
        pdf_cover.parent.mkdir(parents=True, exist_ok=True)
        render_pdf_page_1(stored_original, pdf_cover)
        return parse_pdf(stored_original), "pdf"
    if ext == ".txt":
        return parse_txt(stored_original), "txt"
    if ext in (".mobi", ".azw3"):
        converted = book_dir / "converted.epub"
        convert_to_epub(stored_original, converted)
        return parse_epub(converted, book_dir), ext.lstrip(".")
    # Already filtered by _stage_upload; defensive.
    raise ValueError(f"Unsupported format: {ext}")


def _assemble_book(
    book_id: str,
    parsed: dict,
    original_filename: str,
    fmt: str,
    paragraphs: list[dict],
) -> dict:
    """Build the in-memory book dict that subsequent phases mutate.
    word_count is derived here; ISBN comes from the parser."""
    word_count = sum(len(p["text"].split()) for p in paragraphs)
    return {
        "id": book_id,
        "title": parsed.get("title") or Path(original_filename).stem,
        "author": parsed.get("author"),
        "language": parsed.get("language"),
        "format": fmt,
        "chapters": parsed["chapters"],
        "images": parsed.get("images") or [],
        "isbn": parsed.get("isbn"),
        "word_count": word_count,
    }


def _enrich_metadata(book: dict, book_dir: Path) -> None:
    """Run the OpenLibrary → Google Books cascade. Fill NULL fields on
    the book dict in place. Download the external cover candidate if one
    was returned. Mutates `book`."""
    enriched = md.enrich(book["title"], book["author"], book["language"], book["isbn"])
    if not enriched:
        book["description"] = None
        book["published_year"] = None
        book["genre"] = None
        book["metadata_source"] = "none"
        return
    # EPUB's own ISBN wins over external lookup
    book["isbn"] = book["isbn"] or enriched.get("isbn")
    book["description"] = enriched.get("description")
    book["published_year"] = enriched.get("published_year")
    book["genre"] = enriched.get("genre")
    book["metadata_source"] = enriched["metadata_source"]
    cover_url = enriched.get("cover_url")
    if cover_url:
        source = enriched["metadata_source"]
        candidate_path = book_dir / "covers" / f"{source}.jpg"
        if not candidate_path.exists():
            _download_cover(cover_url, source, book_dir)


def _persist_book(book: dict, *, paragraph_count: int) -> None:
    """Write book.json to disk and INSERT the row into `books`."""
    book_dir = library_dir() / book["id"]
    (book_dir / "book.json").write_text(json.dumps(book, ensure_ascii=False))
    with connect() as c:
        c.execute(
            """
            INSERT INTO books (
              id, title, author, language, format, paragraph_count, added_at,
              description, published_year, isbn, genre, word_count, metadata_source,
              cover_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book["id"],
                book["title"],
                book["author"],
                book["language"],
                book["format"],
                paragraph_count,
                now(),
                book["description"],
                book["published_year"],
                book["isbn"],
                book["genre"],
                book["word_count"],
                book["metadata_source"],
                book["cover_active"],
            ),
        )


def list_books() -> list[dict]:
    with connect() as c:
        rows = c.execute(
            """
            SELECT id, title, author, language, format, paragraph_count, added_at,
                   description, published_year, isbn, genre, word_count, metadata_source,
                   cover_active
            FROM books ORDER BY added_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_book(book_id: str) -> Optional[dict]:
    book_dir = library_dir() / book_id
    book_json = book_dir / "book.json"
    if not book_json.exists():
        return None
    book = json.loads(book_json.read_text())
    # book.json caches the content (chapters); the DB books row is the single
    # source of truth for editable metadata. update_metadata, refresh_metadata
    # and the cover controls write the DB row only, so overlay it here — without
    # this, edits show in the library list (DB-backed) but not on the detail page
    # or reader, which read get_book.
    with connect() as c:
        row = c.execute(
            """
            SELECT title, author, language, format, paragraph_count,
                   description, published_year, isbn, genre, word_count,
                   metadata_source, cover_active
            FROM books WHERE id = ?
            """,
            (book_id,),
        ).fetchone()
    if row is not None:
        book.update(dict(row))
    return book


def delete_book(book_id: str) -> bool:
    book_dir = library_dir() / book_id
    if not book_dir.exists():
        return False
    shutil.rmtree(book_dir, ignore_errors=True)
    with connect() as c:
        c.execute("DELETE FROM books WHERE id = ?", (book_id,))
    return True


def cover_path(book_id: str) -> Optional[Path]:
    p = library_dir() / book_id / "cover.jpg"
    return p if p.exists() else None


def _book_row(book_id: str) -> dict:
    with connect() as c:
        return dict(
            c.execute(
                """
                SELECT id, title, author, language, format, paragraph_count, added_at,
                       description, published_year, isbn, genre, word_count, metadata_source,
                       cover_active
                FROM books WHERE id = ?
                """,
                (book_id,),
            ).fetchone()
        )


# ───────────────────────── EPUB ─────────────────────────


def _extract_paragraphs_from_html(html_bytes: bytes | str) -> tuple[str, list[dict], list[dict]]:
    """Pull paragraphs + chapter title + image refs out of one EPUB document.

    Use get_text() WITHOUT a separator. BeautifulSoup's separator argument
    inserts the given string between every NavigableString in the subtree —
    including between a word and its trailing inline element. With
    separator=" " that produces phantom spaces:
        <p>vite om <em>Potterne</em>.</p>  →  "vite om Potterne ."
    (with a stray space before the period). Reading that in the UI looks
    like punctuation has been "cleaned" off the words it belongs to.
    Using get_text() concatenates without phantom separators; _normalize_ws
    then collapses any legitimate whitespace runs from the source markup
    down to single spaces and trims.

    Returns (chapter_title, [{idx (within-doc, 0-based), text}, ...], [{src_base, alt, after_idx}, ...]).
    Callers should renumber `idx` across multiple documents.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_bytes, "html.parser")
    ch_title = ""
    for h in soup.find_all(["h1", "h2", "h3"]):
        t = h.get_text(strip=True)
        if t and not _GENERIC_HEADING_RE.match(t):
            ch_title = t
            break
    paragraphs: list[dict] = []
    image_refs: list[dict] = []
    for tag in soup.find_all(
        ["p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "img", "image"]
    ):
        if tag.name in ("img", "image"):
            src = tag.get("src") or tag.get("xlink:href") or tag.get("href")
            if not src:
                continue
            image_refs.append({
                "src_base": _href_base(src),
                "alt": (tag.get("alt") or "").strip(),
                "after_idx": len(paragraphs) - 1,
            })
            continue
        text = _normalize_ws(tag.get_text())
        if not text:
            continue
        paragraphs.append({"idx": len(paragraphs), "text": text})
    return ch_title, paragraphs, image_refs


# A structural label ("PART 1", "SECTION 2", "CHAPTER IV") rather than a real
# chapter title — skipped in favour of the document's actual title / TOC name.
_GENERIC_HEADING_RE = re.compile(r"^(part|section|chapter|book)\s+[\divxlcdm]+\.?$", re.I)

# The EPUB3 nav document carries `epub:type="toc"`; it lists the TOC, not prose.
_NAV_TOC_RE = re.compile(rb"""epub:type=['"]toc['"]""")

# Front/back-matter we don't want as readable chapters (matched against the
# chapter title + the source filename).
_FRONTMATTER_KEYWORDS = (
    "cover", "title", "copyright", "dedication", "contents", "toc", "index",
    "about", "acknowledg", "newsletter", "colophon", "adcard", "praise", "nav",
)


def _href_base(href: str) -> str:
    """Filename of an href, without directory or #fragment."""
    return (href or "").split("#", 1)[0].rsplit("/", 1)[-1]


def _toc_title_map(book) -> dict:
    """Map basename(href) -> chapter title from the EPUB TOC (nav for EPUB3,
    ncx for EPUB2, via ebooklib's parsed book.toc). The TOC carries the real
    chapter names; per-file headings are often generic labels. First wins."""
    from ebooklib import epub

    out: dict = {}

    def walk(node):
        for el in node or ():
            if isinstance(el, epub.Link):
                base = _href_base(el.href)
                ttl = (el.title or "").strip()
                if base and ttl and base not in out:
                    out[base] = ttl
            elif isinstance(el, tuple) and len(el) == 2 and not isinstance(el[0], epub.Link):
                walk(el[1])  # (Section, children) — recurse children
            elif isinstance(el, (list, tuple)):
                walk(el)

    try:
        walk(book.toc)
    except Exception:
        pass
    return out


def _is_nav_document(content: "bytes | str") -> bool:
    raw = content if isinstance(content, bytes) else content.encode("utf-8", "ignore")
    return bool(_NAV_TOC_RE.search(raw))


def _is_skippable_chapter(title: str, href_base: str) -> bool:
    """Drop untitled docs + front/back-matter (cover, title page, copyright,
    contents, index, about, …) from the chapter list."""
    t = (title or "").strip().lower()
    if not t:
        return True
    blob = t + " " + href_base.lower()
    return any(k in blob for k in _FRONTMATTER_KEYWORDS)


def _epub_image_resources(book) -> dict:
    """Map basename(file_name) -> (content_bytes, lowercase_ext) for every
    image resource in the EPUB. Used to resolve <img src> references."""
    from ebooklib import ITEM_IMAGE

    out: dict = {}
    for item in book.get_items_of_type(ITEM_IMAGE):
        name = item.file_name or item.get_name() or ""
        base = _href_base(name)
        if not base:
            continue
        content = item.get_content()
        if not content:
            continue
        ext = Path(name).suffix.lstrip(".").lower() or "img"
        out[base] = (content, ext)
    return out


def _write_book_image(book_dir: Path, fname: str, data: bytes) -> None:
    images_dir = book_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / fname).write_bytes(data)


def parse_epub(path: Path, book_dir: Path) -> dict:
    from ebooklib import epub, ITEM_DOCUMENT  # noqa: F401

    book = epub.read_epub(str(path), options={"ignore_ncx": True})

    title = _first_meta(book, "title") or path.stem
    author = _first_meta(book, "creator")
    language = _first_meta(book, "language")
    isbn = _extract_isbn(book)

    _try_extract_cover(book, book_dir)

    image_resources = _epub_image_resources(book)
    toc = _toc_title_map(book)
    raw: list[dict] = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        content = item.get_content()
        if _is_nav_document(content):
            continue  # the EPUB3 nav doc is not a chapter
        base = _href_base(item.file_name or item.get_name())
        heading_title, doc_paragraphs, doc_image_refs = _extract_paragraphs_from_html(content)
        if not doc_paragraphs and not doc_image_refs:
            continue
        raw.append({
            "title": heading_title or toc.get(base) or "",
            "paragraphs": doc_paragraphs,
            "image_refs": doc_image_refs,
            "base": base,
        })

    kept = [c for c in raw if not _is_skippable_chapter(c["title"], c["base"])]
    if not kept:
        kept = raw  # safety: never end up with zero chapters

    chapters: list[dict] = []
    images: list[dict] = []
    written: dict = {}   # src_base -> serving url (dedup)
    idx_counter = 0
    img_seq = 0
    for c in kept:
        renumbered = [
            {"idx": idx_counter + i, "text": p["text"]}
            for i, p in enumerate(c["paragraphs"])
        ]
        for ref in c["image_refs"]:
            local = ref["after_idx"]
            global_after = idx_counter - 1 if local < 0 else idx_counter + local
            src_base = ref["src_base"]
            url = written.get(src_base)
            if url is None:
                res = image_resources.get(src_base)
                if res is None:
                    continue  # unresolvable resource — skip silently
                data, ext = res
                if ext not in IMAGE_EXTS:
                    continue
                fname = f"{img_seq:04d}.{ext}"
                _write_book_image(book_dir, fname, data)
                img_seq += 1
                url = f"/api/books/{book_dir.name}/images/{fname}"
                written[src_base] = url
            images.append({"src": url, "after_idx": global_after, "alt": ref["alt"]})
        idx_counter += len(renumbered)
        chapters.append({"title": c["title"], "paragraphs": renumbered})

    return {
        "title": title,
        "author": author,
        "language": _short_lang(language),
        "isbn": isbn,
        "chapters": chapters,
        "images": images,
    }


def _first_meta(book, name: str) -> Optional[str]:
    items = book.get_metadata("DC", name)
    if not items:
        return None
    return items[0][0]


def _extract_isbn(book) -> Optional[str]:
    """Look up DC:identifier entries; return one matching ISBN scheme/format."""
    from .metadata import clean_isbn

    items = book.get_metadata("DC", "identifier")
    for value, attrs in items or []:
        scheme = (attrs or {}).get("{http://www.idpf.org/2007/opf}scheme", "") or ""
        candidate = clean_isbn(value)
        if candidate and ("isbn" in scheme.lower() or len(candidate) in (10, 13)):
            return candidate
    return None


def _try_extract_cover(book, book_dir: Path) -> None:
    from ebooklib import ITEM_COVER, ITEM_IMAGE

    candidates = list(book.get_items_of_type(ITEM_COVER)) or list(
        book.get_items_of_type(ITEM_IMAGE)
    )
    for item in candidates:
        content = item.get_content()
        if content:
            save_cover_candidate(book_dir, "epub", content)
            return


# ───────────────────────── PDF ─────────────────────────


def parse_pdf(path: Path) -> dict:
    import pymupdf

    doc = pymupdf.open(str(path))
    title = doc.metadata.get("title") if doc.metadata else None
    author = doc.metadata.get("author") if doc.metadata else None

    paragraphs: list[dict] = []
    idx_counter = 0
    for page in doc:
        text = page.get_text("text") or ""
        for para_text in _split_pdf_text(text):
            paragraphs.append({"idx": idx_counter, "text": para_text})
            idx_counter += 1

    chapters = [{"title": "", "paragraphs": paragraphs}] if paragraphs else []
    return {
        "title": title,  # may be None; ingest() falls back to filename
        "author": author,
        "language": None,
        "isbn": None,
        "chapters": chapters,
    }


def _split_pdf_text(raw: str) -> list[str]:
    """Reconstruct paragraphs from PDF text. PDFs often hard-wrap lines;
    treat blank lines as paragraph breaks and join other line breaks with a space."""
    paragraphs: list[str] = []
    buf: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            if buf:
                paragraphs.append(_normalize_ws(" ".join(buf)))
                buf = []
        else:
            buf.append(line)
    if buf:
        paragraphs.append(_normalize_ws(" ".join(buf)))
    return [p for p in paragraphs if p]


# ───────────────────────── TXT ─────────────────────────


def parse_txt(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    paragraphs: list[dict] = []
    for idx, chunk in enumerate(re.split(r"\n\s*\n", raw)):
        text = _normalize_ws(chunk)
        if text:
            paragraphs.append({"idx": idx, "text": text})
    # Re-number to be contiguous after filtering empties
    for i, p in enumerate(paragraphs):
        p["idx"] = i
    return {
        "title": None,  # let ingest() fall back to original filename
        "author": None,
        "language": None,
        "isbn": None,
        "chapters": [{"title": "", "paragraphs": paragraphs}],
    }


# ───────────────────────── MOBI / AZW3 ─────────────────────────


def convert_to_epub(src: Path, dst: Path) -> None:
    if shutil.which("ebook-convert") is None:
        raise RuntimeError(
            "MOBI/AZW3 support requires Calibre's ebook-convert. "
            "Install with: sudo pacman -S calibre (or your distro's equivalent)."
        )
    result = subprocess.run(
        ["ebook-convert", str(src), str(dst)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ebook-convert failed: {result.stderr[-500:]}")


# ───────────────────────── helpers ─────────────────────────

_WS_RE = re.compile(r"\s+")


def _normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _short_lang(lang: Optional[str]) -> Optional[str]:
    if not lang:
        return None
    return lang.split("-")[0].split("_")[0].lower()[:5]


def _download_cover(url: str, source: str, book_dir: Path) -> bool:
    """Best-effort cover download. Writes to covers/<source>.jpg.
    Returns True on success, False on any failure."""
    import httpx

    try:
        r = httpx.get(url, timeout=5.0, follow_redirects=True)
        if r.status_code == 200 and r.content:
            save_cover_candidate(book_dir, source, r.content)
            return True
    except Exception:
        pass
    return False


def save_cover_candidate(book_dir: Path, source: str, content: bytes) -> Path:
    """Write a cover candidate into covers/<source>.jpg. Creates the
    directory if needed. Returns the path.

    Source must be one of: 'epub', 'pdf', 'openlibrary', 'google_books',
    'custom'. The caller is responsible for ensuring the source name is
    valid; passing an unknown source raises ValueError.
    """
    allowed = {"epub", "pdf", "openlibrary", "google_books", "custom"}
    if source not in allowed:
        raise ValueError(f"invalid cover source: {source}")
    covers_dir = book_dir / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    dst = covers_dir / f"{source}.jpg"
    dst.write_bytes(content)
    return dst


_COVER_PRIORITY = ["epub", "pdf", "openlibrary", "google_books"]


def _initialize_active_cover(book_dir: Path, book: dict) -> None:
    """At end of ingest, pick the highest-priority cover candidate that
    exists on disk, copy it to cover.jpg, and set book['cover_active'].
    If no candidate exists, leaves cover_active NULL and cover.jpg absent.
    """
    import shutil
    for source in _COVER_PRIORITY:
        candidate = book_dir / "covers" / f"{source}.jpg"
        if candidate.exists():
            shutil.copyfile(candidate, book_dir / "cover.jpg")
            book["cover_active"] = source
            return
    book["cover_active"] = None


def render_pdf_page_1(src: Path, dst: Path) -> bool:
    """Render page 1 of a PDF to a JPEG. Returns True on success, False
    on any error (corrupt PDF, no pages, pymupdf failure)."""
    try:
        import pymupdf
        from .config import PDF_COVER_MAX_HEIGHT_PX
        doc = pymupdf.open(str(src))
        if doc.page_count < 1:
            return False
        page = doc[0]
        zoom = 2.0
        height_at_zoom = page.rect.height * zoom
        if height_at_zoom > PDF_COVER_MAX_HEIGHT_PX:
            zoom = PDF_COVER_MAX_HEIGHT_PX / page.rect.height
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        pix.save(str(dst))
        return True
    except Exception:
        return False
