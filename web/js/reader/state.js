// Reader page shared state. A single mutable object that submodules read
// from and write to. Mirrors the library/state.js pattern.
import { session } from '../api.js';

export const bookId = location.pathname.split('/').pop();

export const SKIP_SECONDS = 15;

export const state = {
  user: session.user,
  book: null,
  paragraphs: [],
  prefs: null,
  voices: [],
  curIdx: 0,
  playing: false,
  curWordIdx: -1,
  engine: null,           // populated in reader.js after AudioContext is created on first play tap
  audioContext: null,
  prefetchRing: null,
  autoscroll: null,       // populated in setupControls after initAutoscroll
  saveTimer: null,
  quotes: [],
  sleepTimer: null,
  session: { startedAt: null, unsavedSeconds: 0, flushTimer: null },
};
