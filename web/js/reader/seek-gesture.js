// Double-tap-in-gutter gesture for ±15s audio seeks.
//
// The pure functions in this file (computeGutterZones, classifyTap) are
// unit-tested under tests/ui/. The DOM wiring (initSeekGesture) is exercised
// by the end-to-end smoke at tests/ui/immersive-smoke.mjs.

/**
 * Compute the left/right gutter tap-zones from the current paragraph's
 * horizontal bounds.
 *
 * @param {{left: number, right: number}} paragraphRect
 * @param {{width: number}} viewport
 * @returns {{ left: {x0: number, x1: number}, right: {x0: number, x1: number} }}
 */
export function computeGutterZones(paragraphRect, viewport) {
  return {
    left: { x0: 0, x1: paragraphRect.left },
    right: { x0: paragraphRect.right, x1: viewport.width },
  };
}

function tapSide(x, zones) {
  if (x >= zones.left.x0 && x < zones.left.x1) return 'left';
  if (x >= zones.right.x0 && x < zones.right.x1) return 'right';
  return null;
}

/**
 * Classify a tap given the previous gutter-tap (if any).
 *
 * Returns:
 *   'ignored'      — tap was not in a gutter zone; do nothing.
 *   'first'        — tap was in a gutter; store it as the new prev-tap.
 *   'double-left'  — second tap on left gutter within the window; trigger seek.
 *   'double-right' — second tap on right gutter within the window; trigger seek.
 *
 * @param {{x: number, t: number, side: 'left'|'right'} | null} prevTap
 * @param {{x: number, t: number}} currentTap
 * @param {{ zones: ReturnType<typeof computeGutterZones>, doubleTapWindowMs: number }} opts
 * @returns {'ignored'|'first'|'double-left'|'double-right'}
 */
export function classifyTap(prevTap, currentTap, opts) {
  const side = tapSide(currentTap.x, opts.zones);
  if (side === null) return 'ignored';

  if (
    prevTap &&
    prevTap.side === side &&
    currentTap.t - prevTap.t <= opts.doubleTapWindowMs
  ) {
    return side === 'left' ? 'double-left' : 'double-right';
  }

  return 'first';
}

const DOUBLE_TAP_WINDOW_MS = 400;
const FLASH_DURATION_MS = 600;

/**
 * Wire the double-tap-in-gutter gesture against the DOM.
 *
 * @param {object} opts
 * @param {(delta: number) => void} opts.onSeek — called with -15 or +15
 * @param {HTMLElement} opts.flashLeft — element to flash on -15s
 * @param {HTMLElement} opts.flashRight — element to flash on +15s
 */
export function initSeekGesture({ onSeek, flashLeft, flashRight }) {
  let prevTap = null;

  const currentParagraphRect = () => {
    const p = document.querySelector('.reader-content p[data-idx]');
    if (!p) return null;
    const r = p.getBoundingClientRect();
    return { left: r.left, right: r.right };
  };

  const flash = (side) => {
    const el = side === 'left' ? flashLeft : flashRight;
    el.classList.add('active');
    setTimeout(() => el.classList.remove('active'), FLASH_DURATION_MS);
  };

  document.addEventListener('pointerdown', (e) => {
    const paraRect = currentParagraphRect();
    if (!paraRect) return;
    const zones = computeGutterZones(paraRect, { width: window.innerWidth });

    const result = classifyTap(prevTap, { x: e.clientX, t: e.timeStamp }, {
      zones, doubleTapWindowMs: DOUBLE_TAP_WINDOW_MS,
    });

    if (result === 'ignored') return;

    if (result === 'first') {
      const side = e.clientX < zones.left.x1 ? 'left' : 'right';
      prevTap = { x: e.clientX, t: e.timeStamp, side };
      return;
    }

    // Double-tap detected. preventDefault keeps the synthesized `click`
    // from triggering paragraph/word handlers; no need for
    // stopPropagation since no other pointerdown listener depends on
    // event flow ordering with this one.
    e.preventDefault();
    prevTap = null;
    if (result === 'double-left') {
      onSeek(-15);
      flash('left');
    } else {
      onSeek(+15);
      flash('right');
    }
  }, { capture: true });
}
