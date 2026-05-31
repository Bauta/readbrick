// Listening-time tracking: accumulate active-playback seconds and flush
// to the server's progress endpoint every 30s + on pause/ended/unload.
//
// Persists via `api.putProgress(..., seconds_delta)`. The server side
// atomically increments `progress.total_seconds`.
import { api } from '../api.js';
import { state, bookId } from './state.js';

function _flush() {
  if (state.session.startedAt) {
    const now = Date.now();
    state.session.unsavedSeconds += (now - state.session.startedAt) / 1000;
    state.session.startedAt = now;
  }
  const delta = Math.round(state.session.unsavedSeconds);
  if (delta <= 0) return;
  state.session.unsavedSeconds -= delta;
  api.putProgress(state.user.id, bookId, state.curIdx, 0, delta).catch(() => {});
}

function _onPlaying() {
  if (state.session.startedAt) return;
  state.session.startedAt = Date.now();
  state.session.flushTimer = setInterval(_flush, 30000);
}

function _onPause() {
  if (state.session.startedAt) {
    state.session.unsavedSeconds += (Date.now() - state.session.startedAt) / 1000;
    state.session.startedAt = null;
  }
  if (state.session.flushTimer) {
    clearInterval(state.session.flushTimer);
    state.session.flushTimer = null;
  }
  _flush();
}

/** Wire the session-tracking listeners to the engine callbacks. */
export function setupSession({ addOnPlay, addOnPause }) {
  addOnPlay(_onPlaying);
  addOnPause(_onPause);
  window.addEventListener('beforeunload', _onPause);
}
