"""Regenerate data/google-fonts-list.json from Google's public font metadata.

No API key required. Run manually when refreshing the catalog:

    python scripts/build-font-list.py

The metadata endpoint returns the whole Google Fonts family list. We keep only
the family name and category (used for the searchable picker); the actual woff2
files are fetched on demand by server/fonts.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

URL = "https://fonts.google.com/metadata/fonts"
OUT = Path(__file__).resolve().parent.parent / "data" / "google-fonts-list.json"


def main() -> None:
    r = httpx.get(URL, timeout=30.0)
    r.raise_for_status()
    text = r.text
    text = text[text.index("{"):]  # strip the anti-hijacking guard prefix
    data = json.loads(text)
    fams = [
        {"family": f["family"], "category": f.get("category", "")}
        for f in data["familyMetadataList"]
    ]
    fams.sort(key=lambda x: x["family"].lower())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fams, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(fams)} families to {OUT}")


if __name__ == "__main__":
    main()
