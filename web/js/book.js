// Book detail page: header, description, covers gallery, edit sheet,
// refresh + delete actions.
import { api, session, toast } from './api.js';
import { el, humanizeAgo, fmtMinutes, fmtSecondsAsHM } from './util.js';
import { applyTheme } from './theme.js';

const $ = (sel) => document.querySelector(sel);

const bookId = location.pathname.split('/').pop();

const state = {
  user: session.user,
  book: null,
  covers: null,
  quotes: [],
  voiceId: 'kokoro:af_heart',
};

// The book page was the one screen that never applied the theme — it flashed
// cream in a dark app every time a cover was tapped. Paint the cached choice
// immediately, then correct it once the real preference and the desktop's
// answer are known, exactly as the library does.
function applyThemeFromPrefs() {
  const cached = localStorage.getItem('reader.theme');
  if (cached) applyTheme(cached, null);
}

async function applyThemeFromServer(prefs) {
  const desktop = await api.getTheme();
  applyTheme(prefs?.theme || localStorage.getItem('reader.theme') || 'auto', desktop);
}

async function boot() {
  applyThemeFromPrefs();
  try {
    const [book, covers, quotes, progress, prefs] = await Promise.all([
      api.getBook(bookId),
      api.getCovers(bookId),
      api.listQuotes(state.user.id, bookId).catch(() => []),
      api.getProgress(state.user.id, bookId).catch(() => null),
      api.getPrefs(state.user.id).catch(() => null),
    ]);
    state.book = book;
    state.covers = covers;
    state.quotes = quotes;
    if (progress) state.book.progress = progress;
    if (prefs?.voice_id) state.voiceId = prefs.voice_id;
    applyThemeFromServer(prefs);   // not awaited: the cached theme is already painted
  } catch (e) {
    $('#book-detail-content').textContent = `Could not load book: ${e.message}`;
    return;
  }
  $('#book-title').textContent = state.book.title;
  setupCoverUpload();
  setupEditSheet();
  setupDeleteModal();
  renderDetail();
}

function coverUrl(id) {
  return `/api/books/${encodeURIComponent(id)}/cover?v=${Date.now()}`;
}

function renderHeader() {
  const b = state.book;
  const initial = (b.title || '?').charAt(0).toUpperCase();
  const cover = el('div', { class: 'detail-cover' });
  const img = el('img', { src: coverUrl(b.id) });
  img.addEventListener('error', () => {
    img.replaceWith(document.createTextNode(initial));
  });
  cover.appendChild(img);

  const yearStr = b.published_year ? ` · ${b.published_year}` : '';
  const est = fmtMinutes(b.est_minutes);
  const metaBits = [b.format.toUpperCase()];
  if (est) metaBits.push(est);
  const listened = fmtSecondsAsHM(b.progress?.total_seconds);
  if (listened) metaBits.push(`Listened ${listened}`);

  const info = el('div', { class: 'detail-info' }, [
    el('h1', { class: 'detail-title', text: b.title }),
    el('p', { class: 'detail-subtitle', text: `${b.author || 'Unknown'}${yearStr}` }),
    el('p', { class: 'detail-meta', text: metaBits.join(' · ') }),
    el('button', {
      class: 'primary detail-play',
      text: '▶ Play',
      onclick: () => { location.href = `/read/${encodeURIComponent(b.id)}`; },
    }),
  ]);
  return el('section', { class: 'detail-header' }, [cover, info]);
}

function renderDescription() {
  const desc = state.book.description;
  if (!desc) return el('p', { class: 'detail-desc empty', text: '(No description)' });
  return el('p', { class: 'detail-desc', text: desc });
}

