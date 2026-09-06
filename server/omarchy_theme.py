"""Read the active Omarchy theme palette and expose it as CSS.

Omarchy keeps the live theme at ~/.local/state/omarchy/current/theme, a
directory containing a colors.toml with a small named palette. Reading it lets
the reader wear the desktop's colours.

This is strictly optional: Readbrick is a standalone web app, and on any
machine without Omarchy every function here degrades to "no palette" and the
reader renders with its own built-in colours.

The path is overridable via READER_OMARCHY_THEME_DIR, which is how the
container sees the host's theme (bind-mounted read-only).
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Optional

# A theme without these three cannot dress the reader; a half-applied palette
# is worse than none (unreadable body text).
REQUIRED = ("background", "foreground", "accent")

# WCAG AA for body text. The reader is long-form: this is the one place a
# desktop theme's priorities and a reading app's genuinely diverge.
MIN_BODY_CONTRAST = 4.5

# Colour values are interpolated into a stylesheet, so they are validated
# rather than trusted: hex, rgb()/rgba(), or a bare CSS colour keyword.
_SAFE_COLOR = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|rgba?\([\d\s.,%/]+\)|[a-zA-Z]{3,20})$"
)

# Omarchy palette key → Readbrick CSS custom property. Anything Omarchy does
# not define falls back to the value already in style.css.
_VAR_MAP = (
    ("--bg", "background"),
    ("--bg-2", "lighter_background"),
    ("--bg-elev", "lighter_background"),
    ("--fg", "foreground"),
    ("--fg-muted", "light_foreground"),
    ("--accent", "accent"),
    ("--accent-soft", "selection"),
    ("--border", "muted"),
)


def theme_dir() -> Path:
    override = os.environ.get("READER_OMARCHY_THEME_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local/state/omarchy/current/theme"


def theme_name() -> Optional[str]:
    """The active theme's display name, if Omarchy recorded one.

    Omarchy writes theme.name *beside* the theme directory, not inside it, so
    the parent has to be consulted — but never the filesystem root. Mounting
    the theme directory straight at "/omarchy-theme" would otherwise make this
    read "/theme.name", which is nobody's business but the root filesystem's.
    Mount one level up instead (see README) and the name comes through.
    """
    directory = theme_dir()
    candidates = [directory / "theme.name"]
    parent = directory.parent
    if parent != parent.parent:          # anything but the filesystem root
        candidates.append(parent / "theme.name")
    for candidate in candidates:
        try:
            name = candidate.read_text().strip()
        except OSError:
            continue
        if name:
            return name
    return None


def read_palette() -> Optional[dict]:
    """The active palette, or None when Omarchy is absent or unusable."""
    path = theme_dir() / "colors.toml"
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if not all(_safe(data.get(k)) for k in REQUIRED):
        return None
    if not _is_legible(data):
        return None
    return data


def _is_legible(palette: dict) -> bool:
    """Can this palette carry body text for an hour?

    A desktop theme is built for panels and terminals. One that looks sharp on
    a bar can be punishing to read at length, and a half-applied palette is
    worse than none — so a palette that cannot clear the floor is refused
    whole. Colours we cannot measure (CSS keywords, rgb()) are not judged:
    unmeasurable is not the same as unreadable.
    """
    ratio = contrast_ratio(palette.get("foreground"), palette.get("background"))
    return ratio is None or ratio >= MIN_BODY_CONTRAST


def contrast_ratio(one, two) -> Optional[float]:
    """WCAG contrast ratio between two hex colours, or None if unmeasurable."""
    first, second = _luminance(one), _luminance(two)
    if first is None or second is None:
        return None
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def _luminance(value) -> Optional[float]:
    rgb = _to_rgb(value)
    if rgb is None:
        return None
    channels = []
    for raw in rgb:
        c = raw / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _to_rgb(value) -> Optional[tuple]:
    if not isinstance(value, str):
        return None
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) not in (6, 8):
        return None
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _safe(value) -> bool:
    return isinstance(value, str) and bool(_SAFE_COLOR.match(value.strip()))


def palette_css(palette: Optional[dict]) -> str:
    """Render the palette as a scoped CSS block, or empty when unavailable.

    Scoped to [data-theme="omarchy"] so it sits alongside Readbrick's own
    Light / Sepia / Dark / Auto rather than overriding them: picking the
    Omarchy palette is one more choice in the theme setting, not a takeover.
    """
    if not palette:
        return ""
    lines = []
    for var, key in _VAR_MAP:
        value = palette.get(key)
        if _safe(value):
            lines.append(f"  {var}: {value.strip()};")
    if not lines:
        return ""
    # Text drawn ON the accent: the theme background is the safest contrast
    # partner Omarchy gives us for its own accent.
    if _safe(palette.get("background")):
        lines.append(f"  --accent-on: {palette['background'].strip()};")
    body = "\n".join(lines)
    return f'[data-theme="omarchy"] {{\n{body}\n}}\n'
