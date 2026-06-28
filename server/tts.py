"""TTS dispatcher: forward synthesis to the Kokoro backend.

Voice ids are `kokoro:<voice>` (e.g. `kokoro:af_heart`). The backend returns
audio + native word timings; this dispatcher just forwards them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .tts_backends import get_backend


# ───────────────────────── sentence / word splitting ─────────────────────────

_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    parts = _SENT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


_WORD_RE = re.compile(r"\S+")


def tokenize_words(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(), m.start(), m.end()) for m in _WORD_RE.finditer(text)]


# ───────────────────────── public API ─────────────────────────


@dataclass
class SynthResult:
    audio_bytes: bytes
    audio_format: str  # "wav" | "mp3"
    words: list[dict]  # [{text, start_ms, end_ms}, ...]
    aligner_names: list[str]


def list_voices() -> list[dict]:
    return get_backend("kokoro").list_voices()


def synthesize(
    text: str, voice_id: str, language: str = "en", speed: float = 1.0
) -> SynthResult:
    r = get_backend("kokoro").synthesize(text, voice_id, language, speed)
    return SynthResult(
        audio_bytes=r.audio_bytes,
        audio_format=r.audio_format,
        words=r.words or [],
        aligner_names=[r.aligner or "kokoro"],
    )


def dominant_aligner(names: list[str]) -> str:
    if not names:
        raise ValueError("dominant_aligner requires at least one name")
    for preferred in ("kokoro", "native", "proportional"):
        if preferred in names:
            return preferred
    return names[0]
