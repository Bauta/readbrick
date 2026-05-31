// Sleep timer: tap Sleep → pick duration / End of chapter → audio
// pauses when the timer fires. Tap active timer to cancel.
//
// `pause()` (the audio-pause function) is injected because it lives
// in reader.js's playback core. The exported `checkChapterFire`
// callback is invoked by reader.js's advanceParagraph hook.
import { toast } from '../api.js';
import { state } from './state.js';

const $ = (sel) => document.querySelector(sel);

function _lastParaIdxOfCurrentChapter() {
  if (!state.book || !state.book.chapters) return state.paragraphs.length - 1;
  for (const ch of state.book.chapters) {
    if (!ch.paragraphs || ch.paragraphs.length === 0) continue;
    const first = ch.paragraphs[0].idx;
    const last = ch.paragraphs[ch.paragraphs.length - 1].idx;
    if (state.curIdx >= first && state.curIdx <= last) return last;
  }
  return state.paragraphs.length - 1;
}

function _formatRemaining(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function _renderButton() {
  const btn = $('#sleep-btn');
  if (!btn) return;
  if (!state.sleepTimer) {
    btn.textContent = 'Sleep';
    btn.classList.remove('active');
    return;
  }
  btn.classList.add('active');
  if (state.sleepTimer.mode === 'duration') {
    btn.textContent = _formatRemaining(state.sleepTimer.endsAt - Date.now());
  } else if (state.sleepTimer.mode === 'chapter') {
    btn.textContent = 'chapter';
  }
}

function _closeSheet() {
  const sheet = $('#sleep-sheet');
  sheet.classList.remove('open');
  setTimeout(() => { sheet.hidden = true; }, 240);
}

/**
 * Wire the sleep timer. `pauseAudio` is injected so this module
 * doesn't depend on reader.js's playback internals.
 */
export function setupSleepTimer({ pauseAudio }) {
  const fire = () => {
    if (!state.sleepTimer) return;
    if (state.sleepTimer.intervalId) clearInterval(state.sleepTimer.intervalId);
    state.sleepTimer = null;
    pauseAudio();
    _renderButton();
    toast('Sleep timer — paused');
  };

  const start = (spec) => {
    if (state.sleepTimer && state.sleepTimer.intervalId) {
      clearInterval(state.sleepTimer.intervalId);
    }
    if (spec.mode === 'duration') {
      const endsAt = Date.now() + spec.minutes * 60 * 1000;
      state.sleepTimer = { mode: 'duration', endsAt, intervalId: null };
      state.sleepTimer.intervalId = setInterval(() => {
        if (!state.sleepTimer) return;
        if (Date.now() >= state.sleepTimer.endsAt) {
          fire();
        } else {
          _renderButton();
        }
      }, 1000);
    } else if (spec.mode === 'chapter') {
      const endParaIdx = _lastParaIdxOfCurrentChapter();
      state.sleepTimer = { mode: 'chapter', endParaIdx };
    }
    _renderButton();
  };

  const cancel = () => {
    if (!state.sleepTimer) return;
    if (state.sleepTimer.intervalId) clearInterval(state.sleepTimer.intervalId);
    state.sleepTimer = null;
    _renderButton();
    toast('Sleep timer cancelled');
  };

  const btn = $('#sleep-btn');
  const sheet = $('#sleep-sheet');

  btn.addEventListener('click', () => {
    if (state.sleepTimer) { cancel(); return; }
    sheet.hidden = false;
    requestAnimationFrame(() => sheet.classList.add('open'));
  });

  sheet.querySelectorAll('button[data-sleep]').forEach((b) => {
    b.addEventListener('click', () => {
      const val = b.dataset.sleep;
      if (val === 'chapter') start({ mode: 'chapter' });
      else start({ mode: 'duration', minutes: parseInt(val, 10) });
      _closeSheet();
    });
  });

  $('#sleep-cancel').addEventListener('click', _closeSheet);

  // Called from advanceParagraph in reader.js.
  return {
    checkChapterFire: () => {
      if (!state.sleepTimer || state.sleepTimer.mode !== 'chapter') return;
      if (state.curIdx >= state.sleepTimer.endParaIdx) fire();
    },
  };
}
