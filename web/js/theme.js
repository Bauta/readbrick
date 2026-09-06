// Theme selection shared by the library and the reader.
//
// The two pages used to carry their own copies of this logic, and the Omarchy
// option only existed on the reader — so anyone who lived in the library view
// could never find it. One module, both pages.

import { api } from './api.js';

export const THEMES = ['light', 'sepia', 'dark', 'auto', 'omarchy'];

/**
 * Which data-theme the page should actually wear for a stored preference.
 *
 * "Auto" means "match what I'm looking at", in the strongest form the desktop
 * allows: a full palette if it offers one (Omarchy), its light/dark side if it
 * only states that, and the browser's colour-scheme preference otherwise. A
 * freshly made browser profile has no such preference, which is how a dark
 * desktop once produced a white reader. An explicit choice is never overridden,
 * and an unknown preference falls back to auto rather than unstyling the page.
 *
 * `desktop` is the server's answer: { available, mode } or null.
 */
export function resolveTheme(pref, desktop) {
  const known = THEMES.includes(pref) ? pref : 'auto';
  if (known === 'omarchy' && !desktop?.available) return resolveTheme('auto', desktop);
  if (known !== 'auto') return known;
  if (desktop?.available) return 'omarchy';
  if (desktop?.mode === 'dark' || desktop?.mode === 'light') return desktop.mode;
  return 'auto';
}

/** Apply a preference to the document and remember it for the next paint. */
export function applyTheme(pref, desktop) {
  document.documentElement.dataset.theme = resolveTheme(pref, desktop);
  if (pref) localStorage.setItem('reader.theme', pref);
}

/** Reflect the stored preference in the picker (a <select>). */
export function markActiveTheme(picker, pref) {
  if (!picker) return;
  picker.value = pref;
}

/**
 * Ask the server about the desktop, then reveal the Omarchy button if the
 * desktop can supply a palette. Returns { available, mode, name }; never
 * throws, because a reader running anywhere else simply has no desktop.
 */
export async function revealDesktopTheme(picker) {
  const theme = await api.getTheme();
  const option = picker?.querySelector('option[value="omarchy"]');
  if (option && theme.available) {
    option.hidden = false;
    if (theme.name) option.textContent = `Omarchy (${theme.name})`;
  }
  return theme;
}
