"""Kokoro CPU TTS container: text + voice name -> WAV + native word timings.

No GPU, no aligner model, no idle watchdog. Always-up; the reader's
kokoro_lifecycle.ensure_up() brings it up on demand. Exposes a small HTTP
synth+health contract that the main server's backend client calls.
"""
from __future__ import annotations

import base64
import os
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import align
from .synthesizer import KokoroSynthesizer, available_voices

_synth: Optional[KokoroSynthesizer] = None
_loaded: bool = False

_VOICE_RE = re.compile(r"^[a-z]{2}_[a-z]+$")


def set_synthesizer(synth: KokoroSynthesizer) -> None:
    """Inject the synthesizer and mark the service ready (startup + tests)."""
    global _synth, _loaded
    _synth = synth
    _loaded = True


def reset_for_test() -> None:
    global _synth, _loaded
    _synth = None
    _loaded = False


class SynthRequest(BaseModel):
    text: str
    language_id: str = "en"
    voice: str = "af_heart"
    speed: float = 1.0  # Kokoro native rate; clamped to [0.5, 2.0] below


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _startup()
    yield


app = FastAPI(title="reader-kokoro", docs_url=None, redoc_url=None, lifespan=_lifespan)


@app.get("/health")
def health() -> dict:
    if not _loaded or _synth is None:
        raise HTTPException(503, "models not loaded")
    return {"loaded": True, "sample_rate": _synth.sample_rate}


@app.get("/voices")
def voices() -> dict:
    return {"voices": available_voices()}


@app.post("/synthesize")
def synthesize(req: SynthRequest) -> dict:
    if not _loaded or _synth is None:
        raise HTTPException(503, "models not loaded")
    if not req.text.strip():
        raise HTTPException(400, "text required")
    if not _VOICE_RE.match(req.voice) or req.voice not in available_voices():
        raise HTTPException(400, f"unknown voice: {req.voice!r}")
    speed = min(max(req.speed, 0.5), 2.0)
    wav_bytes, dur_ms, timings = _synth.synth(req.text, req.voice, speed)
    source_words = align.tokenize(req.text)
    words, aligner = align.merge(source_words, timings, dur_ms, source_aligner="kokoro")
    return {
        "audio_b64": base64.b64encode(wav_bytes).decode("ascii"),
        "format": "wav",
        "sample_rate": _synth.sample_rate,
        "words": words,
        "aligner": aligner,
    }


def _startup() -> None:
    # Skip heavy model load under tests (synth injected via set_synthesizer).
    if os.environ.get("KOKORO_SKIP_LOAD") == "1" or _loaded:
        return
    set_synthesizer(KokoroSynthesizer())
    # Warm one throwaway synth so the first real request doesn't pay model JIT.
    try:
        warm = os.environ.get("KOKORO_WARMUP_VOICE", "af_heart")
        _synth.synth("Warming up.", warm)  # type: ignore[union-attr]
    except Exception:
        pass
