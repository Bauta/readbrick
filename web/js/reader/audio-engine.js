// HTML5 <audio>-based playback engine.
//
// Replaces the previous Web Audio API engine (which gave sample-accurate
// paragraph chaining at the cost of inaccurate currentTime — the
// AudioContext rendering clock isn't the audible clock, and on Linux audio
// stacks the outputLatency reading is unreliable).
//
// The HTML5 <audio> element's `currentTime` is, by spec and in practice,
// the AUDIBLE playback position. The pill computed against it tracks the
// voice without any latency math, padding compensation, or per-device
// calibration.
//
// Trade-off: paragraph crossings are not sample-accurate. Two <audio>
// elements alternate (preload-then-swap) so the gap stays small (~10-50ms
// in practice, usually masked by natural reading pauses).
//
// Public API: unchanged from the previous engine — drop-in replacement.
//   engine.play() / pause() / seek(paraIdx, localSec) / skip(deltaSec)
//   engine.setRate(rate) / currentTime() / currentParagraphIdx() / isPaused()
//   engine.destroy()
//   engine.onPlay / onPause / onParagraphChange callback setters
//   engine._rate()              — debug probe; current playbackRate

import { globalTimeToParagraph } from './audio-scheduling.js';

export function createAudioEngine({
  prefetchRing,
  getTotalParas,
  getDurations,
}) {
  // Two alternating elements. The "active" one is currently playing (or
  // about to); the "next" one is preloaded with paraIdx+1.
  /** @type {[HTMLAudioElement, HTMLAudioElement]} */
  const els = [_makeAudioEl(), _makeAudioEl()];
  let activeSlot = 0;  // 0 or 1 — which element is currently active

  let paused = true;
  let playbackRate = 1.0;
  // Paragraph-local position to (re)start from on play().
  let resumeParaIdx = 0;
  let resumeLocalSec = 0;
  // The paraIdx currently loaded in each <audio> element (or -1 if none).
  const elParaIdx = [-1, -1];
  // The paraIdx currently audible. Updated on swap.
  let currentParaIdx = 0;

  let onPlay = () => {};
  let onPause = () => {};
  let onParagraphChange = () => {};

  function _makeAudioEl() {
    const el = document.createElement('audio');
    el.preload = 'auto';
    // Keep pitch natural if the element's playbackRate is ever changed; the
    // pill stays synced because it tracks the element's media-time currentTime,
    // which is independent of playbackRate.
    el.preservesPitch = true;
    // Keep elements out of the visual layout; they're driven programmatically.
    el.style.position = 'absolute';
    el.style.width = '0';
    el.style.height = '0';
    el.style.left = '-10000px';
    el.setAttribute('aria-hidden', 'true');
    document.body.appendChild(el);
    return el;
  }

  function _active() { return els[activeSlot]; }
  function _next()   { return els[1 - activeSlot]; }

  // Load the audio URL for paraIdx into the given element, if not already.
  // Returns a promise that resolves when metadata is loaded enough to seek
  // and play (`canplay` event). Rejects on out-of-range or fetch failure.
  async function _loadInto(paraIdx, el, slotIdx) {
    if (paraIdx >= getTotalParas() || paraIdx < 0) {
      throw new Error('out of range');
    }
    const ringSlot = await prefetchRing.await(paraIdx);
    // Absolute URL so the element doesn't have to resolve against the page.
    const url = new URL(ringSlot.audioUrl, location.href).toString();
    // Reload when the URL changed even if the paragraph index matches: a voice
    // or speed change rebinds the same paragraph to a freshly-synthesized audio
    // URL (a new blob), so keying on paraIdx alone would replay stale audio.
    if (elParaIdx[slotIdx] === paraIdx && el.src === url) return;
    el.src = url;
    elParaIdx[slotIdx] = paraIdx;
    // Wait until at least canplay so seeking on currentTime is accurate.
    if (el.readyState < 3) {
      await new Promise((resolve, reject) => {
        const onReady = () => { cleanup(); resolve(undefined); };
        const onErr = () => { cleanup(); reject(new Error('audio load failed')); };
        function cleanup() {
          el.removeEventListener('canplay', onReady);
          el.removeEventListener('error', onErr);
        }
        el.addEventListener('canplay', onReady, { once: true });
        el.addEventListener('error', onErr, { once: true });
      });
    }
  }

  // Wire each element's `ended` event to advance the chain.
  for (let i = 0; i < els.length; i++) {
    const slotIdx = i;
    els[i].addEventListener('ended', () => {
      if (paused) return;
      if (slotIdx !== activeSlot) return;  // ended on the wrong element
      _onActiveEnded();
    });
  }

  async function _onActiveEnded() {
    const nextParaIdx = currentParaIdx + 1;
    if (nextParaIdx >= getTotalParas()) {
      // End of book.
      paused = true;
      resumeParaIdx = currentParaIdx;
      resumeLocalSec = _active().duration || 0;
      onPause();
      return;
    }

    // Swap roles: next element becomes active.
    activeSlot = 1 - activeSlot;
    currentParaIdx = nextParaIdx;
    onParagraphChange(currentParaIdx);
    prefetchRing.advance(currentParaIdx);

    const active = _active();
    try {
      // Preloaded already by the previous setup; ensure it's loaded if not.
      if (elParaIdx[activeSlot] !== currentParaIdx) {
        await _loadInto(currentParaIdx, active, activeSlot);
        if (paused) return;
      }
      active.currentTime = 0;
      active.playbackRate = playbackRate;
      await active.play();
    } catch (_e) {
      paused = true;
      onPause();
      return;
    }

    // Kick off preload of paraIdx+1 on the other element.
    _preloadAhead(currentParaIdx + 1);
  }

  async function _preloadAhead(paraIdx) {
    if (paraIdx >= getTotalParas()) return;
    const el = _next();
    const slotIdx = 1 - activeSlot;
    el.pause();
    try {
      await _loadInto(paraIdx, el, slotIdx);
      el.currentTime = 0;
    } catch (_e) { /* swallow; we'll retry when the active ends */ }
  }

  async function play() {
    if (!paused) return;
    paused = false;
    currentParaIdx = resumeParaIdx;
    onPlay();
    // Seed the prefetch ring at the resume position. Without this, the
    // ring is empty and _loadInto's prefetchRing.await() throws — and we
    // also lose the head-start fetch on paragraphs N+1..N+4 that lets the
    // chain stay seamless.
    prefetchRing.advance(currentParaIdx);
    const active = _active();
    try {
      await _loadInto(currentParaIdx, active, activeSlot);
      if (paused) return;
      active.currentTime = resumeLocalSec;
      active.playbackRate = playbackRate;
      await active.play();
    } catch (_e) {
      // Autoplay refused, decode failed, or torn down mid-await.
      paused = true;
      onPause();
      return;
    }
    _preloadAhead(currentParaIdx + 1);
  }

  function pause() {
    if (paused) return;
    paused = true;
    resumeParaIdx = currentParaIdx;
    resumeLocalSec = _active().currentTime;
    _active().pause();
    _next().pause();
    onPause();
  }

  function seek(paraIdx, localSec) {
    const wasPlaying = !paused;
    paused = true;
    _active().pause();
    _next().pause();
    resumeParaIdx = paraIdx;
    resumeLocalSec = Math.max(0, localSec);
    currentParaIdx = paraIdx;
    // Seed the ring at the new position so the next play() doesn't have
    // to fetch from cold.
    prefetchRing.advance(paraIdx);
    if (wasPlaying) play();
    else onParagraphChange(paraIdx);
  }

  function skip(deltaSec) {
    const durations = getDurations();
    let globalSec = 0;
    for (let i = 0; i < currentParaIdx; i++) globalSec += durations[i] || 0;
    globalSec += _active().currentTime || resumeLocalSec || 0;
    const target = Math.max(0, globalSec + deltaSec);
    const { paraIdx, localOffset } = globalTimeToParagraph(durations, target);
    seek(paraIdx, localOffset);
  }

  function setRate(rate) {
    playbackRate = rate;
    _active().playbackRate = rate;
    _next().playbackRate = rate;
  }

  function currentTime() {
    if (paused) return resumeLocalSec;
    return _active().currentTime;
  }

  function currentParagraphIdx() {
    return currentParaIdx;
  }

  function isPaused() {
    return paused;
  }

  function destroy() {
    for (const el of els) {
      try { el.pause(); } catch {}
      try { el.removeAttribute('src'); el.load(); } catch {}
      try { el.remove(); } catch {}
    }
  }

  const engine = {
    play, pause, seek, skip, setRate,
    currentTime, currentParagraphIdx, isPaused, destroy,
    _rate: () => playbackRate,
  };
  Object.defineProperty(engine, 'onPlay',
    { get: () => onPlay, set: (fn) => { onPlay = fn || (() => {}); } });
  Object.defineProperty(engine, 'onPause',
    { get: () => onPause, set: (fn) => { onPause = fn || (() => {}); } });
  Object.defineProperty(engine, 'onParagraphChange',
    { get: () => onParagraphChange, set: (fn) => { onParagraphChange = fn || (() => {}); } });
  return engine;
}
