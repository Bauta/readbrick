"""Configuration. Paths are read from env at call time so tests can isolate."""
from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("READER_DATA_DIR", str(Path.home() / ".reader")))


def library_dir() -> Path:
    return data_dir() / "library"


def cache_dir() -> Path:
    return data_dir() / "cache"


def fonts_cache_dir() -> Path:
    return cache_dir() / "fonts"


def db_path() -> Path:
    return data_dir() / "data.db"


def host() -> str:
    return os.environ.get("READER_HOST", "127.0.0.1")


def port() -> int:
    return int(os.environ.get("READER_PORT", "8000"))


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SUPPORTED_FORMATS = {".epub", ".pdf", ".txt", ".mobi", ".azw3"}
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}

WORDS_PER_MINUTE = 150  # Audiobook narration baseline at 1.0× speed.

PDF_COVER_MAX_HEIGHT_PX = 800
MAX_COVER_BYTES = 5 * 1024 * 1024
FONT_MAX_BYTES = 4 * 1024 * 1024

DEFAULT_VOICE = "kokoro:af_heart"


def ensure_dirs() -> None:
    for d in (data_dir(), library_dir(), cache_dir(), fonts_cache_dir()):
        d.mkdir(parents=True, exist_ok=True)
