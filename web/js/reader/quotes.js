// Quotes: persistent highlight rendering + selection toolbar + tap-to-
// inspect-and-delete popover. Single-paragraph quotes only (cross-
// paragraph selections clip to the start paragraph at save time).
import { api, toast } from '../api.js';
import { humanizeAgo } from '../util.js';
import { state, bookId } from './state.js';

const $ = (sel) => document.querySelector(sel);

// ───── Highlight rendering (called from renderParagraphs + renderWordsInParagraph) ─────

export function applyQuoteHighlights(paraIdx) {
  if (!state.quotes || state.quotes.length === 0) return;
  const para = document.querySelector(`p[data-idx="${paraIdx}"]`);
  if (!para) return;
  const quotes = state.quotes.filter((q) => q.paragraph_idx === paraIdx);
  if (quotes.length === 0) return;

  const hasWordSpans = para.querySelector('span.w') !== null;
  for (const q of quotes) {
    if (hasWordSpans) _highlightInWordSpans(para, q);
    else _highlightInPlainText(para, q);
  }
}

function _highlightInPlainText(para, quote) {
  const text = para.textContent;
  const idx = text.indexOf(quote.text);
  if (idx < 0) return;
  const textNode = para.firstChild;
  if (!textNode || textNode.nodeType !== Node.TEXT_NODE) return;
  const before = text.slice(0, idx);
  const match = text.slice(idx, idx + quote.text.length);
  const after = text.slice(idx + quote.text.length);
  para.replaceChildren(
    document.createTextNode(before),
    _mark(quote, match),
    document.createTextNode(after),
  );
}

function _highlightInWordSpans(para, quote) {
  // Walk consecutive span.w + text-node neighbours, accumulating textContent
  // until we find quote.text. Then wrap that run of nodes in a <mark>.
  const children = Array.from(para.childNodes);
  let acc = '';
  let startIdx = -1;
  for (let i = 0; i < children.length; i++) {
    const node = children[i];
    const piece = (node.textContent || '');
    if (startIdx < 0) {
      const tryAt = piece.indexOf(quote.text[0]);
      if (tryAt < 0) continue;
      startIdx = i;
      acc = piece.slice(tryAt);
    } else {
      acc += piece;
    }
    if (acc.startsWith(quote.text)) {
      // Snapshot the insertion point BEFORE moving range nodes into the
      // mark — once they're moved, their parentNode is no longer `para`.
      const insertionPoint = children[i + 1] || null;
      const mark = _mark(quote);
      const range = children.slice(startIdx, i + 1);
      for (const n of range) mark.appendChild(n);
      para.insertBefore(mark, insertionPoint);
      return;
    }
    if (!quote.text.startsWith(acc)) {
      // Rewind to startIdx so the next iteration's i++ lands on
      // startIdx+1, picking up any valid start position immediately
      // after the failed one.
      i = startIdx;
      startIdx = -1;
      acc = '';
    }
  }
}

function _mark(quote, textIfPlain) {
  const m = document.createElement('mark');
  m.className = 'quote';
  m.dataset.quoteId = String(quote.id);
  if (textIfPlain != null) m.textContent = textIfPlain;
  return m;
}

// ───── Selection toolbar (drag-to-select → Save) ─────

export function setupQuoteSelection() {
  const toolbar = $('#quote-toolbar');
  const input = $('#quote-note-input');
  const saveBtn = $('#quote-save-btn');
  let pending = null;

  // Show the toolbar only when the user finishes a selection gesture
  // (mouseup / touchend / pointerup). A previous debounce-on-selectionchange
  // approach popped the toolbar 150ms after any selection pause and stole
  // focus into the note input — which made it impossible to extend the
  // selection via the OS selection handles. Settling on the gesture-end
  // event keeps the OS selection UI usable: drag to select → toolbar
  // appears on release → drag handles to adjust → toolbar still visible
  // (we re-read the selection lazily on Save).
  const handleSelectionFinalized = () => {
    // Touch/mouse events fire BEFORE the selection settles in some
    // browsers; defer a frame so window.getSelection() reflects the final
    // range. Two rAFs is more reliable than one across browsers.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (document.activeElement === input) return; // user typing in note
      const payload = _selectionPayload();
      if (!payload) { toolbar.hidden = true; return; }
      pending = payload;
      _positionToolbar(toolbar);
      // Only initialize the input on the FIRST appearance for this selection;
      // don't clobber what the user typed if they're adjusting handles.
      if (toolbar.hidden) input.value = '';
      toolbar.hidden = false;
      // DO NOT auto-focus the input. Auto-focus dismisses the OS selection
      // handles on iOS/Android, making it impossible to adjust the range.
      // User taps the input themselves when they want to add a note.
    }));
  };

  // Fires on pointerup outside the toolbar (selection gesture release).
  document.addEventListener('pointerup', (e) => {
    if (toolbar.contains(e.target)) return;
    handleSelectionFinalized();
  });
  // selectionchange still useful for keyboard-driven selection (Shift+Arrows
  // outside of input fields). Heavy debounce so it doesn't interrupt mid-drag.
  let _kbTimer = null;
  document.addEventListener('selectionchange', () => {
    clearTimeout(_kbTimer);
    _kbTimer = setTimeout(() => {
      if (document.activeElement === input) return;
      // Only react if the active element is in reader content (keyboard
      // selection) — pointer-driven selection is handled by pointerup above.
      const a = document.activeElement;
      if (a && a !== document.body && a !== document.documentElement) return;
      handleSelectionFinalized();
    }, 400);
  });

  saveBtn.addEventListener('click', async () => {
    // Re-read the selection at Save time — the user may have adjusted
    // the selection handles after the toolbar appeared.
    const fresh = _selectionPayload();
    if (fresh) pending = fresh;
    if (!pending) return;
    const noteRaw = input.value.trim();
    const wasClipped = pending.clipped;
    try {
      const row = await api.createQuote(state.user.id, {
        book_id: bookId,
        paragraph_idx: pending.paragraph_idx,
        text: pending.text,
        note: noteRaw || null,
      });
      state.quotes.push(row);
      toolbar.hidden = true;
      window.getSelection().removeAllRanges();
      toast(wasClipped ? 'Quote saved (clipped to one paragraph)' : 'Quote saved');
      applyQuoteHighlights(row.paragraph_idx);
    } catch (e) {
      toast(`Save failed: ${e.message}`);
    }
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); saveBtn.click(); }
    else if (e.key === 'Escape') { toolbar.hidden = true; }
  });

  document.addEventListener('mousedown', (e) => {
    if (toolbar.hidden) return;
    if (toolbar.contains(e.target)) return;
    toolbar.hidden = true;
  });
}

