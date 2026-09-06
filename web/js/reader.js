// Reader page: TTS playback + word highlighting + progress.
import { api, session, toast } from './api.js';
import { humanizeAgo } from './util.js';
import { state, bookId, SKIP_SECONDS } from './reader/state.js';
import { setupSession } from './reader/session.js';
import { setupChapterSidebar } from './reader/chapters.js';
import { setupSleepTimer } from './reader/sleep.js';
import { applyQuoteHighlights, setupQuoteSelection, setupQuotePopover } from './reader/quotes.js';
import { initAutoscroll } from './reader/autoscroll.js';
import { initChromeAutoHide } from './reader/chrome-visibility.js';
import { initSeekGesture } from './reader/seek-gesture.js';
import { applyTheme as applyThemePref, markActiveTheme, revealDesktopTheme as revealDesktop } from '../js/theme.js';
import {
  initMediaSession, cumulativeWords, totalWords, estimateDuration, estimatePosition,
  paragraphAtPosition,
} from './reader/media-session.js';
import { createPrefetchRing } from './reader/prefetch-ring.js';
import { createAudioEngine } from './reader/audio-engine.js';
import { initDebugOverlay } from './reader/debug-overlay.js';
import { findCurrentWord } from './reader/word-tracker.js';
import { groupImagesByAnchor, createFigure, initLightbox } from './reader/images.js';
import { resolveFont, addRecent, readRecents, writeRecents, filterCatalog, injectAndEnsure } from './reader/fonts.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ───── boot ─────

async function boot() {
  if (!state.user) {
    location.href = '/';
    return;
  }
  state.book = await api.getBook(bookId);
  state.paragraphs = flattenParagraphs(state.book);
  $('#book-title').textContent = state.book.title;

  state.prefs = await api.getPrefs(state.user.id);
  state.quotes = await api.listQuotes(state.user.id, bookId).catch(() => []);
  state.voices = await api.listVoices();
  // If the user's stored voice no longer exists in the picker (e.g. the
  // upstream provider retired it), fall back to the first available voice.
  // Without this, every TTS request fails silently against the stale voice.
  if (state.voices.length > 0 && !state.voices.find((v) => v.voice_id === state.prefs.voice_id)) {
    state.prefs = await api.patchPrefs(state.user.id, { voice_id: state.voices[0].voice_id });
  }
  applyPrefs();
  populateVoices();

  renderParagraphs();

  const progress = await api.getProgress(state.user.id, bookId);
  state.curIdx = Math.min(progress.paragraph_idx || 0, state.paragraphs.length - 1);
  highlightParagraph(state.curIdx, /*scroll=*/true);
  updateProgressBar();

  // Warm the prefetch ring NOW (before the play tap). It's pure HTTP, so
  // paragraph curIdx..curIdx+4 begin preparing while the user orients on
  // the page — by the time they press play, paragraph 0 is cached.
  ensurePrefetchRing();
  state.prefetchRing.advance(state.curIdx);
  // Expose for the smoke-test harness before the engine exists.
  window.__readerState = state;

  setupControls();
  setupMediaSession();
  revealDesktopTheme();

  // Reposition the pill instantly when the content area resizes
  // (window resize, font size slider, line height slider, etc).
  const ro = new ResizeObserver(() => {
    if (state.curWordIdx < 0) return;
    const para = document.querySelector(`p[data-idx="${state.curIdx}"]`);
    if (!para) return;
    const span = para.querySelector(`span.w[data-w="${state.curWordIdx}"]`);
    if (span) movePillTo(span, { animate: false });
  });
  ro.observe(document.getElementById('reader-content'));

  const qs = new URLSearchParams(location.search);
  if (qs.get('settings') === '1') {
    setTimeout(() => $('#settings-btn').click(), 100);
  }
  if (qs.get('autoplay') === '1') {
    setTimeout(() => $('#play-btn').click(), 200);
  }

  // ?debug=1 → real-time sync overlay (top-right). No-op without the flag.
  initDebugOverlay({ state });
}

function flattenParagraphs(book) {
  const flat = [];
  for (const ch of book.chapters || []) {
    for (const p of ch.paragraphs || []) flat.push(p);
  }
  return flat;
}

// ───── rendering ─────

function renderParagraphs() {
  const main = $('#reader-content');
  // Preserve the pill element — replaceChildren() would destroy it.
  const pill = document.getElementById('highlight-pill');
  main.replaceChildren();
  if (pill) main.appendChild(pill);

  const imagesByAnchor = groupImagesByAnchor(state.book.images || []);
  const appendFigures = (idx) => {
    const list = imagesByAnchor.get(idx);
    if (!list) return;
    for (const img of list) main.appendChild(createFigure(img));
  };

  appendFigures(-1);  // images before the first paragraph
  for (const p of state.paragraphs) {
    const node = document.createElement('p');
    node.dataset.idx = String(p.idx);
    // Plain text initially; words get spans only once we have TTS timing.
    node.textContent = p.text;
    node.addEventListener('click', () => {
      // Route through engine.seek so the engine's resumeParaIdx + play state
      // stay consistent with what the UI shows. Falls back to the manual
      // state update if the engine isn't built yet (user tapped before play).
      if (state.engine) {
        state.engine.seek(p.idx, 0);
        highlightParagraph(p.idx, true);  // explicit user nav — scroll to it
      } else {
        state.curIdx = p.idx;
        highlightParagraph(state.curIdx, true);
        updateProgressBar();
        saveProgress();
      }
    });
    main.appendChild(node);
    applyQuoteHighlights(p.idx);
    appendFigures(p.idx);
  }
}

