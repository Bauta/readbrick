"""Kokoro CPU HTTP backend: forwards synthesis to the always-up kokoro-tts container.

Kokoro emits native per-word timestamps, so this backend sets
BackendSynthResult.words (the dispatcher skips any aligner). Voice ids:
  kokoro:af_heart   → US English female "Heart"
  kokoro:bm_george  → UK English male   "George"
English-only: the 28 voices shipped by hexgrad/Kokoro-82M v1.0.
"""
from __future__ import annotations

import base64
import os

import httpx

from . import BackendSynthResult

# The 28 English voices baked into the kokoro-tts image. Kept in sync with
# kokoro_service/synthesizer.py ENGLISH_VOICES (separate deployment unit).
ENGLISH_VOICES = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
    "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]
_VOICE_SET = set(ENGLISH_VOICES)
DEFAULT_VOICE = "af_heart"


def _label(voice: str) -> str:
    """`af_heart` → `Heart — US English (female)` for the picker."""
    region = "US" if voice[:1] == "a" else "UK"
    gender = "female" if voice[1:2] == "f" else "male"
    name = voice.split("_", 1)[1].capitalize() if "_" in voice else voice
    return f"{name} — {region} English ({gender})"


def _base_url() -> str:
    return os.environ.get("READER_KOKORO_URL", "http://127.0.0.1:8005")


class KokoroBackend:
    name = "kokoro"

    def list_voices(self) -> list[dict]:
        return [
            {
                "voice_id": f"kokoro:{v}",
                "language": "en",
                "label": _label(v),
                "backend": "kokoro",
            }
            for v in ENGLISH_VOICES
        ]

    def synthesize(
        self, text: str, voice_id: str, language: str = "en", speed: float = 1.0
    ) -> BackendSynthResult:
        from .. import kokoro_lifecycle

        local = voice_id.split(":", 1)[1] if voice_id.startswith("kokoro:") else voice_id
        voice = local if local in _VOICE_SET else DEFAULT_VOICE

        kokoro_lifecycle.ensure_up()
        # Wrap only the network call: a transport error / non-2xx is a synthesis
        # failure (→ 503 upstream). Response-parsing errors below are a server
        # contract bug and should surface with their own, more specific message.
        try:
            resp = httpx.post(
                _base_url() + "/synthesize",
                json={"text": text, "language_id": "en", "voice": voice, "speed": speed},
                timeout=300.0,
            )
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Kokoro synthesis failed: {e}") from e

        data = resp.json()
        return BackendSynthResult(
            audio_bytes=base64.b64decode(data["audio_b64"]),
            audio_format=data.get("format", "wav"),
            sample_rate=int(data.get("sample_rate", 24000)),
            words=data["words"],
            aligner=data.get("aligner", "kokoro"),
        )