function _selectionPayload() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed) return null;
  const raw = sel.toString();
  if (!raw || !raw.trim()) return null;
  const range = sel.getRangeAt(0);
  const startPara = _closestParagraph(range.startContainer);
  if (!startPara) return null;
  const paragraphIdx = Number(startPara.dataset.idx);
  const endPara = _closestParagraph(range.endContainer);
  const clipped = endPara !== startPara;

  let text;
  if (!clipped) {
    text = raw.trim();
  } else {
    const clipRange = document.createRange();
    clipRange.setStart(range.startContainer, range.startOffset);
    clipRange.setEnd(startPara, startPara.childNodes.length);
    text = clipRange.toString().trim();
  }
  if (!text) return null;
  return { paragraph_idx: paragraphIdx, text, clipped };
}

function _closestParagraph(node) {
  while (node && node !== document.body) {
    if (node.nodeType === Node.ELEMENT_NODE && node.matches('p[data-idx]')) return node;
    node = node.parentNode;
  }
  return null;
}

function _positionToolbar(toolbar) {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return;
  const rect = sel.getRangeAt(0).getBoundingClientRect();
  const tbRect = { width: 280, height: 56 };
  const vh = window.innerHeight;
  let top = rect.bottom + 8;
  if (top + tbRect.height > vh) top = rect.top - tbRect.height - 8;
  let left = rect.left + rect.width / 2 - tbRect.width / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - tbRect.width - 8));
  toolbar.style.top = `${top + window.scrollY}px`;
  toolbar.style.left = `${left}px`;
}

// ───── Highlight tap popover (note + Delete) ─────

export function setupQuotePopover() {
  const popover = $('#quote-popover');
  const noteEl = $('#quote-popover-note');
  const metaEl = $('#quote-popover-meta');
  const delBtn = $('#quote-popover-delete');
  let currentQuoteId = null;

  document.addEventListener('click', (e) => {
    const mark = e.target.closest && e.target.closest('mark.quote');
    if (!mark) {
      if (!popover.hidden && !popover.contains(e.target)) {
        popover.hidden = true;
        currentQuoteId = null;
      }
      return;
    }
    const id = Number(mark.dataset.quoteId);
    const quote = state.quotes.find((q) => q.id === id);
    if (!quote) return;
    currentQuoteId = id;
    noteEl.textContent = quote.note || '(no note)';
    noteEl.classList.toggle('empty', !quote.note);
    metaEl.textContent = `Saved ${humanizeAgo(quote.created_at)}`;
    const rect = mark.getBoundingClientRect();
    popover.style.top = `${rect.bottom + window.scrollY + 6}px`;
    popover.style.left = `${rect.left}px`;
    popover.hidden = false;
  });

  delBtn.addEventListener('click', async () => {
    if (currentQuoteId == null) return;
    try {
      await api.deleteQuote(state.user.id, currentQuoteId);
      const removed = state.quotes.find((q) => q.id === currentQuoteId);
      state.quotes = state.quotes.filter((q) => q.id !== currentQuoteId);
      popover.hidden = true;
      currentQuoteId = null;
      if (removed) {
        const para = document.querySelector(`p[data-idx="${removed.paragraph_idx}"]`);
        if (para) {
          para.querySelectorAll('mark.quote').forEach((m) => {
            if (Number(m.dataset.quoteId) === removed.id) {
              m.replaceWith(...m.childNodes);
            }
          });
        }
      }
      toast('Quote deleted');
    } catch (e) {
      toast(`Delete failed: ${e.message}`);
    }
  });
}