function highlightParagraph(idx, scroll = false) {
  $$('.reader-content p[data-idx]').forEach((p) => {
    p.classList.toggle('current', Number(p.dataset.idx) === idx);
  });
  if (scroll) {
    const node = document.querySelector(`p[data-idx="${idx}"]`);
    if (!node) return;
    // Use the autoscroll module's helper so the programmatic-scroll guard
    // prevents the resulting scroll events from suppressing word autoscroll.
    // Fallback to direct scrollIntoView for initial book-load (before
    // setupControls() has set state.autoscroll).
    if (state.autoscroll) state.autoscroll.scrollToElement(node);
    else node.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

function renderWordsInParagraph(idx, words) {
  const node = document.querySelector(`p[data-idx="${idx}"]`);
  if (!node || !words || words.length === 0) return;
  node.replaceChildren();
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const span = document.createElement('span');
    span.className = 'w';
    span.dataset.w = String(i);
    span.textContent = w.text;
    // Tap-to-seek-to-this-word. We ALWAYS stop the click from bubbling to
    // the paragraph's handler. Otherwise tapping a word would trigger the
    // paragraph-tap handler (which routes through engine.seek and causes a
    // redundant seek or scroll).
    span.addEventListener('click', (e) => {
      e.stopPropagation();
      // Seek whether playing or paused — engine.seek preserves play state.
      if (!state.engine) return;
      seekToWord(idx, i);
    });
    node.appendChild(span);
    if (i < words.length - 1) node.appendChild(document.createTextNode(' '));
  }
  applyQuoteHighlights(idx);
}

// ───── playback ─────

async function play() {
  if (state.paragraphs.length === 0) return;
  $('#play-btn').textContent = '⏳︎';  // preparing audio…
  await ensureEngine();
  state.playing = true;
  state.engine.play();
  mediaSession?.setPlaying(true);
}

function pause() {
  state.playing = false;
  $('#play-btn').textContent = '▶︎';
  if (state.engine) state.engine.pause();
  mediaSession?.setPlaying(false);
}

function stop() {
  pause();
  clearCurrentWord();
}

function togglePlay() {
  if (state.playing) pause(); else play();
}

function advanceParagraph(delta = 1) {
  const newIdx = Math.max(0, Math.min(state.paragraphs.length - 1, state.curIdx + delta));
  if (state.engine) {
    state.engine.seek(newIdx, 0);
  } else {
    state.curIdx = newIdx;
    highlightParagraph(state.curIdx, true);
    updateProgressBar();
    saveProgress();
  }
  if (_sleepTimer) _sleepTimer.checkChapterFire();
}

function clearCurrentWord() {
  const cur = document.querySelector('span.w.current');
  if (cur) cur.classList.remove('current');
  state.curWordIdx = -1;
  hidePill();
}

// ───── word highlighting via timeupdate ─────

function ensureWordsRendered(paraIdx) {
  const slot = state.prefetchRing.getResolved(paraIdx);
  if (!slot || slot._rendered) return;
  renderWordsInParagraph(paraIdx, slot.words);
  slot._rendered = true;
}

function onTimeUpdate() {
  if (!state.engine) return;
  const paraIdx = state.engine.currentParagraphIdx();
  ensureWordsRendered(paraIdx);
  const slot = state.prefetchRing.getResolved(paraIdx);
  if (!slot || !slot.words || slot.words.length === 0) return;

  // engine.currentTime() is the HTML5 <audio> element's currentTime — the
  // AUDIBLE playback position in MP3-frame seconds. Word timings (from
  // Kokoro's native timestamps) are also in MP3-frame ms. No latency math,
  // no padding compensation: pill matches voice because both are measured
  // against the same clock.
  const localMs = state.engine.currentTime() * 1000;
  const idx = findCurrentWord(slot.words, localMs);
  if (idx === state.curWordIdx) return;

  const para = document.querySelector(`p[data-idx="${paraIdx}"]`);
  if (!para) return;

  if (state.curWordIdx >= 0) {
    const prev = para.querySelector(`span.w[data-w="${state.curWordIdx}"]`);
    if (prev) prev.classList.remove('current');
  }
  if (idx >= 0) {
    const cur = para.querySelector(`span.w[data-w="${idx}"]`);
    if (cur) { cur.classList.add('current'); movePillTo(cur); }
  }
  state.curWordIdx = idx;
}

// ───── pill positioning ─────

function movePillTo(spanEl, { animate = true } = {}) {
  const pill = document.getElementById('highlight-pill');
  if (!pill) return;
  if (!spanEl) {
    pill.classList.remove('active');
    return;
  }

  const container = document.getElementById('reader-content');
  if (!container) return;
  const cRect = container.getBoundingClientRect();
  const newRect = spanEl.getBoundingClientRect();
  const newLeft = newRect.left - cRect.left + container.scrollLeft;
  const newTop  = newRect.top  - cRect.top  + container.scrollTop;

  // Step 1: teleport (top/left/width/height have no CSS transition; see style.css)
  pill.style.left = newLeft + 'px';
  pill.style.top  = newTop  + 'px';
  pill.style.width  = newRect.width  + 'px';
  pill.style.height = newRect.height + 'px';
  pill.classList.add('active');

  if (!animate) {
    pill.style.transform = 'scale(1)';
    pill.style.opacity = '1';
    return;
  }

  // Step 2: pop-in landing — set the pill to a SMALLER scale and a partial
  // opacity, force a reflow, then transition both back to full size + full
  // opacity. This produces a visible "punch in" animation every time the
  // pill lands on a new word, instead of just changing width invisibly.
  pill.style.transition = 'none';
  pill.style.transform = 'scale(0.78)';
  pill.style.opacity = '0.4';
  // Force layout/paint so the next style change actually triggers the transition.
  // eslint-disable-next-line no-unused-expressions
  pill.offsetWidth;
  pill.style.transition = '';  // restore CSS default (transform + opacity spring)
  pill.style.transform = 'scale(1)';
  pill.style.opacity = '1';
}

function hidePill() {
  const pill = document.getElementById('highlight-pill');
  if (pill) pill.classList.remove('active');
}

// ───── progress save ─────

function saveProgress() {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(() => {
    api.putProgress(state.user.id, bookId, state.curIdx).catch(() => {});
  }, 500);
}

function updateProgressBar() {
  const total = state.paragraphs.length;
  const idx = state.curIdx;
  $('#prog-text').textContent = `${idx + 1} / ${total}`;
  $('#prog-fill').style.width = `${total > 0 ? ((idx + 1) / total) * 100 : 0}%`;
}

// ───── prefs / settings ─────

function fmtSpeed(s) {
  return `${(Math.round(s * 100) / 100).toFixed(s % 1 === 0 ? 1 : 2)}×`;
}

// Drop the prefetch ring (its audio was synthesized at the old voice/speed) and
// reload the current paragraph so the (audio, words) pair matches. Shared by the
// voice and speed controls. Playback rate stays 1.0 — speed is baked into the
// audio by Kokoro, which keeps the pill synced.
function rewarmCurrentParagraph() {
  if (!state.prefetchRing) return;
  if (!state.engine) {
    state.prefetchRing.reset();
    state.prefetchRing.advance(state.curIdx);
    return;
  }
  const wasPlaying = !state.engine.isPaused();
  const curIdx = state.engine.currentParagraphIdx();
  state.engine.pause();
  state.prefetchRing.reset();
  state.engine.seek(curIdx, 0);
  if (wasPlaying) state.engine.play();
}

// Apply a new playback speed. Speed is Kokoro's native rate, baked into the
// synthesized audio (the model paces the speech and emits matching word
// timings), so changing it re-synthesizes the current paragraph at the new pace.
function applySpeed(next) {
  if (next === state.prefs.speed) return;
  state.prefs = { ...state.prefs, speed: next };   // optimistic so the refetch uses the new speed
  patchPref({ speed: next });
  rewarmCurrentParagraph();
}

const BUNDLED_KEYS = ['sans', 'serif', 'slab', 'hyperlegible', 'dyslexic'];
let fontCatalog = null; // {bundled, families}, loaded lazily

function applyPrefs() {
  document.documentElement.style.setProperty('--reader-font-size', `${state.prefs.font_size}px`);
  document.documentElement.style.setProperty('--reader-line-height', String(state.prefs.line_height));
  const tw = state.prefs.text_width ?? 70;
  document.documentElement.style.setProperty('--reader-measure', `${tw}ch`);
  const fontFamily = state.prefs.font_family || 'serif';
  const resolved = resolveFont(fontFamily, BUNDLED_KEYS);
  document.documentElement.style.setProperty('--reader-font-family', resolved.cssValue);
  if (!resolved.isBundled) {
    injectAndEnsure(resolved.family).catch(() => {
      toast("Couldn't load that font — check your connection");
    });
  }
  applyTheme();

  $('#speed-val').textContent = fmtSpeed(state.prefs.speed);
  $('#speed').value = String(state.prefs.speed);
  $('#font-size').value = String(state.prefs.font_size);
  $('#fs-val').textContent = `${state.prefs.font_size} px`;
  $('#line-height').value = String(state.prefs.line_height);
  $('#lh-val').textContent = state.prefs.line_height.toFixed(1);
  $('#text-width').value = String(tw);
  $('#tw-val').textContent = String(tw);

  markActiveTheme($('.theme-toggle'), state.prefs.theme);
  renderFontSelect(fontFamily);

  const showImages = (state.prefs.show_images ?? 1) ? true : false;
  document.body.classList.toggle('hide-images', !showImages);
  const imgToggle = $('#show-images-toggle');
  if (imgToggle) imgToggle.checked = showImages;
}

function populateVoices() {
  const sel = $('#voice-select');
  sel.replaceChildren();
  if (state.voices.length === 0) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No voices installed';
    sel.appendChild(opt);
    sel.disabled = true;
    return;
  }
  // Group by language so the voices stay browsable.
  const LANG_LABEL = { en: 'English' };
  const groups = new Map();
  for (const v of state.voices) {
    const lang = v.language || 'other';
    if (!groups.has(lang)) groups.set(lang, []);
    groups.get(lang).push(v);
  }
  for (const [lang, voices] of groups) {
    const og = document.createElement('optgroup');
    og.label = LANG_LABEL[lang] || lang;
    for (const v of voices) {
      const opt = document.createElement('option');
      opt.value = v.voice_id;
      opt.textContent = v.label || v.voice_id;
      if (v.voice_id === state.prefs.voice_id) opt.selected = true;
      og.appendChild(opt);
    }
    sel.appendChild(og);
  }
}

