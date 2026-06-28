// Word-following autoscroll for the reader.
//
// During playback, the active word's vertical position is monitored. When it
// leaves the middle 60% of the viewport (the "comfort band"), the reader
// scrolls just enough to bring it back to vertical center. Throttled to avoid
// fighting the 60Hz pill tracker, and suppressed briefly after any manual
// scroll/touch so the user can override.

const COMFORT_BAND_TOP_FRAC = 0.2;
const COMFORT_BAND_BOTTOM_FRAC = 0.8;
const SCROLL_THROTTLE_MS = 400;
const INTERACTION_SUPPRESSION_MS = 1500;
const SMOOTH_SCROLL_SETTLE_MS = 600;
// maybeScroll only nudges when the active word is within this fraction of a
// viewport edge — a safety net for paragraphs taller than the screen, not the
// per-word follow (paragraph-centering on change is the primary behavior).
const EDGE_MARGIN_FRAC = 0.12;

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Decide whether to auto-scroll now.
 *
 * @param {object} args
 * @param {{top: number, bottom: number} | null} args.wordRect — current word's bounding rect (viewport-relative)
 * @param {number} args.viewportHeight — window.innerHeight
 * @param {number} args.lastScrollAt — timestamp of last programmatic scroll
 * @param {number} args.lastInteractionAt — timestamp of last user pointer/wheel/touch event
 * @param {number} args.now — current timestamp (typically Date.now())
 * @returns {boolean}
 */
export function shouldAutoScroll({
  wordRect, viewportHeight, lastScrollAt, lastInteractionAt, now,
}) {
  if (!wordRect) return false;
  if (now - lastScrollAt < SCROLL_THROTTLE_MS) return false;
  if (now - lastInteractionAt < INTERACTION_SUPPRESSION_MS) return false;

  const topThreshold = viewportHeight * COMFORT_BAND_TOP_FRAC;
  const bottomThreshold = viewportHeight * COMFORT_BAND_BOTTOM_FRAC;

  return wordRect.top < topThreshold || wordRect.bottom > bottomThreshold;
}

/**
 * Wire up DOM listeners that track user interaction and expose a tick
 * function that the RAF loop in reader.js can call.
 *
 * @param {object} opts
 * @param {HTMLElement} opts.scrollContainer — the element to monitor for scroll events
 * @returns {{
 *   maybeScroll: () => void,
 * }}
 */
export function initAutoscroll({ scrollContainer }) {
  let lastScrollAt = 0;
  let lastInteractionAt = 0;
  let programmaticScrollGuard = false;

  const markInteraction = () => { lastInteractionAt = Date.now(); };

  // Listeners below are page-lifetime by design — the reader page is loaded
  // fresh on every navigation, so there's nothing to clean up. If reader.js
  // ever moves to SPA-style re-initialization, return a destroy() that calls
  // removeEventListener on the three handlers below.
  //
  // Any user-initiated scroll counts as interaction. The guard distinguishes
  // our own programmatic scroll (via scrollIntoView) from user wheel/drag.
  scrollContainer.addEventListener('wheel', markInteraction, { passive: true });
  scrollContainer.addEventListener('touchstart', markInteraction, { passive: true });
  window.addEventListener('scroll', () => {
    if (programmaticScrollGuard) return;
    markInteraction();
  }, { passive: true });

  const maybeScroll = () => {
    // Per-paragraph centering (scrollToElement, on paragraph change) keeps the
    // reading position centered. This is only a safety net for paragraphs
    // TALLER than the viewport: when the active word drifts to/over an edge,
    // re-center it so a long paragraph's tail doesn't read off-screen. Words
    // comfortably in view never trigger a scroll, so there's no per-word churn.
    const cur = document.querySelector('span.w.current');
    if (!cur) return;
    const r = cur.getBoundingClientRect();
    const vh = window.innerHeight;
    const margin = vh * EDGE_MARGIN_FRAC;
    if (r.top >= margin && r.bottom <= vh - margin) return;  // comfortably in view
    const now = Date.now();
    if (now - lastScrollAt < SCROLL_THROTTLE_MS) return;
    if (now - lastInteractionAt < INTERACTION_SUPPRESSION_MS) return;

    lastScrollAt = now;
    programmaticScrollGuard = true;
    cur.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
    setTimeout(() => { programmaticScrollGuard = false; }, SMOOTH_SCROLL_SETTLE_MS);
  };

  // Smoothly scroll an element to the vertical center, marking the scroll as
  // "ours" so the window.scroll listener doesn't treat it as user interaction
  // (which would suppress autoscroll for 1500ms). Used to center the current
  // paragraph on paragraph change + explicit navigation (paragraph-tap, jump).
  const scrollToElement = (element) => {
    if (!element) return;
    lastScrollAt = Date.now();
    programmaticScrollGuard = true;
    element.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' });
    setTimeout(() => { programmaticScrollGuard = false; }, SMOOTH_SCROLL_SETTLE_MS);
  };

  return { maybeScroll, scrollToElement };
}
