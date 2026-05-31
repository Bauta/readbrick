"""Unit tests for TTS helpers (sentence/word splitting)."""
from __future__ import annotations


def test_split_sentences_basic():
    from server.tts import split_sentences

    s = split_sentences("Hello world. How are you? I am fine!")
    assert s == ["Hello world.", "How are you?", "I am fine!"]


def test_split_sentences_multiple():
    from server.tts import split_sentences

    s = split_sentences("Once upon a time. She went home.")
    assert s == ["Once upon a time.", "She went home."]


def test_split_sentences_empty():
    from server.tts import split_sentences

    assert split_sentences("") == []
    assert split_sentences("   ") == []


def test_tokenize_words():
    from server.tts import tokenize_words

    toks = tokenize_words("Hello world test")
    assert [w for (w, _, _) in toks] == ["Hello", "world", "test"]
