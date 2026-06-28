// Library rendering: hero band, search/chips, and grid.
import { state, filteredBooks, heroBook, chipCounts, bookStatus,
         setSearch, setStatus } from './state.js';
import { el, humanizeAgo, fmtMinutes, fmtSecondsAsHM } from '../util.js';

// Re-export el so `import { el } from './library/render.js'` in app.js
// keeps working without churn at the call sites.
export { el, humanizeAgo };

const $ = (sel) => document.querySelector(sel);

const STATUS_LABELS = {
  all: 'All',
  unread: 'Unread',
  in_progress: 'In progress',
  finished: 'Finished',
};

// Holds the callback most recently passed to renderLibrary; chip/search
// re-renders use this so we don't lose the picker hook.
let lastOnPickUser = null;

function renderChips() {
  const host = $('#status-chips');
  if (!host) return;
  host.replaceChildren();
  const counts = chipCounts(state.books);
  for (const key of ['all', 'unread', 'in_progress', 'finished']) {
    const count = counts[key];
    const btn = el('button', {
      class: 'chip' + (state.status === key ? ' active' : ''),
      text: `${STATUS_LABELS[key]} (${count})`,
      attrs: { role: 'tab', 'aria-selected': state.status === key ? 'true' : 'false' },
      onclick: () => {
        if (state.status === key) return;
        setStatus(key);
        renderLibrary({ onPickUser: lastOnPickUser });
      },
    });
    host.appendChild(btn);
  }
}

function renderHero(book) {
  const initial = (book.title || '?').charAt(0).toUpperCase();
  const pct = book.progress_pct ?? 0;
  const estLeft = book.est_minutes != null
    ? Math.max(1, Math.round(book.est_minutes * (1 - pct / 100)))
    : null;

  const cover = el('div', { class: 'hero-cover' });
  const img = el('img', { src: `/api/books/${encodeURIComponent(book.id)}/cover` });
  img.addEventListener('error', () => {
    cover.replaceChildren(document.createTextNode(initial));
  });
  cover.appendChild(img);

  const yearStr = book.published_year ? ` · ${book.published_year}` : '';
  const lastOpenedTs = book.progress?.last_read_at || book.added_at;
  const lastOpened = lastOpenedTs ? `Last opened ${humanizeAgo(lastOpenedTs)}` : '';
  const stats = `${Math.round(pct)}% · ${estLeft != null ? `~${estLeft}m left` : 'no estimate'}`;
  const listenedStr = fmtSecondsAsHM(book.progress?.total_seconds);

  const info = el('div', { class: 'hero-info' }, [
    el('div', { class: 'hero-eyebrow', text: 'Continue reading' }),
    el('h2', { class: 'hero-title', text: book.title }),
    el('p', { class: 'hero-subtitle', text: `${book.author || ''}${yearStr}` }),
    el('p', { class: 'hero-stats', text: stats }),
    ...(lastOpened ? [el('p', { class: 'hero-lastopened', text: lastOpened })] : []),
    ...(listenedStr ? [el('p', { class: 'hero-lastopened', text: `Listened ${listenedStr}` })] : []),
    ...(book.description
      ? [el('p', { class: 'hero-desc', text: book.description })]
      : []),
    el('button', {
      class: 'primary hero-resume',
      text: 'Resume ▶',
      onclick: () => { location.href = `/read/${encodeURIComponent(book.id)}`; },
    }),
  ]);

  return el('section', { class: 'hero', attrs: { 'aria-label': 'Continue reading' } },
    [cover, info]);
}

// ───── public render entry point ─────

