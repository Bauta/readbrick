// Shared helpers used across the library, book detail, and reader pages.
// Pure functions and DOM utilities — no fetches, no global side effects.

// ───── DOM construction ─────

/**
 * Build a DOM element with props and children in one expression.
 * Supported props:
 *   - class:   className
 *   - text:    textContent (safe — no HTML parsing)
 *   - on<Event>: addEventListener('event', value)
 *   - attrs: { name: value } applied via setAttribute
 *   - anything else assigned directly to the node (id, hidden, value, src, …)
 */
export const el = (tag, props = {}, children = []) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else if (k === 'attrs') for (const [ak, av] of Object.entries(v)) n.setAttribute(ak, av);
    else n[k] = v;
  }
  for (const c of children) n.appendChild(c);
  return n;
};

// ───── Time formatting ─────

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;
const WEEK = 604800;
const YEAR = 31536000;

/**
 * Humanize a unix timestamp as an "ago" string:
 *   just now / Xm ago / Xh ago / yesterday / weekday / MMM D / MMM YYYY.
 * Returns an empty string for falsy input.
 */
export function humanizeAgo(ts, now = Date.now() / 1000) {
  if (!ts) return '';
  const diff = Math.max(0, now - ts);
  if (diff < MINUTE) return 'just now';
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  const tsDate = new Date(ts * 1000);
  const nowDate = new Date(now * 1000);
  const sameDay = (a, b) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate();
  const yest = new Date(nowDate);
  yest.setDate(yest.getDate() - 1);
  if (sameDay(tsDate, yest)) return 'yesterday';
  if (diff < WEEK) return tsDate.toLocaleDateString(undefined, { weekday: 'short' });
  if (diff < YEAR) return tsDate.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return tsDate.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
}

/**
 * Format a minute count as "~Xm" / "~Xh" / "~Xh Ym".
 * Returns null for nullish input (caller decides what to render).
 */
export function fmtMinutes(mins) {
  if (mins == null) return null;
  if (mins < 60) return `~${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `~${h}h` : `~${h}h ${m}m`;
}

/**
 * Format a seconds count as "Xm" / "Xh" / "Xh Ym" for cumulative
 * listening time. Returns null for < 30s (avoids noisy "0m" on glance).
 */
export function fmtSecondsAsHM(seconds) {
  if (!seconds || seconds < 30) return null;
  const total = Math.round(seconds / 60);
  if (total < 60) return `${total}m`;
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}
