// Reader fonts: resolve the font_family pref to a CSS value, manage the
// localStorage recents list, filter the catalog, and lazily inject @font-face
// rules for server-cached Google fonts. Bundled fonts have static @font-face
// in style.css and need no injection.
import { api } from '../api.js';

const RECENTS_KEY = 'reader.fontRecents';
const injected = new Set(); // families whose @font-face we've added this session

export function resolveFont(prefValue, bundledKeys) {
  const v = (prefValue || '').trim();
  if (!v) return { cssValue: 'var(--font-reader-serif)', isBundled: true, family: 'serif' };
  if (bundledKeys.includes(v)) {
    return { cssValue: `var(--font-reader-${v})`, isBundled: true, family: v };
  }
  // Google family: quote it, fall back to the bundled serif while it loads.
  return { cssValue: `"${v}", var(--font-reader-serif)`, isBundled: false, family: v };
}

export function addRecent(list, family, cap = 6) {
  const next = [family, ...list.filter((f) => f !== family)];
  return next.slice(0, cap);
}

export function readRecents() {
  try { return JSON.parse(localStorage.getItem(RECENTS_KEY)) || []; }
  catch { return []; }
}

export function writeRecents(list) {
  localStorage.setItem(RECENTS_KEY, JSON.stringify(list));
}

export function filterCatalog(families, query, limit = 60) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return families.slice(0, limit);
  const pre = [];
  const sub = [];
  for (const f of families) {
    const name = f.family.toLowerCase();
    if (name.startsWith(q)) pre.push(f);
    else if (name.includes(q)) sub.push(f);
  }
  return [...pre, ...sub].slice(0, limit);
}

// DOM: inject @font-face rules for a server-cached Google family (idempotent).
export function ensureFontFace(family, faces) {
  if (injected.has(family)) return;
  const fam = family.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const css = faces.map((f) =>
    `@font-face{font-family:"${fam}";src:url("${f.url}") format("woff2");`
    + `font-style:${f.style === 'italic' ? 'italic' : 'normal'};font-weight:${f.weight ?? 400};font-display:swap;}`
  ).join('\n');
  const el = document.createElement('style');
  el.dataset.font = family;
  el.textContent = css;
  document.head.appendChild(el);
  injected.add(family);
}

// DOM: ask the server to cache the font, then inject its @font-face.
export async function injectAndEnsure(family) {
  if (injected.has(family)) return;
  const out = await api.ensureFont(family);
  ensureFontFace(family, out.faces);
}
