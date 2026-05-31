"""Unit tests for the Kokoro synthesizer's native-timestamp mapping.

The valuable logic — turning Kokoro result tokens into globally-offset word
timings — is exercised here without loading the model. The WAV byte encoding
(soundfile) is verified at runtime against the live container.
"""
import pytest

from kokoro_service.synthesizer import (
    ENGLISH_VOICES,
    KokoroSynthesizer,
    _token_words,
    available_voices,
    lang_code,
)


class _Tok:
    def __init__(self, text, start_ts, end_ts):
        self.text = text
        self.start_ts = start_ts
        self.end_ts = end_ts


class _Res:
    def __init__(self, audio, tokens):
        self.audio = audio
        self.tokens = tokens


def test_english_voices_is_the_28_v1_voices():
    assert len(ENGLISH_VOICES) == 28
    assert len(set(ENGLISH_VOICES)) == 28
    # every name is <region><gender>_<name>, region a|b, gender f|m
    assert all(v[0] in ("a", "b") and v[1] in ("f", "m") and v[2] == "_" for v in ENGLISH_VOICES)
    assert "af_heart" in ENGLISH_VOICES and "bm_george" in ENGLISH_VOICES


def test_available_voices_returns_a_copy():
    a = available_voices()
    assert a == ENGLISH_VOICES
    a.append("zz_bogus")
    assert "zz_bogus" not in ENGLISH_VOICES  # mutating the copy doesn't leak


def test_lang_code_from_voice_prefix():
    assert lang_code("af_heart") == "a"
    assert lang_code("am_michael") == "a"
    assert lang_code("bf_emma") == "b"
    assert lang_code("bm_george") == "b"
    assert lang_code("weird") == "a"  # unknown prefix → American default


def test_token_words_keeps_words_drops_punctuation_and_whitespace():
    toks = [_Tok("It", 0.25, 0.36), _Tok(",", 0.36, 0.40),
            _Tok("was", 0.40, 0.55), _Tok(" ", None, None)]
    out = _token_words(toks, 0.0)
    assert [w for w, _, _ in out] == ["It", "was"]
    assert out[0] == ("It", 0.25, 0.36)


def test_token_words_applies_offset():
    out = _token_words([_Tok("two", 0.1, 0.5)], 3.0)
    assert out == [("two", pytest.approx(3.1), pytest.approx(3.5))]


def test_token_words_skips_tokens_missing_timestamps():
    toks = [_Tok("hi", None, 0.5), _Tok("yo", 0.1, None), _Tok("ok", 0.2, 0.6)]
    assert [w for w, _, _ in _token_words(toks, 0.0)] == ["ok"]


def test_token_words_handles_none_token_list():
    assert _token_words(None, 0.0) == []


def test_synthesize_pcm_accumulates_offset_across_chunks():
    np = pytest.importorskip("numpy")
    sr = 24000

    def fake_factory(_lc):
        def pipe(_text, voice, speed=1.0):
            # two 1-second chunks; second chunk's token starts at 0.2s locally
            yield _Res(np.zeros(sr, dtype=np.float32), [_Tok("one", 0.1, 0.5)])
            yield _Res(np.zeros(sr, dtype=np.float32), [_Tok("two", 0.2, 0.6)])
        return pipe

    s = KokoroSynthesizer(pipeline_factory=fake_factory)
    full, dur_ms, words = s._synthesize_pcm("one two", "af_heart")
    assert len(full) == 2 * sr
    assert dur_ms == pytest.approx(2000.0, abs=1.0)
    assert [w for w, _, _ in words] == ["one", "two"]
    assert words[0][1] == pytest.approx(0.1)
    assert words[1][1] == pytest.approx(1.2)  # 0.2 local + 1.0s of prior chunk


def test_synthesize_pcm_empty_output_is_safe():
    np = pytest.importorskip("numpy")

    def fake_factory(_lc):
        def pipe(_text, voice, speed=1.0):
            return iter(())  # model yielded nothing
        return pipe

    full, dur_ms, words = KokoroSynthesizer(pipeline_factory=fake_factory)._synthesize_pcm("", "af_heart")
    assert len(full) == 0 and dur_ms == 0.0 and words == []


def test_synthesize_pcm_forwards_native_speed_to_pipeline():
    np = pytest.importorskip("numpy")
    seen = {}

    def fake_factory(_lc):
        def pipe(_text, voice, speed=1.0):
            seen["speed"] = speed
            yield _Res(np.zeros(100, dtype=np.float32), [])
        return pipe

    KokoroSynthesizer(pipeline_factory=fake_factory)._synthesize_pcm("hi", "af_heart", 0.75)
    assert seen["speed"] == 0.75
