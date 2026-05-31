#!/usr/bin/env python3
"""Re-extract paragraph text from an already-ingested book's original file.

Updates <library>/<book_id>/book.json in place. Audio cache, progress,
quotes, and user prefs are untouched. Paragraph IDX values stay stable as
long as the source file's <p>/<h*>/<blockquote> tag count hasn't changed
(which it hasn't — only the text within each is being re-cleaned).

Usage:
    python -m scripts.reextract <book_id>
    python -m scripts.reextract --all              # all books in the library

Motivation: an earlier extraction used BeautifulSoup's `get_text(" ", ...)`
which inserted phantom spaces around inline elements, producing things
like "Potterne ." (space before period). The new extraction (`get_text()`
without separator) renders clean text, but books already in the library
have the old text baked into book.json. Run this once after upgrading.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import config, library  # noqa: E402


def _book_dir(book_id: str) -> Path:
    return config.library_dir() / book_id


def _find_source_file(book_dir: Path) -> Path | None:
    # We store the upload as original.<ext>; pick whichever exists.
    for p in book_dir.iterdir():
        if p.name.startswith("original."):
            return p
    return None


def _list_book_ids() -> list[str]:
    return sorted(
        d.name for d in config.library_dir().iterdir()
        if d.is_dir() and (d / "book.json").exists()
    )


def _reextract_one(book_id: str) -> bool:
    bd = _book_dir(book_id)
    book_json_path = bd / "book.json"
    if not book_json_path.exists():
        print(f"  {book_id}: no book.json found, skipping", file=sys.stderr)
        return False
    src = _find_source_file(bd)
    if src is None:
        print(f"  {book_id}: no original.* source file, skipping", file=sys.stderr)
        return False

    ext = src.suffix.lower()
    if ext != ".epub":
        # PDF/TXT/MOBI/AZW3 extraction wouldn't use the same code path; not
        # affected by the BS4 separator bug. Skip them.
        print(f"  {book_id}: {ext} format unaffected by extraction fix, skipping")
        return False

    book = json.loads(book_json_path.read_text(encoding="utf-8"))
    old_chapters = book.get("chapters") or []
    old_para_count = sum(len(ch.get("paragraphs") or []) for ch in old_chapters)

    # Re-parse with the new extraction logic.
    parsed = library.parse_epub(src, bd)
    new_chapters = parsed.get("chapters") or []
    new_para_count = sum(len(ch.get("paragraphs") or []) for ch in new_chapters)

    if new_para_count != old_para_count:
        print(f"  {book_id}: paragraph count changed "
              f"({old_para_count} → {new_para_count}); refusing to update "
              f"because paragraph_idx in progress/quotes would mis-align. "
              f"Re-upload the book if you accept losing position.")
        return False

    # Preserve metadata that lives outside the parsed structure: title,
    # author, language, isbn — anything ingest set or the user edited.
    # We only replace `chapters`.
    book["chapters"] = new_chapters

    book_json_path.write_text(
        json.dumps(book, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  {book_id}: updated {new_para_count} paragraphs across "
          f"{len(new_chapters)} chapter(s)")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument("book_id", nargs="?", help="Single book id to re-extract.")
    grp.add_argument("--all", action="store_true", help="Re-extract every book in the library.")
    args = p.parse_args(argv)

    targets = _list_book_ids() if args.all else [args.book_id]
    print(f"Re-extracting {len(targets)} book(s) under {config.library_dir()}/")
    updated = 0
    for bid in targets:
        if _reextract_one(bid):
            updated += 1
    print(f"\nDone. Updated {updated} / {len(targets)} book(s).")
    if updated > 0:
        print("Reload the reader page (or hard-refresh) to see the cleaned text.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
