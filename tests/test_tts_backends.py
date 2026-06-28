import pytest


def test_parse_voice_id_with_prefix():
    from server.tts_backends import parse_voice_id
    assert parse_voice_id("kokoro:af_heart") == ("kokoro", "af_heart")
    assert parse_voice_id("kokoro:bm_george") == ("kokoro", "bm_george")


def test_parse_voice_id_unprefixed_defaults_to_kokoro():
    from server.tts_backends import parse_voice_id, DEFAULT_BACKEND
    assert DEFAULT_BACKEND == "kokoro"
    assert parse_voice_id("legacy-thing") == ("kokoro", "legacy-thing")


def test_get_backend_kokoro():
    from server.tts_backends import get_backend
    k = get_backend("kokoro")
    assert k.name == "kokoro"
    assert get_backend("kokoro") is k  # cached


def test_get_backend_unknown_raises():
    from server.tts_backends import get_backend
    with pytest.raises(ValueError):
        get_backend("unknown")
    with pytest.raises(ValueError):
        get_backend("madeup")


def test_all_backend_names():
    from server.tts_backends import all_backend_names
    assert all_backend_names() == ["kokoro"]


def test_backend_synth_result_has_aligner_field():
    from server.tts_backends import BackendSynthResult
    r = BackendSynthResult(audio_bytes=b"x", audio_format="wav", sample_rate=24000,
                           words=[], aligner="kokoro")
    assert r.aligner == "kokoro"