function renderQuotes() {
  const quotes = state.quotes || [];
  const exportBtn = el('button', {
    class: 'tap',
    text: 'Export',
    onclick: () => {
      if (!quotes.length) return;
      location.href = api.exportQuotesUrl(state.user.id, bookId);
    },
  });
  if (!quotes.length) exportBtn.disabled = true;

  const header = el('div', { class: 'detail-quotes-header' }, [
    el('h2', { class: 'detail-section-h2', text: `Quotes (${quotes.length})` }),
    exportBtn,
  ]);

  const list = el('div', { class: 'detail-quotes-list' });
  for (const q of quotes) {
    const item = el('div', { class: 'detail-quote' }, [
      el('p', { class: 'detail-quote-text', text: `"${q.text}"` }),
      ...(q.note ? [el('p', { class: 'detail-quote-note', text: q.note })] : []),
      el('div', { class: 'detail-quote-foot' }, [
        el('span', { class: 'detail-quote-time', text: humanizeAgo(q.created_at) }),
        el('button', {
          class: 'tap danger detail-quote-del',
          text: '×',
          attrs: { 'aria-label': 'Delete quote' },
          onclick: async () => {
            try {
              await api.deleteQuote(state.user.id, q.id);
              state.quotes = state.quotes.filter((x) => x.id !== q.id);
              renderDetail();
              toast('Quote deleted');
            } catch (e) {
              toast(`Delete failed: ${e.message}`);
            }
          },
        }),
      ]),
    ]);
    list.appendChild(item);
  }
  return el('section', { class: 'detail-quotes' }, [header, list]);
}

function renderActions() {
  return el('div', { class: 'detail-actions' }, [
    el('button', { class: 'tap', text: 'Edit', onclick: openEditSheet }),
    el('button', { class: 'tap', text: 'Refresh metadata', onclick: (e) => doRefresh(e) }),
    el('button', { class: 'tap danger', text: 'Delete…', onclick: openDeleteModal }),
  ]);
}

const COVER_LABELS = {
  epub: 'EPUB',
  pdf: 'PDF page 1',
  openlibrary: 'OpenLibrary',
  google_books: 'Google Books',
  custom: 'Custom',
};

function renderCovers() {
  const { active, available } = state.covers;
  const tiles = available.map((source) => {
    const tile = el('button', {
      class: 'cover-tile' + (source === active ? ' active' : ''),
      attrs: { 'aria-label': `Set cover to ${COVER_LABELS[source]}` },
      onclick: () => switchCover(source),
    });
    const thumb = el('img', { src: `/api/books/${encodeURIComponent(bookId)}/cover?v=${Date.now()}` });
    // Trick: for non-active tiles, the cover.jpg URL points to the active source,
    // so we need a separate endpoint OR a probe per source. Simplification:
    // tiles only show the active img; non-active tiles show their source label only.
    if (source === active) {
      tile.appendChild(thumb);
    } else {
      tile.appendChild(el('div', { class: 'cover-tile-letter', text: COVER_LABELS[source].slice(0, 4) }));
    }
    tile.appendChild(el('span', { class: 'cover-tile-label', text: COVER_LABELS[source] }));
    return tile;
  });
  // Upload tile
  const uploadTile = el('button', {
    class: 'cover-tile cover-tile-upload',
    text: '+ Upload',
    onclick: () => $('#cover-file-input').click(),
  });
  tiles.push(uploadTile);

  return el('section', { class: 'detail-covers' }, [
    el('div', { class: 'cover-grid' }, tiles),
  ]);
}

async function switchCover(source) {
  try {
    state.covers = await api.setCover(bookId, source);
    renderDetail();
    // Re-render the covers section inside the edit sheet too if it's open.
    if ($('#edit-sheet').classList.contains('open')) renderCoversInto($('#edit-covers'));
  } catch (e) {
    toast(`Could not switch cover: ${e.message}`);
    // Re-fetch gallery — the stale tile may need to disappear if its file
    // is gone server-side.
    try {
      state.covers = await api.getCovers(bookId);
      renderDetail();
    } catch (_) {
      // best-effort
    }
  }
}

function setupCoverUpload() {
  const input = $('#cover-file-input');
  input.addEventListener('change', async () => {
    const f = input.files[0];
    if (!f) return;
    input.value = '';
    try {
      state.covers = await api.uploadCover(bookId, f);
      renderDetail();
      if ($('#edit-sheet').classList.contains('open')) renderCoversInto($('#edit-covers'));
      toast('Cover uploaded');
    } catch (e) {
      toast(`Upload failed: ${e.message}`);
    }
  });
}

