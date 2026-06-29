"""Reader fonts: bundled manifest, Google Fonts catalog, and on-demand
server-side download + cache.

Privacy: the browser never contacts Google. The server fetches each
non-bundled family once (latin subset), caches it under
config.fonts_cache_dir()/<slug>/, and serves it from /api/fonts/file/...
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import FONT_MAX_BYTES, fonts_cache_dir

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "google-fonts-list.json"
_CSS_URL = "https://fonts.googleapis.com/css2?family={family}:ital@0;1&display=swap"
# A modern browser UA so Google serves woff2 (not legacy ttf).
_WOFF2_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = httpx.Timeout(8.0)

# Bundled fonts. kind="system" → no file (system stack); kind="file" → served
# from /web/fonts/ via the existing static route, @font-face is static CSS.
_BUNDLED = [
    {"key": "sans", "label": "Sans", "family": "System Sans", "kind": "system"},
    {"key": "serif", "label": "Serif", "family": "Lora", "kind": "file"},
    {"key": "slab", "label": "Slab", "family": "Bitter", "kind": "file"},
    {"key": "hyperlegible", "label": "Legible", "family": "Atkinson Hyperlegible", "kind": "file"},
    {"key": "dyslexic", "label": "Dyslexic", "family": "OpenDyslexic", "kind": "file"},
]
_BUNDLED_FAMILIES = {b["family"] for b in _BUNDLED}


def bundled_manifest() -> list[dict]:
    return [dict(b) for b in _BUNDLED]


@lru_cache(maxsize=1)
def _families() -> list[dict]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def catalog() -> dict:
    return {"bundled": bundled_manifest(), "families": _families()}


def slugify(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")


def is_allowed(family: str) -> bool:
    if family in _BUNDLED_FAMILIES:
        return True
    return any(f["family"] == family for f in _families())


_FACE_RE = re.compile(r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{([^}]*)\}", re.S)
_URL_RE = re.compile(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)")


def _parse_css(css: str) -> dict[str, str]:
    """Return {style: gstatic-woff2-url} for the latin subset. Only
    fonts.gstatic.com URLs are accepted (SSRF guard)."""
    chosen: dict[str, str] = {}
    for m in _FACE_RE.finditer(css):
        subset, body = m.group(1), m.group(2)
        if subset != "latin":
            continue
        url_m = _URL_RE.search(body)
        if not url_m:
            continue
        style = "italic" if "font-style: italic" in body else "normal"
        chosen.setdefault(style, url_m.group(1))
    return chosen


def _fetch_font_files(family: str) -> dict[str, bytes]:
    """Download the latin woff2 (normal + italic if present) for `family`.
    Raises RuntimeError on any network/parse/host failure."""
    url = _CSS_URL.format(family=quote(family))
    try:
        css = httpx.get(url, headers={"User-Agent": _WOFF2_UA}, timeout=_TIMEOUT,
                        follow_redirects=True)
        css.raise_for_status()
        faces = _parse_css(css.text)
        if not faces:
            raise RuntimeError(f"no latin woff2 found for {family!r}")
        out: dict[str, bytes] = {}
        for style, furl in faces.items():
            resp = httpx.get(furl, timeout=_TIMEOUT, follow_redirects=True)
            resp.raise_for_status()
            data = resp.content
            if not data or len(data) > FONT_MAX_BYTES:
                raise RuntimeError(f"bad font payload for {family!r}")
            out[style] = data
        return out
    except httpx.HTTPError as e:
        raise RuntimeError(f"font fetch failed for {family!r}: {e}") from e


_STYLE_INDEX = {"normal": "0", "italic": "1"}


def ensure(family: str) -> dict:
    if not is_allowed(family):
        raise ValueError(f"font not in catalog: {family!r}")
    slug = slugify(family)
    dest = fonts_cache_dir() / slug
    existing = sorted(dest.glob("*.woff2")) if dest.is_dir() else []
    if existing:
        faces = [
            {"style": s, "url": f"/api/fonts/file/{slug}/{i}.woff2"}
            for s, i in _STYLE_INDEX.items()
            if (dest / f"{i}.woff2").is_file()
        ]
        return {"family": family, "slug": slug, "cached": True, "faces": faces}

    files = _fetch_font_files(family)
    dest.mkdir(parents=True, exist_ok=True)
    faces = []
    for style, data in files.items():
        i = _STYLE_INDEX[style]
        (dest / f"{i}.woff2").write_bytes(data)
        faces.append({"style": style, "url": f"/api/fonts/file/{slug}/{i}.woff2"})
    return {"family": family, "slug": slug, "cached": False, "faces": faces}


def font_path(slug: str, leaf: str) -> Path | None:
    base = fonts_cache_dir().resolve()
    target = (base / slug / leaf).resolve()
    if base not in target.parents:
        return None
    return target if target.is_file() else None
