"""Tests for the Kokoro HTTP backend (main server side)."""
import base64

import pytest

from server.tts_backends.kokoro import ENGLISH_VOICES, KokoroBackend, _label


def test_list_voices_exposes_all_english_voices():
    voices = KokoroBackend().list_voices()
    assert len(voices) == len(ENGLISH_VOICES) == 28
    ids = [v["voice_id"] for v in voices]
    assert "kokoro:af_heart" in ids
    assert "kokoro:bm_george" in ids
    assert all(v["voice_id"].startswith("kokoro:") for v in voices)
    assert all(v["language"] == "en" for v in voices)
    assert all(v["backend"] == "kokoro" for v in voices)
    assert all(v["label"] for v in voices)


def test_label_is_human_readable():
    assert _label("af_heart") == "Heart — US English (female)"
    assert _label("am_michael") == "Michael — US English (male)"
    assert _label("bf_emma") == "Emma — UK English (female)"
    assert _label("bm_george") == "George — UK English (male)"


def _fake_post(captured, *, aligner="kokoro"):
    def post(url, json, timeout):
        captured.update(json)
        captured["url"] = url

        class _R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "audio_b64": base64.b64encode(b"WAV").decode(),
                    "format": "wav",
                    "sample_rate": 24000,
                    "words": [{"text": "Hello", "start_ms": 0, "end_ms": 500}],
                    "aligner": aligner,
                }

        return _R()

    return post


def test_synthesize_strips_prefix_and_returns_native_words(monkeypatch):
    monkeypatch.setattr("server.kokoro_lifecycle.ensure_up", lambda: None)
    captured = {}
    monkeypatch.setattr("server.tts_backends.kokoro.httpx.post", _fake_post(captured))
    r = KokoroBackend().synthesize("Hello", "kokoro:am_michael", "en")
    assert captured["voice"] == "am_michael"
    assert captured["language_id"] == "en"
    assert r.audio_bytes == b"WAV"
    assert r.audio_format == "wav"
    assert r.sample_rate == 24000
    assert r.aligner == "kokoro"
    assert r.words[0]["text"] == "Hello"


def test_synthesize_unknown_voice_falls_back_to_default(monkeypatch):
    monkeypatch.setattr("server.kokoro_lifecycle.ensure_up", lambda: None)
    captured = {}
    monkeypatch.setattr("server.tts_backends.kokoro.httpx.post", _fake_post(captured))
    KokoroBackend().synthesize("Hi", "kokoro:zz_nope", "en")
    assert captured["voice"] == "af_heart"


def test_synthesize_network_error_raises_runtimeerror(monkeypatch):
    monkeypatch.setattr("server.kokoro_lifecycle.ensure_up", lambda: None)

    def boom(url, json, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr("server.tts_backends.kokoro.httpx.post", boom)
    with pytest.raises(RuntimeError, match="Kokoro synthesis failed"):
        KokoroBackend().synthesize("Hi", "kokoro:af_heart", "en")
