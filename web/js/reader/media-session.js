// MediaSession → MPRIS bridge.
//
// Chromium republishes navigator.mediaSession on D-Bus as an
// org.mpris.MediaPlayer2 player, which is how the desktop (media keys, the
// Omarchy bar) sees Readbrick. Without this module the browser still publishes
// a player, but a useless one: playback runs on two alternating <audio>
// elements, so the reported duration flips between paragraph clips and the
// status reads "Stopped" in the middle of active reading.
//
// Three rules learned from driving the real bus, all load-bearing:
//
//   1. `album` is the only stable identifier. MPRIS `Identity` is always
//      "Chromium" and `DesktopEntry` is absent, so the app name goes in album
//      and the book title goes in title.
//   2. Duration and position must be book-level. Per-clip values are the bug.
//   3. Never call setPositionState on a timer — it produces a 1 Hz `Seeked`
//      storm on the bus. Paragraph boundaries are the right cadence.

// Matches server/config.py WORDS_PER_MINUTE.
const WORDS_PER_MINUTE = 150;

/** Value published in the `album` slot so a desktop widget can recognise us. */
export const MPRIS_IDENTITY = 'Readbrick';

/**
 * Metadata for one book. Deliberately does NOT include the chapter: chapter
 * changes every paragraph or two, and every metadata write makes the browser
 * re-publish (and re-encode) the artwork, so chapter-level churn is expensive
 * for no gain in a bar widget.
 */
export function buildMetadata(book, coverUrl) {
  return {
    title: book?.title || MPRIS_IDENTITY,
    artist: book?.author || '',
    album: MPRIS_IDENTITY,
    artwork: coverUrl ? [{ src: coverUrl, sizes: '512x512', type: 'image/jpeg' }] : [],
  };
}

/** Running word count BEFORE each paragraph, so index i maps to a position. */
export function cumulativeWords(paragraphs) {
  const out = [];
  let total = 0;
  for (const p of paragraphs) {
    out.push(total);
    total += countWords(p?.text);
  }
  return out;
}

/** Total words in the book — the denominator for every position estimate. */
export function totalWords(paragraphs) {
  let total = 0;
  for (const p of paragraphs) total += countWords(p?.text);
  return total;
}

function countWords(text) {
  if (!text) return 0;
  const trimmed = String(text).trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

/** Whole-book duration in seconds at the given playback rate. */
export function estimateDuration(book, rate) {
  const minutes = book?.est_minutes
    || (book?.word_count ? book.word_count / WORDS_PER_MINUTE : 0);
  if (!minutes) return 0;
  const r = rate > 0 ? rate : 1;
  return (minutes * 60) / r;
}

/** Where paragraph `idx` starts, in seconds into the whole book. */
export function estimatePosition(cumWords, bookWords, durationSec, idx) {
  if (!bookWords || !durationSec) return 0;
  const consumed = cumWords[idx] ?? cumWords[cumWords.length - 1] ?? 0;
  return Math.min(durationSec, (consumed / bookWords) * durationSec);
}

/**
 * Inverse of estimatePosition: which paragraph contains `seconds`. Paragraph
 * granularity is the honest limit — the engine seeks to paragraph starts.
 */
export function paragraphAtPosition(cumWords, bookWords, durationSec, seconds) {
  if (!bookWords || !durationSec || cumWords.length === 0) return 0;
  const targetWords = (Math.max(0, seconds) / durationSec) * bookWords;
  let idx = 0;
  while (idx + 1 < cumWords.length && cumWords[idx + 1] <= targetWords) idx += 1;
  return idx;
}

/**
 * Wire the browser's MediaSession to the reader. Returns a small controller,
 * or a no-op one where MediaSession is unavailable, so callers never branch.
 */
export function initMediaSession({ onPlay, onPause, onPrev, onNext, onSeekBy, onSeekTo }) {
  const ms = globalThis.navigator?.mediaSession;
  if (!ms) return noopController();

  const set = (action, handler) => {
    // Chromium rejects actions it does not implement; one unsupported action
    // must not take the rest down with it.
    try { ms.setActionHandler(action, handler); } catch { /* unsupported */ }
  };

  set('play', onPlay);
  set('pause', onPause);
  set('previoustrack', onPrev);
  set('nexttrack', onNext);
  set('seekbackward', (d) => onSeekBy(-(d?.seekOffset || 15)));
  set('seekforward', (d) => onSeekBy(d?.seekOffset || 15));
  set('seekto', (d) => { if (typeof d?.seekTime === 'number') onSeekTo(d.seekTime); });

  return {
    setBook(book, coverUrl) {
      const MD = globalThis.MediaMetadata;
      if (MD) ms.metadata = new MD(buildMetadata(book, coverUrl));
    },
    // Explicit, so the bus never sees "Stopped" during the gap while the
    // engine swaps from one <audio> element to the next.
    setPlaying(isPlaying) { ms.playbackState = isPlaying ? 'playing' : 'paused'; },
    setPosition(durationSec, positionSec, rate) {
      if (!durationSec || typeof ms.setPositionState !== 'function') return;
      try {
        ms.setPositionState({
          duration: durationSec,
          position: Math.min(positionSec, durationSec),
          playbackRate: rate > 0 ? rate : 1,
        });
      } catch { /* browser rejected the state; not worth breaking playback */ }
    },
    clear() {
      ms.metadata = null;
      ms.playbackState = 'none';
    },
  };
}

function noopController() {
  return {
    setBook() {}, setPlaying() {}, setPosition() {}, clear() {},
  };
}
