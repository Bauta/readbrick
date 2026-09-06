// Library entry point. Boots user pill + book list, wires upload zone.
import { api, session, toast } from './api.js';
import { state, setSearch } from './library/state.js';
import { setupUploadZone } from './library/upload.js';
import { renderLibrary, el } from './library/render.js';
import { applyTheme, markActiveTheme, revealDesktopTheme } from './theme.js';
import { setupSheet } from './sheet.js';

const $ = (sel) => document.querySelector(sel);

async function boot() {
  applyThemeFromPrefs();
  state.users = await api.listUsers();
  if (!state.user || !state.users.find((u) => u.id === state.user.id)) {
    state.user = state.users[0] || null;
    session.user = state.user;
  }
  renderUserPill();
  setupSettings();
  await loadBooks();

  const searchInput = document.querySelector('#library-search');
  if (searchInput) {
    searchInput.value = state.search;
    let h = null;
    searchInput.addEventListener('input', (e) => {
      const v = e.target.value;
      clearTimeout(h);
      h = setTimeout(() => {
        setSearch(v);
        renderLibrary({ onPickUser: openUserPicker });
      }, 120);
    });
  }

  setupUploadZone({
    getUser: () => state.user,
    onUploaded: async () => { await loadBooks(); },
  });
  $('#user-pill').addEventListener('click', openUserPicker);
}

// First paint uses whatever the last page remembered, so there is no flash
// while the real preference loads from the server.
function applyThemeFromPrefs() {
  const cached = localStorage.getItem('reader.theme');
  if (cached) applyTheme(cached, null);
}

// ───── Settings (library) ─────
//
// Only what applies outside a book: the theme. Voice, speed and typography
// belong to the reader and live in its own sheet. This is also where the
// Omarchy option has to be reachable — until now it only existed inside a
// book's settings, invisible to anyone who lives in the library view.
let _themePref = null;
let _desktop = null;   // { available, mode } from the server, once known

async function setupSettings() {
  const sheet = $('#settings-sheet');
  const backdrop = $('#sheet-backdrop');
  const toggle = $('#theme-toggle');
  if (!sheet || !backdrop || !toggle) return;

  setupSheet({ sheet, backdrop, trigger: $('#settings-btn') });

  const paint = () => {
    applyTheme(_themePref, _desktop);
    markActiveTheme(toggle, _themePref);
  };

  toggle.querySelectorAll('button[data-theme]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      _themePref = btn.dataset.theme;
      paint();
      if (!state.user) return;
      try {
        await api.patchPrefs(state.user.id, { theme: _themePref });
      } catch {
        toast("Couldn't save the theme — it will reset next time");
      }
    });
  });

  // The stored preference, then the desktop's word on light/dark. Neither
  // should stall the library: the cached theme is already painted.
  if (state.user) {
    api.getPrefs(state.user.id)
      .then((prefs) => { _themePref = prefs.theme || 'auto'; paint(); })
      .catch(() => { _themePref = localStorage.getItem('reader.theme') || 'auto'; paint(); });
  }
  revealDesktopTheme(toggle).then((theme) => { _desktop = theme; paint(); });
}

function renderUserPill() {
  $('#user-pill').textContent = state.user ? state.user.name : 'Pick a user';
}

function confirmDialog({ title, body, confirmLabel }) {
  return new Promise((resolve) => {
    const backdrop = el('div', { class: 'modal-backdrop' });
    const modal = el('div', { class: 'modal confirm' });
    modal.addEventListener('click', (e) => e.stopPropagation());
    const finish = (answer) => { backdrop.remove(); resolve(answer); };
    modal.appendChild(el('h2', { text: title }));
    modal.appendChild(el('p', { class: 'confirm-body', text: body }));
    const row = el('div', { class: 'row confirm-actions' });
    const cancel = el('button', { text: 'Cancel' });
    const go = el('button', { class: 'danger', text: confirmLabel });
    cancel.addEventListener('click', () => finish(false));
    go.addEventListener('click', () => finish(true));
    row.append(cancel, go);
    modal.appendChild(row);
    backdrop.addEventListener('click', () => finish(false));
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    cancel.focus();
  });
}

function openUserPicker() {
  const backdrop = el('div', { class: 'modal-backdrop' });
  const modal = el('div', { class: 'modal' });
  modal.addEventListener('click', (e) => e.stopPropagation());
  backdrop.appendChild(modal);

  modal.appendChild(el('h2', { text: "Who's reading?" }));

  const list = el('div', { class: 'user-list' });
  for (const u of state.users) {
    const row = el('div', {
      class: 'user-row' + (state.user && u.id === state.user.id ? ' current' : ''),
    });
    row.appendChild(el('span', { text: u.name }));
    const del = el('button', { class: 'del', text: '✕', title: 'Delete user' });
    row.appendChild(del);
    row.addEventListener('click', async () => {
      state.user = u;
      session.user = u;
      renderUserPill();
      backdrop.remove();
      await loadBooks();
    });
    del.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      // In-app, not the browser's native confirm(): it says what is actually
      // lost, it matches how deleting a book already asks, and it works the
      // same inside the desktop app window.
      const ok = await confirmDialog({
        title: `Remove ${u.name}?`,
        body: 'Their reading positions and saved quotes go with them. The books stay.',
        confirmLabel: 'Remove',
      });
      if (!ok) return;
      await api.deleteUser(u.id);
      state.users = state.users.filter((x) => x.id !== u.id);
      if (state.user && state.user.id === u.id) {
        state.user = state.users[0] || null;
        session.user = state.user;
        renderUserPill();
        await loadBooks();
      }
      row.remove();
    });
    list.appendChild(row);
  }
  modal.appendChild(list);

  const row = el('div', { class: 'row' });
  const input = el('input', { type: 'text', placeholder: 'New user name', maxLength: 64 });
  const addBtn = el('button', { class: 'primary', text: 'Add' });
  row.appendChild(input);
  row.appendChild(addBtn);
  modal.appendChild(row);

  const add = async () => {
    const name = input.value.trim();
    if (!name) return;
    try {
      const u = await api.createUser(name);
      state.users.push(u);
      state.user = u;
      session.user = u;
      renderUserPill();
      backdrop.remove();
      await loadBooks();
    } catch (e) {
      toast(e.message);
    }
  };
  addBtn.addEventListener('click', add);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') add(); });
  backdrop.addEventListener('click', () => backdrop.remove());

  document.body.appendChild(backdrop);
  setTimeout(() => input.focus(), 50);
}

async function loadBooks() {
  state.books = await api.listBooks(state.user?.id);
  renderLibrary({ onPickUser: openUserPicker });
}

boot();