async function patchPref(patch) {
  state.prefs = await api.patchPrefs(state.user.id, patch);
  applyPrefs();
}

// Minimal slug matching the server's slugify: family → url-safe id.
function slugify(family) {
  return family.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

// Rebuild the font <select>: bundled optgroup + downloaded optgroup from recents.
function renderFontSelect(activeFamily) {
  const sel = document.getElementById('font-select');
  if (!sel) return;
  sel.replaceChildren();

  const og1 = document.createElement('optgroup');
  og1.label = 'Built-in';
  const BUNDLED_OPTS = [
    { key: 'sans', label: 'Sans-serif' },
    { key: 'serif', label: 'Serif' },
    { key: 'slab', label: 'Slab serif' },
    { key: 'hyperlegible', label: 'Hyperlegible' },
    { key: 'dyslexic', label: 'OpenDyslexic' },
  ];
  for (const { key, label } of BUNDLED_OPTS) {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = label;
    if (key === activeFamily) opt.selected = true;
    og1.appendChild(opt);
  }
  sel.appendChild(og1);

  const recents = readRecents();
  // If the active font is a Google family not yet in recents, include it first.
  const isBundledActive = BUNDLED_KEYS.includes(activeFamily);
  const families = (!isBundledActive && activeFamily && !recents.includes(activeFamily))
    ? [activeFamily, ...recents]
    : recents;

  if (families.length > 0) {
    const og2 = document.createElement('optgroup');
    og2.label = 'Downloaded';
    for (const fam of families) {
      const opt = document.createElement('option');
      opt.value = fam;
      opt.textContent = fam;
      if (fam === activeFamily) opt.selected = true;
      og2.appendChild(opt);
    }
    sel.appendChild(og2);
  }
}

// Render the font panel list: downloaded-fonts manage view or catalog search results.
function renderFontPanel(query) {
  const list = document.getElementById('font-panel-list');
  if (!list) return;
  list.replaceChildren();

  const q = (query || '').trim();
  const recents = readRecents();

  if (!q) {
    // Manage view: downloaded fonts with delete buttons.
    if (recents.length === 0) {
      const li = document.createElement('li');
      li.className = 'font-panel-empty';
      li.textContent = 'No downloaded fonts yet — search above to add one.';
      list.appendChild(li);
      return;
    }
    for (const fam of recents) {
      list.appendChild(makeFontRow(fam, /*showDelete=*/true));
    }
  } else {
    // Search view: catalog results; downloaded ones show their delete button.
    const results = filterCatalog(fontCatalog?.families || [], q);
    if (results.length === 0) {
      const li = document.createElement('li');
      li.className = 'font-panel-empty';
      li.textContent = 'No results';
      list.appendChild(li);
      return;
    }
    for (const f of results) {
      list.appendChild(makeFontRow(f.family, recents.includes(f.family)));
    }
  }
}

function makeFontRow(family, showDelete) {
  const li = document.createElement('li');
  li.className = 'font-panel-item';

  const nameBtn = document.createElement('button');
  nameBtn.type = 'button';
  nameBtn.className = 'font-panel-name';
  nameBtn.textContent = family;
  nameBtn.addEventListener('click', () => pickFont(family));
  li.appendChild(nameBtn);

  if (showDelete) {
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'font-panel-del';
    delBtn.textContent = '✕';
    delBtn.setAttribute('aria-label', `Remove ${family}`);
    delBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      deleteFont(family);
    });
    li.appendChild(delBtn);
  }
  return li;
}

