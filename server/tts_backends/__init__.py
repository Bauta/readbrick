"""Pluggable TTS backends.

A "backend" turns text + a voice id into (audio bytes, word timings, format).
The voice id is prefixed with the backend name: `kokoro:af_heart`. Backward-
compat: unprefixed ids default to `kokoro`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

DEFAULT_BACKEND = "kokoro"


@dataclass(frozen=True)
class BackendSynthResult:
    """One TTS backend's synthesis output.

    `words` is None when the backend doesn't know word timings (it leaves them
    for the aligner waterfall to fill in). When the backend provides word
    timings natively (Kokoro), the aligner is bypassed and `words` is final.
    """

    audio_bytes: bytes
    audio_format: str  # "wav" | "mp3"
    sample_rate: Optional[int]  # None for compressed formats
    words: Optional[list[dict]]  # native timings, or None to let the aligner fill in
    aligner: Optional[str] = None  # backend-supplied aligner name (e.g. "kokoro")


@runtime_checkable
class TTSBackend(Protocol):
    name: str

    def list_voices(self) -> list[dict]:
        """Return [{voice_id, language, ...}, ...] for voices this backend exposes.

        voice_id is the fully-qualified prefixed form: `<backend>:<id>`.
        """

    def synthesize(
        self, text: str, voice_id: str, language: str = "en", speed: float = 1.0
    ) -> BackendSynthResult:
        """Synthesize text → audio + optional word timings.

        voice_id is the prefixed form (backends strip their own prefix).
        language is the book's language code (the backend maps it to whatever
        the underlying model expects). speed is a native rate multiplier
        (0.5 slower … 2.0 faster).
        """


def parse_voice_id(voice_id: str) -> tuple[str, str]:
    """Split a voice id into (backend_name, local_id).

    Unprefixed ids default to `kokoro` (DEFAULT_BACKEND) for backward
    compatibility with saved user preferences.
    """
    if ":" in voice_id:
        backend, _, local = voice_id.partition(":")
        return backend, local
    return DEFAULT_BACKEND, voice_id


# Registry of installed backends. Populated lazily so importing this package
# doesn't pull in the backend's httpx client until first use.
_backends: dict[str, TTSBackend] = {}


def get_backend(name: str) -> TTSBackend:
    """Return the backend with the given name, importing it on first use."""
    if name in _backends:
        return _backends[name]
    if name == "kokoro":
        from .kokoro import KokoroBackend

        _backends[name] = KokoroBackend()
    else:
        raise ValueError(f"Unknown TTS backend: {name!r}")
    return _backends[name]


def all_backend_names() -> list[str]:
    return ["kokoro"]
