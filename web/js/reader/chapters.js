// Chapter sidebar: slide-out left panel that lists book.chapters and
// jumps to the first paragraph of the tapped chapter.
//
// Dependencies are injected as callbacks because they live in
// reader.js (still part of the core playback module). When the
// core is split further, these can be replaced with imports.
import { state } from './state.js';

const $ = (sel) => document.querySelector(sel);

function _activeChapterIdx() {
  if (!state.book || !state.book.chapters) return 0;
  for (let i = 0; i < state.book.chapters.length; i++) {
    const ch = state.book.chapters[i];
    if (!ch.paragraphs || ch.paragraphs.length === 0) continue;
    const first = ch.paragraphs[0].idx;
    const last = ch.paragraphs[ch.paragraphs.length - 1].idx;
    if (state.curIdx >= first && state.curIdx <= last) return i;
  }
  return 0;
}

function _renderChapterList({ seekToParagraph, close }) {
  const host = $('#chapter-list');
  if (!host) return;
  host.replaceChildren();
  const chapters = (state.book && state.book.chapters) || [];
  const active = _activeChapterIdx();
  chapters.forEach((ch, i) => {
    const row = document.createElement('button');
    row.className = 'chapter-row' + (i === active ? ' active' : '');
    const title = document.createElement('span');
    title.className = 'chapter-row-title';
    title.textContent = ch.title && ch.title.trim() ? ch.title : `Chapter ${i + 1}`;
    const meta = document.createElement('span');
    meta.className = 'chapter-row-meta';
    const count = ch.paragraphs ? ch.paragraphs.length : 0;
    meta.textContent = `${count} paragraph${count === 1 ? '' : 's'}`;
    row.appendChild(title);
    row.appendChild(meta);
    row.addEventListener('click', () => {
      if (ch.paragraphs && ch.paragraphs.length > 0) {
        seekToParagraph(ch.paragraphs[0].idx);
      }
      close();
    });
    host.appendChild(row);
  });
}

/**
 * Wire the chapter sidebar. `seekToParagraph(idx)` is injected because
 * it lives in reader.js (loadParagraph + state mutation). Open via the
 * ☰ button; close via X / backdrop / Escape.
 */
export function setupChapterSidebar({ seekToParagraph }) {
  const open = () => {
    const sidebar = $('#chapter-sidebar');
    const backdrop = $('#sheet-backdrop');
    _renderChapterList({ seekToParagraph, close });
    sidebar.hidden = false;
    backdrop.hidden = false;
    requestAnimationFrame(() => {
      sidebar.classList.add('open');
      backdrop.classList.add('open');
    });
  };
  const close = () => {
    const sidebar = $('#chapter-sidebar');
    const backdrop = $('#sheet-backdrop');
    sidebar.classList.remove('open');
    backdrop.classList.remove('open');
    setTimeout(() => {
      sidebar.hidden = true;
      backdrop.hidden = true;
    }, 240);
  };

  $('#chapter-btn').addEventListener('click', open);
  $('#chapter-close').addEventListener('click', close);
  $('#sheet-backdrop').addEventListener('click', () => {
    const sidebar = $('#chapter-sidebar');
    if (sidebar && sidebar.classList.contains('open')) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      const sidebar = $('#chapter-sidebar');
      if (sidebar && sidebar.classList.contains('open')) close();
    }
  });
}
