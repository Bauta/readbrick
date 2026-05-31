// Map paragraph-local time → active word index.
//
// Semantics: the currently-highlighted word is the one with the LATEST
// start_ms that does not exceed `ms`. We deliberately do NOT use the
// word's end_ms as an upper bound, because some TTS engines report a word
// `duration` that includes any trailing silence (the
// pause after a comma or period). That makes the previous word's
// reported [start_ms, end_ms] overlap the next word's actual audible
// range, so a naive "first matching range" scan keeps the pill on the
// previous word while the voice has already moved on. "Latest start
// wins" resolves the overlap correctly and also handles gaps (the
// previous word's effective range extends until the next word's
// start_ms).
//
// Returns -1 only when `words` is empty.
export function findCurrentWord(words, ms) {
  if (words.length === 0) return -1;
  if (ms < words[0].start_ms) return 0;
  for (let i = words.length - 1; i >= 0; i--) {
    if (words[i].start_ms <= ms) return i;
  }
  return 0;
}
