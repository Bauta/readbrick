"""Realtime synth service: synthesize audio + word timings on demand.

No disk cache and no precache — audio is synthesized when asked for and returned
inline. A small in-memory LRU memoizes the most recent synths (keyed by
text+voice+language+speed) so toggling speed, re-reading, or seeking back to a
just-heard paragraph is instant instead of paying another ~5s synth. The LRU is
RAM-only and bounded; nothing is persisted.

A single asyncio.Lock serializes the actual synthesis (the prefetch ring fires
several requests at once; the container does one synth at a time) and synthesis
runs off the event loop (asyncio.to_thread) so other routes stay responsive.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from . import tts

# Serializes synthesis across concurrent requests. An asyncio.Lock binds to the
# loop it's first used on, so we key it by running loop: production has one
# uvicorn loop (one shared lock); tests each get their own.
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None

# Bounded RAM memoization. ~32 paragraph synths (~8-16 MB of audio) is plenty to
# cover the visible window + recent speed/voice toggles without persisting.
_LRU_CAP = 32
_lru: "OrderedDict[tuple, SynthOutcome]" = OrderedDict()


def _get_lock() -> asyncio.Lock:
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock = asyncio.Lock()
        _lock_loop = loop
    return _lock


def _lru_get(key: tuple) -> "SynthOutcome | None":
    hit = _lru.get(key)
    if hit is not None:
        _lru.move_to_end(key)  # mark most-recently-used
    return hit


def _lru_put(key: tuple, outcome: "SynthOutcome") -> None:
    _lru[key] = outcome
    _lru.move_to_end(key)
    while len(_lru) > _LRU_CAP:
        _lru.popitem(last=False)  # drop least-recently-used


def reset_cache() -> None:
    """Clear the memoization LRU (used by tests)."""
    _lru.clear()


@dataclass(frozen=True)
class SynthOutcome:
    audio_bytes: bytes
    audio_format: str
    words: list[dict]
    aligner: str
    from_cache: bool = False


async def synthesize(
    text: str, voice_id: str, language: str = "en", speed: float = 1.0
) -> SynthOutcome:
    """Synthesize (text, voice_id, language, speed) → audio + word timings.

    LRU-first; on a miss, acquires the synth lock, re-checks the LRU (a request
    ahead of us may have just produced it), then synthesizes off the event loop
    and memoizes. `speed` is Kokoro's native rate (0.5 slower … 2.0 faster); the
    model paces the speech and emits matching word timings, so the read-along
    pill stays synced with no post-processing. Exceptions from tts.synthesize
    propagate to the caller (mapped to HTTP status there).
    """
    key = (text, voice_id, language, round(speed, 3))
    hit = _lru_get(key)
    if hit is not None:
        return SynthOutcome(hit.audio_bytes, hit.audio_format, hit.words, hit.aligner, True)

    async with _get_lock():
        hit = _lru_get(key)  # another coroutine may have synthesized it while we waited
        if hit is not None:
            return SynthOutcome(hit.audio_bytes, hit.audio_format, hit.words, hit.aligner, True)
        result = await asyncio.to_thread(tts.synthesize, text, voice_id, language, speed)
        aligner = tts.dominant_aligner(result.aligner_names)
        outcome = SynthOutcome(result.audio_bytes, result.audio_format, result.words, aligner, False)
        _lru_put(key, outcome)
        return outcome
