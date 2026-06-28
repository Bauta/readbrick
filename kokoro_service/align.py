"""Word-timing alignment for the Kokoro TTS container.

Kokoro emits per-word timestamps from its own duration predictor, but its
tokenization (punctuation as separate tokens, contraction/hyphen handling)
rarely lines up 1:1 with the reader's SOURCE tokenization (what the pill
highlights on screen). So we Needleman-Wunsch-align the *normalized* sequences,
anchor each source word to Kokoro's real timestamp where they correspond, and
interpolate the rest. Source spelling is always preserved; only timings come
from Kokoro. Pure functions, no heavy deps — unit-testable outside the image.

This is a verbatim copy of tts_service/align.py (different deployment unit /
image, so it cannot import across container boundaries). Keep the two in sync.
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"\S+")
# Keep letters (incl. accented) + digits; drop punctuation/quotes.
_NORM_RE = re.compile(r"[^0-9a-zà-öø-ÿ]+")

# Below this fraction of source words anchored to an equal aligner word, the
# alignment is too weak to trust → fall back to even (proportional) spacing.
_MIN_ANCHOR_FRACTION = 0.5


def tokenize(text: str) -> list[str]:
    return [m.group() for m in _WORD_RE.finditer(text)]


def _norm(w: str) -> str:
    return _NORM_RE.sub("", w.lower())


def _proportional(source_words: list[str], audio_dur_ms: float) -> list[dict]:
    n = len(source_words)
    if n == 0:
        return []
    slot = audio_dur_ms / n
    return [
        {"text": w, "start_ms": round(i * slot, 1), "end_ms": round((i + 1) * slot, 1)}
        for i, w in enumerate(source_words)
    ]


def _nw_anchor(src_n: list[str], wsp_n: list[str]) -> list[int]:
    """Needleman-Wunsch align two normalized token lists.

    Returns anchor[i] = the aligner index aligned to source word i, or -1 if
    source word i aligns to a gap (deletion).
    """
    n, m = len(src_n), len(wsp_n)
    GAP, MATCH, MISS = -1, 2, -1
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * GAP
    for j in range(1, m + 1):
        dp[0][j] = j * GAP
    for i in range(1, n + 1):
        si = src_n[i - 1]
        for j in range(1, m + 1):
            sc = MATCH if si and si == wsp_n[j - 1] else MISS
            dp[i][j] = max(dp[i - 1][j - 1] + sc, dp[i - 1][j] + GAP, dp[i][j - 1] + GAP)
    anchor = [-1] * n
    i, j = n, m
    while i > 0 and j > 0:
        si = src_n[i - 1]
        is_match = bool(si) and si == wsp_n[j - 1]
        diag = dp[i - 1][j - 1] + (MATCH if is_match else MISS)
        # Prefer a real match. Otherwise resolve ties toward consuming the later
        # aligner word as an insertion (left move) so a source word that the
        # aligner split into several anchors to the FIRST sub-token, not the last.
        if is_match and dp[i][j] == diag:
            anchor[i - 1] = j - 1
            i -= 1
            j -= 1
        elif dp[i][j] == dp[i][j - 1] + GAP:
            j -= 1
        elif dp[i][j] == dp[i - 1][j] + GAP:
            i -= 1
        else:  # diagonal substitution
            anchor[i - 1] = j - 1
            i -= 1
            j -= 1
    return anchor


def merge(
    source_words: list[str],
    aligner_words: list[tuple[str, float, float]],
    audio_dur_ms: float,
    source_aligner: str = "kokoro",
) -> tuple[list[dict], str]:
    """Return (words, aligner_name).

    source_words: the source tokenization (spelling preserved in the output).
    aligner_words: [(text, start_s, end_s), ...] timings to anchor against.
    source_aligner: name of the aligner that produced `aligner_words` (e.g.
        "kokoro"). Returned as aligner_name when anchoring succeeds; a too-weak
        alignment still falls back to "proportional".
    """
    if not source_words:
        return [], "proportional"
    if not aligner_words:
        return _proportional(source_words, audio_dur_ms), "proportional"

    src_n = [_norm(w) for w in source_words]
    wsp_n = [_norm(t) for (t, _s, _e) in aligner_words]
    anchor = _nw_anchor(src_n, wsp_n)

    # Trust the alignment only if enough source words anchored to an EQUAL
    # aligner token (NW substitutions don't count as real anchors).
    nonempty = sum(1 for s in src_n if s)
    good = sum(1 for i, a in enumerate(anchor) if a >= 0 and src_n[i] and src_n[i] == wsp_n[a])
    if nonempty == 0 or good < _MIN_ANCHOR_FRACTION * nonempty:
        return _proportional(source_words, audio_dur_ms), "proportional"

    dur_s = audio_dur_ms / 1000.0
    n = len(source_words)
    starts: list[float | None] = [None] * n
    for i, a in enumerate(anchor):
        if a >= 0:
            starts[i] = float(aligner_words[a][1])

    # Interpolate unanchored starts between known anchors (virtual endpoints at
    # 0.0 before the first word and dur_s after the last), linearly by index.
    known = [(-1, 0.0)] + [(i, s) for i, s in enumerate(starts) if s is not None] + [(n, dur_s)]
    for (i0, s0), (i1, s1) in zip(known, known[1:]):
        span = i1 - i0
        for i in range(i0 + 1, i1):
            if starts[i] is None:
                starts[i] = s0 + (s1 - s0) * ((i - i0) / span)

    # Enforce monotonic non-decreasing starts.
    for i in range(1, n):
        if starts[i] < starts[i - 1]:  # type: ignore[operator]
            starts[i] = starts[i - 1]

    # Each word ends where the next begins; the last extends to the clip end.
    out: list[dict] = []
    for i, w in enumerate(source_words):
        st = float(starts[i])  # type: ignore[arg-type]
        en = float(starts[i + 1]) if i + 1 < n else dur_s  # type: ignore[arg-type]
        if en < st:
            en = st
        out.append({"text": w, "start_ms": round(st * 1000, 1), "end_ms": round(en * 1000, 1)})
    return out, source_aligner