async function ensureCatalog() {
  if (!fontCatalog) fontCatalog = await api.getFontCatalog();
  return fontCatalog;
}

// Escape-to-close handler, bound only while the panel is open so keyboard
// users can dismiss it without tabbing back to the trigger.
let fontPanelEscHandler = null;

async function openFontPanel() {
  const panel = document.getElementById('font-panel');
  if (!panel) return;
  panel.hidden = false;
  const moreBtn = document.getElementById('font-more-btn');
  if (moreBtn) moreBtn.setAttribute('aria-expanded', 'true');
  fontPanelEscHandler = (e) => {
    if (e.key === 'Escape') { closeFontPanel(); if (moreBtn) moreBtn.focus(); }
  };
  document.addEventListener('keydown', fontPanelEscHandler);
  const input = document.getElementById('font-search-input');
  if (input) { input.value = ''; input.focus(); }
  renderFontPanel('');
  // Load catalog in background; re-render if user has already typed.
  await ensureCatalog();
  const q = input ? input.value : '';
  if (q) renderFontPanel(q);
}

function closeFontPanel() {
  const panel = document.getElementById('font-panel');
  if (panel) panel.hidden = true;
  const moreBtn = document.getElementById('font-more-btn');
  if (moreBtn) moreBtn.setAttribute('aria-expanded', 'false');
  if (fontPanelEscHandler) {
    document.removeEventListener('keydown', fontPanelEscHandler);
    fontPanelEscHandler = null;
  }
  const input = document.getElementById('font-search-input');
  if (input) input.value = '';
}