function renderDetail() {
  const c = $('#book-detail-content');
  c.replaceChildren();
  c.appendChild(renderHeader());
  c.appendChild(renderDescription());
  c.appendChild(renderQuotes());
  // Cover gallery moved into the edit sheet — see openEditSheet().
  c.appendChild(renderActions());
}

function renderCoversInto(container) {
  container.replaceChildren();
  container.appendChild(renderCovers());
}

function openEditSheet() {
  const sheet = $('#edit-sheet');
  const backdrop = $('#sheet-backdrop');
  const b = state.book;
  $('#edit-title').value = b.title || '';
  $('#edit-author').value = b.author || '';
  $('#edit-year').value = b.published_year ?? '';
  $('#edit-description').value = b.description || '';
  renderCoversInto($('#edit-covers'));
  backdrop.hidden = false;
  requestAnimationFrame(() => backdrop.classList.add('open'));
  sheet.classList.add('open');
}

function closeEditSheet() {
  const sheet = $('#edit-sheet');
  const backdrop = $('#sheet-backdrop');
  sheet.classList.remove('open');
  backdrop.classList.remove('open');
  setTimeout(() => { backdrop.hidden = true; }, 240);
}

async function saveEdit() {
  const patch = {
    title: $('#edit-title').value,
    author: $('#edit-author').value,
    published_year: $('#edit-year').value === '' ? null : parseInt($('#edit-year').value, 10),
    description: $('#edit-description').value,
  };
  try {
    state.book = await api.patchBook(bookId, patch);
    closeEditSheet();
    $('#book-title').textContent = state.book.title;
    renderDetail();
    toast('Saved');
  } catch (e) {
    toast(`Save failed: ${e.message}`);
  }
}

function setupEditSheet() {
  $('#edit-cancel').addEventListener('click', closeEditSheet);
  $('#edit-save').addEventListener('click', saveEdit);
  $('#sheet-backdrop').addEventListener('click', closeEditSheet);
}

async function doRefresh(event) {
  const btn = event?.currentTarget;
  if (btn) btn.disabled = true;
  try {
    const r = await api.refreshBook(bookId);
    state.book = r.book;
    state.covers = await api.getCovers(bookId);  // reload to reflect any new candidate
    renderDetail();
    if ($('#edit-sheet').classList.contains('open')) renderCoversInto($('#edit-covers'));
    if (r.fields_filled > 0) {
      toast(`Refreshed ${r.fields_filled} field(s)`);
    } else if (r.new_cover_sources.length > 0) {
      toast(`Added cover: ${r.new_cover_sources.join(', ')}`);
    } else {
      toast('Nothing to refresh');
    }
  } catch (e) {
    toast(`Refresh failed: ${e.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function openDeleteModal() {
  const backdrop = $('#delete-modal-backdrop');
  const prompt = $('#delete-prompt');
  const input = $('#delete-confirm-input');
  const confirmBtn = $('#delete-confirm');
  prompt.textContent = `Type the title to confirm: ${state.book.title}`;
  input.value = '';
  confirmBtn.disabled = true;
  backdrop.hidden = false;
}

function closeDeleteModal() {
  $('#delete-modal-backdrop').hidden = true;
}

async function confirmDelete() {
  try {
    await api.deleteBook(bookId);
    location.href = '/';
  } catch (e) {
    toast(`Delete failed: ${e.message}`);
  }
}

function setupDeleteModal() {
  const input = $('#delete-confirm-input');
  const confirmBtn = $('#delete-confirm');
  input.addEventListener('input', () => {
    confirmBtn.disabled = input.value !== (state.book?.title || '');
  });
  $('#delete-cancel').addEventListener('click', closeDeleteModal);
  confirmBtn.addEventListener('click', confirmDelete);
  $('#delete-modal-backdrop').addEventListener('click', (e) => {
    if (e.target.id === 'delete-modal-backdrop') closeDeleteModal();
  });
}

boot();
