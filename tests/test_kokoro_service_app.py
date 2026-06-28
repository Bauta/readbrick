"""HTTP contract tests for the Kokoro container app (no model loaded).

Mirrors test_tts_service_app.py: a FakeSynth is injected via set_synthesizer so
the FastAPI surface is tested without numpy/soundfile/kokoro. The app's
/synthesize anchors source words to the synth's native timings via align.merge.
"""
import base64
import importlib

from fastapi.testclient import TestClient


class FakeSynth:
    sample_rate = 24000

    def synth(self, text, voice, speed=1.0):
        self.last = (text, voice, speed)
        # native per-word timings, in seconds, matching the source words
        return b"WAVDATA", 1000.0, [("Hello", 0.0, 0.5), ("there", 0.5, 1.0)]


def _client(synth):
    app_mod = importlib.import_module("kokoro_service.app")
    app_mod.set_synthesizer(synth)  # inject + mark loaded
    return TestClient(app_mod.app), app_mod


def test_health_503_until_loaded():
    app_mod = importlib.import_module("kokoro_service.app")
    app_mod.reset_for_test()
    client = TestClient(app_mod.app)
    assert client.get("/health").status_code == 503


def test_health_200_after_load():
    client, _ = _client(FakeSynth())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["loaded"] is True
    assert r.json()["sample_rate"] == 24000


def test_voices_lists_english_voices():
    client, _ = _client(FakeSynth())
    r = client.get("/voices")
    assert r.status_code == 200
    voices = r.json()["voices"]
    assert "af_heart" in voices and "bm_george" in voices
    assert len(voices) == 28


def test_synthesize_returns_audio_and_native_words():
    synth = FakeSynth()
    client, _ = _client(synth)
    r = client.post("/synthesize", json={"text": "Hello there", "voice": "af_heart"})
    assert r.status_code == 200
    body = r.json()
    assert base64.b64decode(body["audio_b64"]) == b"WAVDATA"
    assert body["sample_rate"] == 24000
    assert body["format"] == "wav"
    assert body["aligner"] == "kokoro"  # native timings anchored, not proportional
    assert [w["text"] for w in body["words"]] == ["Hello", "there"]
    # ms timings derived from the synth's seconds
    assert body["words"][0]["start_ms"] == 0.0
    assert synth.last == ("Hello there", "af_heart", 1.0)


def test_synthesize_forwards_and_clamps_native_speed():
    synth = FakeSynth()
    client, _ = _client(synth)
    assert client.post("/synthesize", json={"text": "Hi", "voice": "af_heart", "speed": 0.75}).status_code == 200
    assert synth.last[2] == 0.75
    client.post("/synthesize", json={"text": "Hi", "voice": "af_heart", "speed": 5.0})
    assert synth.last[2] == 2.0  # clamped up
    client.post("/synthesize", json={"text": "Hi", "voice": "af_heart", "speed": 0.1})
    assert synth.last[2] == 0.5  # clamped down


def test_synthesize_rejects_unknown_voice():
    client, _ = _client(FakeSynth())
    r = client.post("/synthesize", json={"text": "Hi", "voice": "af_notavoice"})
    assert r.status_code == 400


def test_synthesize_rejects_malformed_voice_name():
    client, _ = _client(FakeSynth())
    r = client.post("/synthesize", json={"text": "Hi", "voice": "../etc/passwd"})
    assert r.status_code == 400


def test_synthesize_rejects_empty_text():
    client, _ = _client(FakeSynth())
    r = client.post("/synthesize", json={"text": "   ", "voice": "af_heart"})
    assert r.status_code == 400


def test_synthesize_defaults_to_af_heart():
    synth = FakeSynth()
    client, _ = _client(synth)
    r = client.post("/synthesize", json={"text": "Hi"})  # no voice → default
    assert r.status_code == 200
    assert synth.last[1] == "af_heart"