// Apply a font family: bundled key or Google family name.
async function pickFont(family) {
  const bundled = (fontCatalog?.bundled || []).find((b) => b.family === family);
  if (bundled) {
    closeFontPanel();
    await patchPref({ font_family: bundled.key });
    return;
  }
  // Google font: ensure the server has cached it + inject @font-face before
  // applying. Close the panel first so a slow download can't be raced by a
  // second pick, and bail on failure so a font that won't load never sticks in
  // recents/prefs (a stuck pref would re-trigger the failure on every reload).
  closeFontPanel();
  try {
    await injectAndEnsure(family);
  } catch {
    toast("Couldn't load that font — check your connection");
    return;
  }
  writeRecents(addRecent(readRecents(), family));
  await patchPref({ font_family: family });
}

// Remove a downloaded Google font from recents + server cache.
async function deleteFont(family) {
  const slug = slugify(family);
  writeRecents(readRecents().filter((f) => f !== family));
  fetch(`/api/fonts/${slug}`, { method: 'DELETE' }).catch(() => {});

  const activeFamily = state.prefs.font_family || 'serif';
  if (activeFamily === family) {
    // Fall back to default serif; patchPref → applyPrefs → renderFontSelect.
    await patchPref({ font_family: 'serif' });
  } else {
    renderFontSelect(activeFamily);
  }
  // Refresh the panel to reflect the deletion.
  renderFontPanel(document.getElementById('font-search-input')?.value || '');
}

// ───── controls wiring ─────

function skipSeconds(delta) {
  if (state.engine) state.engine.skip(delta);
}

function seekToParagraph(idx) {
  if (idx < 0 || idx >= state.paragraphs.length) return;
  if (state.engine) {
    state.engine.seek(idx, 0);
  } else {
    state.curIdx = idx;
    highlightParagraph(idx, true);
    updateProgressBar();
    saveProgress();
  }
}

function seekToWord(paraIdx, wordIdx) {
  if (!state.engine) return;
  const slot = state.prefetchRing.getResolved(paraIdx);
  if (!slot || !slot.words || !slot.words[wordIdx]) {
    state.engine.seek(paraIdx, 0);
    return;
  }
  const localSec = slot.words[wordIdx].start_ms / 1000;
  state.engine.seek(paraIdx, localSec);
}

// Sleep timer is wired in setupControls; this module-level handle is
// what advanceParagraph reaches into for end-of-chapter firing.
let _sleepTimer = null;

