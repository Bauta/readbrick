// Pure helpers used by audio-engine.js and the prefetch ring.
// No DOM, no AudioContext; unit-tested directly in tests/ui/.

/**
 * Map a global (book-wide) seconds offset to (paragraphIdx, paragraph-local seconds).
 *
 * @param {number[]} durations — duration of each paragraph in seconds
 * @param {number} globalSec — seconds since the very first paragraph started
 * @returns {{ paraIdx: number, localOffset: number }}
 */
export function globalTimeToParagraph(durations, globalSec) {
  let acc = 0;
  for (let i = 0; i < durations.length; i++) {
    const next = acc + durations[i];
    if (globalSec < next) {
      return { paraIdx: i, localOffset: Math.max(0, globalSec - acc) };
    }
    acc = next;
  }
  // Clamp to end of last paragraph.
  const last = durations.length - 1;
  return { paraIdx: last, localOffset: durations[last] };
}

/**
 * The set of paragraph indices that should be kept warm in the prefetch ring.
 * Starts at the current paragraph (so we always have the currently-playing
 * one ready) and extends forward up to ringSize total slots, clamping to
 * the book's last paragraph.
 *
 * @param {number} currentParaIdx
 * @param {number} totalParas
 * @param {number} ringSize
 * @returns {number[]}
 */
export function ringSlotsFor(currentParaIdx, totalParas, ringSize) {
  if (currentParaIdx < 0 || currentParaIdx >= totalParas) return [];
  const slots = [];
  for (let i = 0; i < ringSize; i++) {
    const idx = currentParaIdx + i;
    if (idx >= totalParas) break;
    slots.push(idx);
  }
  return slots;
}
