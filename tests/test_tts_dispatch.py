from server import tts
from server.tts_backends import BackendSynthResult


def test_synthesize_passes_through_native_words(monkeypatch):
    fake = BackendSynthResult(
        audio_bytes=b"WAV", audio_format="wav", sample_rate=24000,
        words=[{"text": "Hi", "start_ms": 0, "end_ms": 100}], aligner="kokoro",
    )

    class FakeBackend:
        name = "kokoro"

        def synthesize(self, text, voice_id, language="en", speed=1.0):
            return fake

    monkeypatch.setattr("server.tts.get_backend", lambda name: FakeBackend())
    r = tts.synthesize("Hi", "kokoro:af_heart")
    assert r.audio_bytes == b"WAV"
    assert r.audio_format == "wav"
    assert r.words[0]["text"] == "Hi"
    assert r.aligner_names == ["kokoro"]


def test_synthesize_forwards_speed(monkeypatch):
    seen = {}

    class FakeBackend:
        name = "kokoro"

        def synthesize(self, text, voice_id, language="en", speed=1.0):
            seen["speed"] = speed
            return BackendSynthResult(b"X", "wav", 24000, [], "kokoro")

    monkeypatch.setattr("server.tts.get_backend", lambda name: FakeBackend())
    tts.synthesize("Hi", "kokoro:af_heart", "en", 0.75)
    assert seen["speed"] == 0.75


def test_dominant_aligner_picks_strongest():
    assert tts.dominant_aligner(["proportional", "kokoro"]) == "kokoro"
    assert tts.dominant_aligner(["proportional"]) == "proportional"


def test_list_voices_delegates_to_kokoro():
    # KokoroBackend.list_voices is a static list — no container needed.
    ids = [v["voice_id"] for v in tts.list_voices()]
    assert "kokoro:af_heart" in ids
    assert all(v["voice_id"].startswith("kokoro:") for v in tts.list_voices())


def test_install_voice_removed():
    assert not hasattr(tts, "install_voice")
    assert not hasattr(tts, "align_cached_audio")
