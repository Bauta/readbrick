// Library entry point. Boots user pill + book list, wires upload zone.
import { api, session, toast } from './api.js';
import { state, setSearch } from './library/state.js';
import { setupUploadZone } from './library/upload.js';
import { renderLibrary, el } from './library/render.js';

const $ = (sel) => document.querySelector(sel);

async function boot() {
  applyThemeFromPrefs();
  state.users = await api.listUsers();
  if (!state.user || !state.users.find((u) => u.id === state.user.id)) {
    state.user = state.users[0] || null;
    session.user = state.user;
  }
  renderUserPill();
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

function applyThemeFromPrefs() {
  const cached = localStorage.getItem('reader.theme');
  if (cached) document.documentElement.dataset.theme = cached;
}

function renderUserPill() {
  $('#user-pill').textContent = state.user ? state.user.name : 'Pick a user';
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
      if (!confirm(`Delete user "${u.name}"? Progress for this user will be lost.`)) return;
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