// Build the prefetch ring once. Pure HTTP (/api/tts) — no AudioContext,
// no user gesture — so it can run at book-open to warm paragraph 0 before
// the play tap. Idempotent.
function ensurePrefetchRing() {
  if (state.prefetchRing) return;
  state.prefetchRing = createPrefetchRing({
    // Realtime synthesis (no cache) makes each slot a fresh ~2-3s synth, so keep
    // the look-ahead small: current + 2 is enough to stay gapless at Kokoro's
    // ~4.4x realtime, and a small window keeps a voice/speed change (which
    // re-synthesizes the window) from flooding the serialized synth lock.
    size: 3,
    totalParas: state.paragraphs.length,
    fetchAndDecode: async (paraIdx) => {
      const p = state.paragraphs[paraIdx];
      const tts = await api.tts(
        p.text, state.prefs.voice_id, state.book.language, state.prefs.speed,
      );
      // Realtime: the server returns the audio inline (base64). Wrap it in a
      // blob URL the <audio> element can load; the ring revokes it on eviction.
      const bin = atob(tts.audio_b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blobUrl = URL.createObjectURL(
        new Blob([bytes], { type: tts.format === 'mp3' ? 'audio/mpeg' : 'audio/wav' }),
      );
      const lastEnd = tts.words?.length ? tts.words[tts.words.length - 1].end_ms : 0;
      return {
        words: tts.words,
        aligner: tts.aligner,
        audioUrl: blobUrl,
        blobUrl,            // retained so prefetch-ring can revokeObjectURL on evict
        duration: lastEnd / 1000,
      };
    },
  });
}

// ensureEngine is assigned inside setupControls (where AudioContext subs live)
// and used by the module-level play() which fires on user gesture.
let ensureEngine = async () => {};

// The server's answer about the desktop — { available, mode } — once known.
// Declared up here because applyTheme reads it before the fetch resolves.
let _desktop = null;

// Just the theme attribute — deliberately not the whole of applyPrefs, which
// re-injects the reader font and would fire a second network load (and a
// second failure toast) every time the theme is re-applied. The resolution
// rules live in theme.js, shared with the library.
function applyTheme() {
  applyThemePref(state.prefs.theme, _desktop);
}

// ───── Desktop palette (Omarchy) ─────
//
// One more option beside Light / Sepia / Dark / Auto, never a replacement for
// them: the reader is used on phones too, where the desktop's theme means
// nothing. The colours themselves arrive as /api/theme.css.
async function revealDesktopTheme() {
  _desktop = await revealDesktop($('.theme-toggle'));
  applyTheme();   // re-apply now that Auto has a better answer
  if (!_desktop?.available && state.prefs?.theme === 'omarchy') {
    // Stored preference for a palette this machine can no longer supply —
    // fall back rather than render an unstyled page. Fire-and-forget: the
    // fallback is cosmetic, and boot() must not stall on it.
    patchPref({ theme: 'auto' }).catch(() => {});
  }
}

// ───── MediaSession (→ MPRIS on Linux) ─────
//
// Lets the desktop see and drive playback: media keys, and the Omarchy bar
// widget. See reader/media-session.js for why album carries the app name and
// why position is only published on paragraph boundaries.
let mediaSession = null;
let _cumWords = [];
let _totalWords = 0;

function mediaDuration() {
  return estimateDuration(state.book, state.prefs?.speed);
}

function publishMediaPosition() {
  if (!mediaSession) return;
  const duration = mediaDuration();
  mediaSession.setPosition(
    duration,
    estimatePosition(_cumWords, _totalWords, duration, state.curIdx),
    // The <audio> element always runs at 1.0 — the chosen speed is baked into
    // the synthesized audio by the prefetch ring, not applied as a rate.
    1,
  );
}

function setupMediaSession() {
  _cumWords = cumulativeWords(state.paragraphs);
  _totalWords = totalWords(state.paragraphs);

  mediaSession = initMediaSession({
    onPlay: () => play(),
    onPause: () => pause(),
    // No stop() here, unlike the footer buttons: a media key meaning "next
    // track" must not halt reading. advanceParagraph seeks the engine, which
    // keeps playing if it already was.
    onPrev: () => { advanceParagraph(-1); publishMediaPosition(); },
    onNext: () => { advanceParagraph(1); publishMediaPosition(); },
    // Republish after any seek that stays inside a paragraph — the paragraph
    // -change subscription would not fire, leaving the bus position stale.
    onSeekBy: (delta) => { skipSeconds(delta); publishMediaPosition(); },
    onSeekTo: (seconds) => {
      const idx = paragraphAtPosition(_cumWords, _totalWords, mediaDuration(), seconds);
      if (state.engine) state.engine.seek(idx, 0);
      publishMediaPosition();
    },
  });

  // Leaving the page should retract the player rather than leave a stale one
  // on the bus for the desktop to keep showing.
  window.addEventListener('pagehide', () => mediaSession?.clear());
  mediaSession.setBook(state.book, `/api/books/${bookId}/cover`);
  mediaSession.setPlaying(false);
  publishMediaPosition();
}

function setupControls() {
  // ───── Engine subscription chains ─────
  const playSubs = [], pauseSubs = [], paraSubs = [];
  function _engineOnPlay()           { for (const fn of playSubs)  fn(); }
  function _engineOnPause()          { for (const fn of pauseSubs) fn(); }
  function _engineOnParaChange(idx)  { for (const fn of paraSubs)  fn(idx); }
  function addOnPlay(fn)         { playSubs.push(fn); }
  function addOnPause(fn)        { pauseSubs.push(fn); }
  function addOnParaChange(fn)   { paraSubs.push(fn); }

  // ───── Lazy engine construction (deferred until first play so the
  // browser doesn't tie up audio resources before they're needed) ─────
  ensureEngine = async function() {
    if (state.engine) return;
    ensurePrefetchRing();
    state.engine = createAudioEngine({
      prefetchRing: state.prefetchRing,
      getTotalParas: () => state.paragraphs.length,
      getDurations: () => state.paragraphs.map((p, i) => {
        const slot = state.prefetchRing.getResolved(i);
        if (slot?.duration) return slot.duration;
        // Rough estimate for paragraphs not yet fetched (~14 chars/sec).
        return (p.text?.length || 0) / 14;
      }),
    });
    state.engine.onPlay = _engineOnPlay;
    state.engine.onPause = _engineOnPause;
    state.engine.onParagraphChange = (newIdx) => {
      // Clear any stale current-word marker from the previous paragraph BEFORE
      // touching state.curIdx. onTimeUpdate's cleanup only queries within the
      // current paragraph; without this, a `.current` class can leak across
      // paragraphs and the autoscroller will keep tracking the old word.
      $$('span.w.current').forEach((el) => el.classList.remove('current'));
      state.curWordIdx = -1;
      hidePill();

      state.curIdx = newIdx;
      highlightParagraph(state.curIdx, false);
      // Soft-scroll the new paragraph to the vertical center on each paragraph
      // change (the programmatic-scroll guard keeps this from registering as
      // user interaction). Per-word scrolling is gone — the pill still tracks
      // words, but the page only moves between paragraphs.
      const paraNode = document.querySelector(`p[data-idx="${state.curIdx}"]`);
      if (paraNode) autoscroll.scrollToElement(paraNode);
      updateProgressBar();
      saveProgress();
      _engineOnParaChange(newIdx);
    };
    // Position the engine at the user's saved-progress paragraph. Without
    // this, the engine always starts at paragraph 0 even when state.curIdx
    // is 42 (resumed reading). The result is audio playing from the book's
    // start while the UI highlights paragraph 42, with the autoscroller
    // then dragging the page UP to wherever the audio actually is — visible
    // as "page jumps to the top on first play".
    if (state.curIdx > 0) state.engine.seek(state.curIdx, 0);
    // No playbackRate adjustment: the saved speed is Kokoro's native rate, baked
    // into the audio by the prefetch ring (which fetches at state.prefs.speed),
    // so the element plays at 1.0× and the pill stays synced.
    // Expose for the smoke test harness.
    window.__readerEngine = state.engine;
    window.__readerState = state;
  }

  // Tap progress bar to jump to a paragraph. Paused-only (the
  // CSS body.audio-playing rule already makes the cursor `default`
  // during playback as a hint).
  const progressTrack = document.querySelector('.reader-footer-progress .progress-track');
  if (progressTrack) {
    progressTrack.addEventListener('click', (e) => {
      if (!state.engine || !state.engine.isPaused()) return;
      const rect = progressTrack.getBoundingClientRect();
      const fraction = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const n = state.paragraphs.length;
      const newIdx = Math.max(0, Math.min(n - 1, Math.floor(fraction * n)));
      seekToParagraph(newIdx);
    });
  }

  $('#play-btn').addEventListener('click', togglePlay);
  $('#prev-btn').addEventListener('click', () => { stop(); advanceParagraph(-1); });
  $('#next-btn').addEventListener('click', () => { stop(); advanceParagraph(1); });

  // Speed slider (in settings sheet). Live-update the label while dragging;
  // re-synthesize only on release (change), since each speed re-renders audio.
  $('#speed').addEventListener('input', (e) => {
    $('#speed-val').textContent = fmtSpeed(parseFloat(e.target.value));
  });
  $('#speed').addEventListener('change', (e) => {
    applySpeed(parseFloat(e.target.value));
  });

  $('#font-size').addEventListener('input', (e) => {
    const v = parseInt(e.target.value, 10);
    document.documentElement.style.setProperty('--reader-font-size', `${v}px`);
    $('#fs-val').textContent = `${v} px`;
    patchPref({ font_size: v });
  });

  $('#line-height').addEventListener('input', (e) => {
    const v = parseFloat(e.target.value);
    document.documentElement.style.setProperty('--reader-line-height', String(v));
    $('#lh-val').textContent = v.toFixed(1);
    patchPref({ line_height: v });
  });

  $('#text-width').addEventListener('input', (e) => {
    const v = parseInt(e.target.value, 10);
    document.documentElement.style.setProperty('--reader-measure', `${v}ch`);
    $('#tw-val').textContent = String(v);
    patchPref({ text_width: v });
  });

  $('#voice-select').addEventListener('change', async (e) => {
    await patchPref({ voice_id: e.target.value });
    // The ring's slots were synthesized with the old voice — drop them and
    // reload the current paragraph with the new one.
    rewarmCurrentParagraph();
  });

  $$('.theme-toggle button').forEach((btn) => {
    btn.addEventListener('click', () => {
      patchPref({ theme: btn.dataset.theme });
    });
  });

  $('#font-select').addEventListener('change', (e) => {
    patchPref({ font_family: e.target.value });
  });

  $('#font-more-btn').addEventListener('click', async () => {
    if ($('#font-panel').hidden) await openFontPanel();
    else closeFontPanel();
  });

  $('#font-search-input').addEventListener('input', (e) => {
    renderFontPanel(e.target.value);
  });

  const imgToggle = $('#show-images-toggle');
  if (imgToggle) {
    imgToggle.addEventListener('change', (e) => {
      const on = e.target.checked;
      document.body.classList.toggle('hide-images', !on);
      patchPref({ show_images: on ? 1 : 0 });
    });
  }
  initLightbox();

  // Settings sheet open/close with backdrop
  const sheet = $('#settings-sheet');
  const backdrop = $('#sheet-backdrop');
  const openSheet = () => {
    closeFontPanel();
    sheet.classList.add('open');
    backdrop.hidden = false;
    requestAnimationFrame(() => backdrop.classList.add('open'));
  };
  const closeSheet = () => {
    sheet.classList.remove('open');
    backdrop.classList.remove('open');
    setTimeout(() => { backdrop.hidden = true; }, 240);
  };
  $('#settings-btn').addEventListener('click', () => {
    if (sheet.classList.contains('open')) closeSheet();
    else openSheet();
  });
  backdrop.addEventListener('click', closeSheet);

  // Keep the desktop's view of playback honest. Subscribing to the engine
  // rather than to play()/pause() matters: the engine also pauses on its own
  // (autoplay rejection, end of book), and those paths never call pause().
  addOnPlay(() => mediaSession?.setPlaying(true));
  addOnPause(() => mediaSession?.setPlaying(false));
  // Paragraph boundaries are the only cadence position is published at — on a
  // timer it produces a 1 Hz Seeked storm on the bus.
  addOnParaChange(() => publishMediaPosition());

  // Body class drives the cursor gates in style.css — seek-to-position
  // targets are only clickable when audio is paused.
  addOnPlay(() => document.body.classList.add('audio-playing'));
  addOnPause(() => {
    document.body.classList.remove('audio-playing');
    // If a play() attempt was rejected (e.g. autoplay policy) the engine
    // fires onPause without going through reader.js's pause(); make sure the
    // "preparing audio" glyph doesn't stick.
    if ($('#play-btn').textContent === '⏳︎') $('#play-btn').textContent = '▶︎';
  });

  // Drive onTimeUpdate via requestAnimationFrame for smooth ~60Hz pill tracking.
  // The engine's pill positioning replaces the audio element's timeupdate event.
  const autoscroll = initAutoscroll({
    scrollContainer: document.getElementById('reader-content'),
  });
  state.autoscroll = autoscroll;
  let rafId = null;
  const tick = () => {
    if (!state.engine || state.engine.isPaused()) { rafId = null; return; }
    // Clear the "preparing…" glyph once audio is actually progressing.
    if (state.engine.currentTime() > 0 && $('#play-btn').textContent === '⏳︎') {
      $('#play-btn').textContent = '⏸︎';
    }
    onTimeUpdate();
    autoscroll.maybeScroll();
    rafId = requestAnimationFrame(tick);
  };
  addOnPlay(() => { if (rafId === null) rafId = requestAnimationFrame(tick); });

  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
    if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
    else if (e.code === 'ArrowRight') { stop(); advanceParagraph(1); }
    else if (e.code === 'ArrowLeft') { stop(); advanceParagraph(-1); }
    else if (e.key === '+' || e.key === '=') {
      const cur = parseInt($('#font-size').value, 10);
      $('#font-size').value = String(Math.min(28, cur + 1));
      $('#font-size').dispatchEvent(new Event('input'));
    } else if (e.key === '-') {
      const cur = parseInt($('#font-size').value, 10);
      $('#font-size').value = String(Math.max(14, cur - 1));
      $('#font-size').dispatchEvent(new Event('input'));
    }
  });

  initSeekGesture({
    onSeek: (delta) => skipSeconds(delta),
    flashLeft: document.getElementById('seek-flash-left'),
    flashRight: document.getElementById('seek-flash-right'),
  });

  // First-run hint for the seek gesture. Shown once after first playback.
  const SEEK_HINT_KEY = 'reader.seenSeekHint';
  if (localStorage.getItem(SEEK_HINT_KEY) !== '1') {
    const hint = document.getElementById('seek-hint');
    let hintShown = false;
    const showHintOnce = () => {
      if (hintShown) return;
      hintShown = true;
      hint.hidden = false;
      requestAnimationFrame(() => hint.classList.add('visible'));
      const dismiss = () => {
        hint.classList.remove('visible');
        setTimeout(() => { hint.hidden = true; }, 260);
        localStorage.setItem(SEEK_HINT_KEY, '1');
        hint.removeEventListener('click', dismiss);
      };
      hint.addEventListener('click', dismiss);
      setTimeout(dismiss, 4000);
    };
    addOnPlay(showHintOnce);
  }

  initChromeAutoHide({
    isPaused: () => !state.engine || state.engine.isPaused(),
    addOnPlay,
    addOnPause,
  });
  setupSession({ addOnPlay, addOnPause });

  setupQuoteSelection();
  setupQuotePopover();
  _sleepTimer = setupSleepTimer({ pauseAudio: pause });
  setupChapterSidebar({ seekToParagraph });
}

boot().catch((e) => {
  toast(`Failed to load: ${e.message}`);
});
