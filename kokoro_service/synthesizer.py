"""CPU Kokoro-82M synthesizer: text + voice name -> WAV bytes + native word timings.

Kokoro emits exact per-word timestamps from its duration predictor, so we read
them straight off the result tokens — no forced aligner, no GPU.

Heavy deps (kokoro, numpy, soundfile) are imported lazily inside the methods so
the FastAPI app module and the pure unit tests can import this package without
them installed — matching the tts_service convention.
"""
from __future__ import annotations

import io

SAMPLE_RATE = 24000

# The 28 English voices shipped by hexgrad/Kokoro-82M (v1.0). Authoritative list,
# baked into the image. Kept in sync with server/tts_backends/kokoro.py
# ENGLISH_VOICES (separate deployment units, so duplicated by necessity — a
# runtime check in the integration test asserts parity against /voices).
ENGLISH_VOICES: list[str] = [
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
    "am_onyx", "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]


def available_voices() -> list[str]:
    return list(ENGLISH_VOICES)


def lang_code(voice: str) -> str:
    """Kokoro pipeline language code: voice prefix 'a' = American, 'b' = British."""
    return voice[0] if voice[:1] in ("a", "b") else "a"


def _token_words(tokens, offset_s: float) -> list[tuple[str, float, float]]:
    """Map Kokoro result tokens -> [(word, start_s, end_s)], shifted by offset_s.

    Keeps only tokens that carry timestamps and at least one alphanumeric char,
    dropping standalone punctuation tokens (which would clutter the pill).
    """
    out: list[tuple[str, float, float]] = []
    for t in tokens or []:
        w = (getattr(t, "text", "") or "").strip()
        s = getattr(t, "start_ts", None)
        e = getattr(t, "end_ts", None)
        if w and s is not None and e is not None and any(ch.isalnum() for ch in w):
            out.append((w, offset_s + float(s), offset_s + float(e)))
    return out


class KokoroSynthesizer:
    sample_rate = SAMPLE_RATE

    def __init__(self, pipeline_factory=None) -> None:
        # Lazy import so tests can inject a fake factory without the model/deps.
        if pipeline_factory is None:
            from kokoro import KPipeline

            def pipeline_factory(lc: str):
                return KPipeline(lang_code=lc)

        self._factory = pipeline_factory
        self._pipes: dict[str, object] = {}

    def _pipe(self, lc: str):
        if lc not in self._pipes:
            self._pipes[lc] = self._factory(lc)
        return self._pipes[lc]

    def _synthesize_pcm(self, text: str, voice: str, speed: float = 1.0):
        """Run Kokoro → (samples: float32 mono ndarray, duration_ms, words).

        `speed` is Kokoro's native rate knob (0.5 = slower, 2.0 = faster): the
        model generates speech at that pace (natural prosody, pitch preserved —
        not time-stretch) and the per-word timestamps come out matching, so the
        read-along pill stays synced with no extra math.

        Concatenates per-chunk audio and accumulates each chunk's token
        timestamps by the cumulative duration of the chunks before it, so a
        multi-chunk paragraph yields globally-correct word starts. numpy-only
        (no soundfile) so the timing logic is unit-testable on the host venv.
        """
        import numpy as np

        pipe = self._pipe(lang_code(voice))
        chunks: list = []
        words: list[tuple[str, float, float]] = []
        offset_s = 0.0
        for r in pipe(text, voice=voice, speed=speed):
            audio = getattr(r, "audio", None)
            if audio is None:
                continue
            arr = (
                audio.detach().cpu().numpy()
                if hasattr(audio, "detach")
                else np.asarray(audio)
            )
            arr = np.asarray(arr, dtype=np.float32).reshape(-1)
            words.extend(_token_words(getattr(r, "tokens", None), offset_s))
            offset_s += len(arr) / SAMPLE_RATE
            chunks.append(arr)
        full = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        return full, (len(full) / SAMPLE_RATE) * 1000.0, words

    def synth(
        self, text: str, voice: str, speed: float = 1.0
    ) -> tuple[bytes, float, list[tuple[str, float, float]]]:
        """Return (wav_bytes, duration_ms, [(word, start_s, end_s), ...])."""
        import soundfile as sf

        full, dur_ms, words = self._synthesize_pcm(text, voice, speed)
        buf = io.BytesIO()
        sf.write(buf, full, SAMPLE_RATE, format="WAV", subtype="PCM_16")
        return buf.getvalue(), dur_ms, words
