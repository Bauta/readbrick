"""Download the bundled reading fonts (latin woff2) into web/fonts/ and their
OFL licenses into web/fonts/licenses/. Reuses the parse/download logic in
server.fonts so there is one implementation. Run manually:

    python scripts/fetch-bundled-fonts.py
"""
from __future__ import annotations

from pathlib import Path

import httpx

from server import fonts

ROOT = Path(__file__).resolve().parent.parent
WEB_FONTS = ROOT / "web" / "fonts"
LICENSES = WEB_FONTS / "licenses"

# (family, filename-stem, OFL raw url)
TARGETS = [
    ("Lora", "Lora", "https://raw.githubusercontent.com/google/fonts/main/ofl/lora/OFL.txt"),
    ("Bitter", "Bitter", "https://raw.githubusercontent.com/google/fonts/main/ofl/bitter/OFL.txt"),
    ("Atkinson Hyperlegible", "AtkinsonHyperlegible",
     "https://raw.githubusercontent.com/google/fonts/main/ofl/atkinsonhyperlegible/OFL.txt"),
]
_STYLE_SUFFIX = {"normal": "Regular", "italic": "Italic"}


def main() -> None:
    WEB_FONTS.mkdir(parents=True, exist_ok=True)
    LICENSES.mkdir(parents=True, exist_ok=True)
    for family, stem, ofl_url in TARGETS:
        files = fonts._fetch_font_files(family)
        for style, data in files.items():
            out = WEB_FONTS / f"{stem}-{_STYLE_SUFFIX[style]}.woff2"
            out.write_bytes(data)
            print(f"wrote {out.name} ({len(data)} bytes)")
        lic = httpx.get(ofl_url, timeout=30.0, follow_redirects=True)
        lic.raise_for_status()
        (LICENSES / f"{fonts.slugify(family)}-OFL.txt").write_text(lic.text, encoding="utf-8")
        print(f"wrote license for {family}")


if __name__ == "__main__":
    main()
