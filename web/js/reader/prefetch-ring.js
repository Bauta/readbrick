// Sliding-window prefetch ring for the audio engine.
//
// Maintains N=5 paragraph slots starting at the current paragraph. Each slot
// is a Promise<{words, audioUrl, duration, aligner?}>. Production wiring
// fetches words + audio URL from /api/tts (the audio is loaded by the
// HTML5 <audio> engine on demand). Tests inject a mock fetcher.
//
// Pure-function logic in audio-scheduling.js (ringSlotsFor) drives the
// window math; this module owns the slot state + async fetching.

import { ringSlotsFor } from './audio-scheduling.js';

/**
 * @param {object} opts
 * @param {number} opts.size — ring size, typically 5
 * @param {number} opts.totalParas — book paragraph count
 * @param {(paraIdx: number) => Promise<{words, audioUrl, duration}>} opts.fetchAndDecode
 */
export function createPrefetchRing({ size, totalParas, fetchAndDecode }) {
  /** @type {Map<number, Promise<object>>} */
  const slots = new Map();
  /** @type {Map<number, object>} — synchronous mirror of resolved slots */
  const resolved = new Map();
  let currentHead = -1;

  function fillSlot(paraIdx) {
    if (slots.has(paraIdx)) return;
    const p = fetchAndDecode(paraIdx);
    slots.set(paraIdx, p);
    // Mirror into `resolved` once the fetch finishes, so onTimeUpdate
    // and word-tap-to-seek can read the words synchronously.
    p.then((val) => {
      // Only mirror if the slot is still in the window — guards against
      // races where the user has already advanced past this paragraph.
      if (slots.has(paraIdx)) resolved.set(paraIdx, val);
    });
  }

  function advance(toParaIdx) {
    if (toParaIdx === currentHead) return;
    currentHead = toParaIdx;
    const target = new Set(ringSlotsFor(toParaIdx, totalParas, size));
    // Drop slots that fell out of the window (revoking their blob URLs so the
    // realtime-synthesized audio doesn't leak object URLs).
    for (const idx of [...slots.keys()]) {
      if (!target.has(idx)) {
        _revoke(idx);
        slots.delete(idx);
        resolved.delete(idx);
      }
    }
    // Fill new slots.
    for (const idx of target) fillSlot(idx);
  }

  // Revoke a resolved slot's blob URL (realtime audio is delivered as object
  // URLs; without this they accumulate for the life of the page).
  function _revoke(paraIdx) {
    const slot = resolved.get(paraIdx);
    if (slot && slot.blobUrl) URL.revokeObjectURL(slot.blobUrl);
  }

  function get(paraIdx) {
    return slots.get(paraIdx);
  }

  function getResolved(paraIdx) {
    return resolved.get(paraIdx) || null;
  }

  async function await_(paraIdx) {
    const slot = slots.get(paraIdx);
    if (!slot) {
      throw new Error(`paragraph ${paraIdx} not in ring (head=${currentHead})`);
    }
    return slot;
  }

  // Drop everything. Used when the voice changes — every slot's audio URL +
  // word timings are tied to the old voice. The next advance() refills the
  // ring with fresh fetches against the new voice.
  function reset() {
    for (const idx of resolved.keys()) _revoke(idx);
    slots.clear();
    resolved.clear();
    currentHead = -1;
  }

  return { advance, get, getResolved, await: await_, reset };
}
