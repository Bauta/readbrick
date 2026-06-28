// Library page state + pure selectors. Keep this module side-effect-free:
// no DOM access, no fetches.
import { session } from '../api.js';

export const state = {
  user: session.user,
  users: [],
  books: [],
  // Filter state (Tasks 8–9 will use these).
  search: sessionStorage.getItem('library.search') || '',
  status: sessionStorage.getItem('library.status') || 'all',
};

export function setSearch(q) {
  state.search = q || '';
  sessionStorage.setItem('library.search', state.search);
}

export function setStatus(s) {
  state.status = s;
  sessionStorage.setItem('library.status', s);
}

/** unread | in_progress | finished */
export function bookStatus(b) {
  const idx = b.progress?.paragraph_idx ?? 0;
  const n = b.paragraph_count ?? 0;
  if (idx === 0) return 'unread';
  if (n > 0 && idx >= n - 1) return 'finished';
  return 'in_progress';
}

/** Counts based on the unfiltered list. Used by chip badges so they
 *  don't shift when the user types in the search box. */
export function chipCounts(books) {
  const c = { all: books.length, unread: 0, in_progress: 0, finished: 0 };
  for (const b of books) c[bookStatus(b)] += 1;
  return c;
}

/** Apply current status + search to the book list. */
export function filteredBooks() {
  const q = state.search.trim().toLowerCase();
  return state.books.filter((b) => {
    if (state.status !== 'all' && bookStatus(b) !== state.status) return false;
    if (!q) return true;
    const hay = `${b.title || ''} ${b.author || ''}`.toLowerCase();
    return hay.includes(q);
  });
}

/** Book the user is actively reading: max(last_read_at) where paragraph_idx > 0.
 *  Returns null if no book has any progress yet. */
export function heroBook() {
  let best = null;
  for (const b of state.books) {
    const lastAt = b.progress?.last_read_at;
    if (b.progress?.paragraph_idx > 0 && lastAt) {
      if (!best || lastAt > best.progress.last_read_at) best = b;
    }
  }
  return best;
}
