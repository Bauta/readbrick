// Diagnostic overlay for pill/voice sync investigation.
//
// Activate by appending ?debug=1 to the reader URL. Shows real-time values
// every RAF tick:
//   - voice + which aligner produced the current paragraph's timings
//   - paragraph index / total
//   - <audio>.currentTime (audible) in ms
//   - prev / CURR / next words with their start/end ms
//
// With the HTML5 <audio> engine there's no latency math to surface —
// audio.currentTime IS the audible position, full stop.

import { findCurrentWord } from './word-tracker.js';

export function initDebugOverlay({ state }) {
  if (new URLSearchParams(location.search).get('debug') !== '1') return null;

  const root = document.createElement('div');
  root.id = 'debug-overlay';
  root.style.cssText = `
    position: fixed; top: 8px; right: 8px; z-index: 99999;
    background: rgba(0, 0, 0, 0.85); color: #eaeaea;
    font: 11px/1.35 ui-monospace, Menlo, Consolas, monospace;
    padding: 8px 10px; border-radius: 6px;
    min-width: 280px; max-width: 360px;
    user-select: none;
    backdrop-filter: blur(4px);
    pointer-events: none;
  `;
  const statsEl = document.createElement('pre');
  statsEl.style.cssText = 'margin: 0; white-space: pre;';
  root.appendChild(statsEl);
  document.body.appendChild(root);

  function fmt(n, digits = 1) {
    if (n === undefined || n === null || Number.isNaN(n)) return '–';
    return Number(n).toFixed(digits);
  }

  function update() {
    const e = state.engine;
    const paraIdx = e ? e.currentParagraphIdx() : -1;
    const slot = (state.prefetchRing && paraIdx >= 0)
      ? state.prefetchRing.getResolved(paraIdx) : null;
    const words = slot?.words || [];

    const rate = e?._rate ? e._rate() : 1;
    const audibleMs = e ? e.currentTime() * 1000 : 0;
    const curIdx = findCurrentWord(words, audibleMs);
    const cur = words[curIdx];
    const prev = words[curIdx - 1];
    const next = words[curIdx + 1];

    function wordLine(label, idx, w) {
      if (!w) return `${label} [${idx}] : –`;
      return `${label} [${idx}] : "${w.text}"  ${fmt(w.start_ms, 0)}–${fmt(w.end_ms, 0)} ms`;
    }

    statsEl.textContent = [
      `voice    : ${state.prefs?.voice_id || '?'}`,
      `aligner  : ${slot?.aligner || '?'}`,
      `para     : ${paraIdx}/${state.paragraphs?.length ?? '?'}    words: ${words.length}`,
      ``,
      `audio.ct : ${fmt(audibleMs, 1)} ms    rate: ${fmt(rate, 2)}x`,
      ``,
      wordLine('prev', curIdx - 1, prev),
      wordLine('CURR', curIdx,     cur),
      wordLine('next', curIdx + 1, next),
    ].join('\n');
  }

  function loop() {
    update();
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);

  return { update };
}
