// Tiny fetch wrapper.

const j = async (r) => {
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const body = await r.json(); if (body.detail) msg = body.detail; } catch {}
    throw new Error(msg);
  }
  if (r.status === 204) return null;
  return r.json();
};

export const api = {
  // Desktop palette availability (Omarchy). Never throws the page: a reader
  // running anywhere else simply has no desktop theme to offer.
  getTheme: () => fetch('/api/theme').then(j).catch(() => ({ available: false })),

  listUsers: () => fetch('/api/users').then(j),
  createUser: (name) => fetch('/api/users', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({name})
  }).then(j),
  deleteUser: (id) => fetch(`/api/users/${id}`, {method: 'DELETE'}).then(j),
  getPrefs: (id) => fetch(`/api/users/${id}/prefs`).then(j),
  patchPrefs: (id, patch) => fetch(`/api/users/${id}/prefs`, {
    method: 'PATCH', headers: {'content-type': 'application/json'},
    body: JSON.stringify(patch)
  }).then(j),

  getFontCatalog: () => fetch('/api/fonts/catalog').then(j),
  ensureFont: (family) => fetch('/api/fonts/ensure', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({family})
  }).then(j),

  listBooks: (userId) => fetch(`/api/books${userId ? `?user_id=${userId}` : ''}`).then(j),
  getBook: (id) => fetch(`/api/books/${id}`).then(j),
  deleteBook: (id) => fetch(`/api/books/${id}`, {method: 'DELETE'}).then(j),
  uploadBook: (file, onProgress) => {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/books');
      const form = new FormData();
      form.append('file', file);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          let msg = xhr.statusText;
          try { msg = JSON.parse(xhr.responseText).detail || msg; } catch {}
          reject(new Error(msg));
        }
      };
      xhr.onerror = () => reject(new Error('upload failed'));
      xhr.send(form);
    });
  },

  getProgress: (uid, bid) => fetch(`/api/users/${uid}/progress/${bid}`).then(j),
  putProgress: (uid, bid, paragraph_idx, char_offset = 0, seconds_delta = 0) => fetch(
    `/api/users/${uid}/progress/${bid}`,
    {method: 'PUT', headers: {'content-type': 'application/json'},
     body: JSON.stringify({paragraph_idx, char_offset, seconds_delta})}
  ).then(j),

  listVoices: () => fetch('/api/voices').then(j),
  tts: (text, voice_id, language, speed = 1.0) => fetch('/api/tts', {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify({text, voice_id, language, speed})
  }).then(j),

  patchBook: (id, patch) => fetch(`/api/books/${id}`, {
    method: 'PATCH', headers: {'content-type': 'application/json'},
    body: JSON.stringify(patch),
  }).then(j),
  refreshBook: (id) => fetch(`/api/books/${id}/refresh`, { method: 'POST' }).then(j),
  getCovers: (id) => fetch(`/api/books/${id}/covers`).then(j),
  setCover: (id, source) => fetch(`/api/books/${id}/cover`, {
    method: 'PUT', headers: {'content-type': 'application/json'},
    body: JSON.stringify({ source }),
  }).then(j),
  uploadCover: (id, file) => {
    const form = new FormData();
    form.append('file', file);
    return fetch(`/api/books/${id}/cover`, { method: 'POST', body: form }).then(j);
  },

  createQuote: (uid, body) => fetch(`/api/users/${uid}/quotes`, {
    method: 'POST', headers: {'content-type': 'application/json'},
    body: JSON.stringify(body),
  }).then(j),
  listQuotes: (uid, bookId) => fetch(
    `/api/users/${uid}/quotes?book_id=${encodeURIComponent(bookId)}`
  ).then(j),
  deleteQuote: (uid, quoteId) => fetch(
    `/api/users/${uid}/quotes/${quoteId}`,
    { method: 'DELETE' }
  ).then(j),
  exportQuotesUrl: (uid, bookId) =>
    `/api/users/${uid}/quotes/${encodeURIComponent(bookId)}/export`,
};

// localStorage helpers for "current user" persistence
export const session = {
  get user() {
    const raw = localStorage.getItem('reader.user');
    return raw ? JSON.parse(raw) : null;
  },
  set user(u) {
    if (u) localStorage.setItem('reader.user', JSON.stringify(u));
    else localStorage.removeItem('reader.user');
  },
};

export const toast = (msg, ms = 2400) => {
  let t = document.querySelector('.toast');
  if (!t) {
    t = document.createElement('div');
    t.className = 'toast';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove('show'), ms);
};
