import asyncio

import pytest

from server.tts import SynthResult


@pytest.fixture(autouse=True)
def _clear_lru():
    from server import synth_service
    synth_service.reset_cache()
    yield
    synth_service.reset_cache()


def test_synthesize_calls_backend_and_returns_audio(monkeypatch):
    from server import synth_service
    calls = {"n": 0}

    def fake(text, voice_id, language="en", speed=1.0):
        calls["n"] += 1
        return SynthResult(b"WAV", "wav", [{"text": "Hi", "start_ms": 0, "end_ms": 10}], ["kokoro"])

    monkeypatch.setattr("server.tts.synthesize", fake)
    out = asyncio.run(synth_service.synthesize("Hi", "kokoro:af_heart", "en", 1.0))
    assert out.audio_bytes == b"WAV"
    assert out.audio_format == "wav"
    assert out.aligner == "kokoro"
    assert out.words[0]["text"] == "Hi"
    assert out.from_cache is False
    assert calls["n"] == 1


def test_repeat_request_hits_lru(monkeypatch):
    from server import synth_service
    calls = {"n": 0}

    def fake(text, voice_id, language="en", speed=1.0):
        calls["n"] += 1
        return SynthResult(b"WAV", "wav", [{"text": "Hi", "start_ms": 0, "end_ms": 10}], ["kokoro"])

    monkeypatch.setattr("server.tts.synthesize", fake)

    async def go():
        a = await synth_service.synthesize("Hi", "kokoro:af_heart", "en", 0.75)
        b = await synth_service.synthesize("Hi", "kokoro:af_heart", "en", 0.75)
        return a, b

    a, b = asyncio.run(go())
    assert a.from_cache is False and b.from_cache is True   # second served from LRU
    assert calls["n"] == 1                                  # no re-synth on the repeat
    assert b.audio_bytes == a.audio_bytes


def test_different_speed_is_a_different_key(monkeypatch):
    from server import synth_service
    calls = {"n": 0}

    def fake(text, voice_id, language="en", speed=1.0):
        calls["n"] += 1
        return SynthResult(b"X", "wav", [], ["kokoro"])

    monkeypatch.setattr("server.tts.synthesize", fake)

    async def go():
        await synth_service.synthesize("Hi", "kokoro:af_heart", "en", 1.0)
        await synth_service.synthesize("Hi", "kokoro:af_heart", "en", 0.75)

    asyncio.run(go())
    assert calls["n"] == 2  # speed is part of the cache identity


def test_synthesize_forwards_speed(monkeypatch):
    from server import synth_service
    seen = {}

    def fake(text, voice_id, language="en", speed=1.0):
        seen["speed"] = speed
        return SynthResult(b"X", "wav", [], ["kokoro"])

    monkeypatch.setattr("server.tts.synthesize", fake)
    asyncio.run(synth_service.synthesize("Hi", "kokoro:af_heart", "en", 0.75))
    assert seen["speed"] == 0.75


def test_synthesize_propagates_errors(monkeypatch):
    from server import synth_service

    def boom(text, voice_id, language="en", speed=1.0):
        raise RuntimeError("container not ready")

    monkeypatch.setattr("server.tts.synthesize", boom)
    with pytest.raises(RuntimeError, match="container not ready"):
        asyncio.run(synth_service.synthesize("Hi", "kokoro:af_heart"))