export function renderLibrary({ onPickUser }) {
  lastOnPickUser = onPickUser;
  const toolbar = document.querySelector('.library-toolbar');
  const c = $('#content');
  c.replaceChildren();

  if (!state.user) {
    if (toolbar) toolbar.hidden = true;
    c.appendChild(el('div', { class: 'empty' }, [
      el('h2', { text: 'Welcome' }),
      el('p', { text: 'Create or pick a user to start reading.' }),
      el('button', { class: 'primary', text: 'Pick user', onclick: onPickUser }),
    ]));
    return;
  }
  if (state.books.length === 0) {
    if (toolbar) toolbar.hidden = true;
    c.appendChild(el('div', { class: 'empty' }, [
      el('h2', { text: 'Your library is empty' }),
      el('p', { text: 'Drop an EPUB, PDF, TXT, MOBI, or AZW3 file to get started.' }),
      el('button', {
        class: 'primary', text: 'Upload book',
        onclick: () => $('#file-input').click(),
      }),
    ]));
    $('#upload-zone').hidden = false;
    return;
  }

  if (toolbar) toolbar.hidden = false;
  renderChips();

  // Hero only when no filter / no search — keeps the view focused on the
  // result set when the user is narrowing.
  const hero = heroBook();
  if (hero && state.status === 'all' && !state.search.trim()) {
    c.appendChild(renderHero(hero));
  }

  const visible = filteredBooks();
  if (visible.length === 0) {
    const isSearchActive = !!state.search.trim();
    const children = [
      el('p', {
        text: isSearchActive
          ? `No books match "${state.search}".`
          : 'No books in this state.',
      }),
    ];
    if (isSearchActive) {
      children.push(el('button', {
        class: 'primary', text: 'Clear search',
        onclick: () => {
          setSearch('');
          const input = $('#library-search');
          if (input) input.value = '';
          renderLibrary({ onPickUser: lastOnPickUser });
        },
      }));
    }
    c.appendChild(el('div', { class: 'empty' }, children));
    return;
  }
  renderGrid(c, visible);
}

// ───── grid ─────

function renderGrid(container, books) {
  const grid = el('div', { class: 'book-grid' });
  for (const b of books) {
    grid.appendChild(renderCard(b));
  }
  container.appendChild(grid);
}

function renderCard(b) {
  const initial = (b.title || '?').charAt(0).toUpperCase();
  const pct = b.progress_pct ?? 0;

  const cover = el('div', { class: 'cover' });
  const img = el('img', { src: `/api/books/${encodeURIComponent(b.id)}/cover` });
  // Replace just the img on error (not the whole cover) so the format
  // badge below survives the letter fallback.
  img.addEventListener('error', () => {
    img.replaceWith(document.createTextNode(initial));
  });
  cover.appendChild(img);
  if (b.format) {
    cover.appendChild(el('span', { class: 'format-badge', text: b.format.toUpperCase() }));
  }

  const bar = el('div', { class: 'progress-bar' });
  const fill = el('div');
  fill.style.width = `${pct}%`;
  bar.appendChild(fill);

  // Build the metadata line: "2018 · ~3h 12m · Last opened yesterday"
  const metaBits = [];
  if (b.published_year) metaBits.push(String(b.published_year));
  if (b.est_minutes != null) metaBits.push(fmtMinutes(b.est_minutes));
  const lastTs = b.progress?.last_read_at;
  if (lastTs) {
    metaBits.push(`Last opened ${humanizeAgo(lastTs)}`);
  } else if (b.added_at) {
    metaBits.push(`Added ${humanizeAgo(b.added_at)}`);
  }
  const listened = fmtSecondsAsHM(b.progress?.total_seconds);
  if (listened) metaBits.push(`${listened} listened`);
  const metaLine = metaBits.join(' · ');

  const meta = el('div', { class: 'meta' }, [
    el('p', { class: 'title', text: b.title }),
    el('p', { class: 'author', text: b.author || '' }),
    bar,
    el('p', { class: 'progress-text', text: pct > 0 ? `${pct}% read` : 'Not started' }),
    ...(metaLine ? [el('p', { class: 'card-meta', text: metaLine })] : []),
  ]);

  const card = el('div', { class: 'book-card' }, [cover, meta]);
  card.addEventListener('click', () => {
    location.href = `/book/${encodeURIComponent(b.id)}`;
  });
  return card;
}
