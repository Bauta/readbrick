// Auto-hide the reader chrome (header + footer) during playback.
//
// Rules:
// - Playing + no interaction for IDLE_MS → hide chrome.
// - Any pointer/key/touch event → show chrome + restart timer if playing.
// - Pause/ended → show chrome immediately, cancel timer.
// - Sheets/toolbars open → force visible (chrome stays up while user interacts).

const IDLE_MS = 3000;

/**
 * @param {object} opts
 * @param {() => boolean} opts.isPaused — closure that returns true when audio is paused/stopped
 * @param {(fn: () => void) => void} opts.addOnPlay — subscribe to engine play callback
 * @param {(fn: () => void) => void} opts.addOnPause — subscribe to engine pause callback
 * @returns {{ markInteraction: () => void }}
 */
export function initChromeAutoHide({ isPaused, addOnPlay, addOnPause }) {
  let hideTimer = null;

  const isAnySheetOpen = () => {
    const settings = document.getElementById('settings-sheet');
    const sidebar = document.getElementById('chapter-sidebar');
    const sleep = document.getElementById('sleep-sheet');
    const quoteToolbar = document.getElementById('quote-toolbar');
    const quotePopover = document.getElementById('quote-popover');
    if (settings && settings.classList.contains('open')) return true;
    if (sidebar && !sidebar.hidden) return true;
    if (sleep && !sleep.hidden) return true;
    if (quoteToolbar && !quoteToolbar.hidden) return true;
    if (quotePopover && !quotePopover.hidden) return true;
    return false;
  };

  const show = () => {
    document.body.classList.remove('chrome-hidden');
  };

  const hide = () => {
    if (isAnySheetOpen()) return;
    if (isPaused()) return;
    document.body.classList.add('chrome-hidden');
  };

  const scheduleHide = () => {
    if (hideTimer !== null) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      hideTimer = null;
      hide();
    }, IDLE_MS);
  };

  const cancelHide = () => {
    if (hideTimer !== null) {
      clearTimeout(hideTimer);
      hideTimer = null;
    }
  };

  const markInteraction = () => {
    show();
    if (!isPaused()) scheduleHide();
  };

  // Engine callbacks (these now replace the `<audio>` element's play/pause events).
  addOnPlay(scheduleHide);
  addOnPause(() => { cancelHide(); show(); });

  // Listeners below are page-lifetime by design — the reader page is loaded
  // fresh on every navigation, so there's nothing to clean up. If reader.js
  // ever moves to SPA-style re-initialization, return a destroy() that calls
  // removeEventListener on the three handlers below.
  document.addEventListener('pointerdown', markInteraction, { capture: true });
  document.addEventListener('keydown', markInteraction, { capture: true });
  document.addEventListener('touchstart', markInteraction, { capture: true, passive: true });

  return { markInteraction };
}
