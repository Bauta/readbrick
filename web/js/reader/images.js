// Inline book images: figure factory + tap-to-zoom lightbox.
//
// The reader flattens chapters→paragraphs and renders each as <p data-idx=N>.
// `book.images` carries {src, after_idx, alt}; this module turns each into a
// quiet "plate" figure interleaved after its anchor paragraph, and provides a
// single, theme-aware lightbox for tap-to-zoom. Pure DOM — no app state, so it
// can be unit-tested and reused without booting the reader.

// ───── grouping ─────

// Group images by their `after_idx` anchor, preserving document order within
// each bucket. `-1` means "before the first paragraph"; several images may
// share an anchor (consecutive plates), so each value is an array.
export function groupImagesByAnchor(images) {
  const byAnchor = new Map();
  for (const image of images || []) {
    const anchor = image.after_idx;
    if (!byAnchor.has(anchor)) byAnchor.set(anchor, []);
    byAnchor.get(anchor).push(image);
  }
  return byAnchor;
}

// ───── figure factory ─────

// <figure class="reader-image"><img class="reader-image-img" loading="lazy" …>
// A successful load fades the plate in (CSS `.loaded`); a broken src hides the
// whole figure so the prose closes back up with no empty gap. Clicking the
// figure opens the lightbox on the full image.
export function createFigure(image) {
  const figure = document.createElement('figure');
  figure.className = 'reader-image';

  const img = document.createElement('img');
  img.className = 'reader-image-img';
  img.loading = 'lazy';
  img.decoding = 'async';
  img.alt = image.alt || '';

  // Wire load/error BEFORE assigning src so a cached image can't fire its
  // load event before we're listening (which would leave the plate stuck at
  // opacity:0). The `complete` check below covers the synchronous-cache case.
  img.addEventListener('load', () => figure.classList.add('loaded'));
  img.addEventListener('error', () => { figure.classList.add('broken'); });
  img.src = image.src;
  if (img.complete && img.naturalWidth > 0) figure.classList.add('loaded');

  figure.appendChild(img);
  figure.addEventListener('click', () => openLightbox(image.src, image.alt || ''));
  return figure;
}

// ───── lightbox ─────

// Single overlay shared by every figure. Built lazily into #image-lightbox by
// initLightbox(); `openLightbox` is the bridge the figures call.
let _controller = null;

function openLightbox(src, alt) {
  if (_controller) _controller.open(src, alt);
}

// Build + wire the fullscreen viewer once. Idempotent: a `data-ready` guard
// means repeat calls (e.g. across re-renders) are no-ops. Dismiss on backdrop
// tap, the close affordance, or Esc; focus moves into the overlay on open and
// returns to the originating figure on close.
export function initLightbox() {
  const root = document.getElementById('image-lightbox');
  if (!root || root.dataset.ready === '1') return;
  root.dataset.ready = '1';

  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-label', 'Image viewer');

  const img = document.createElement('img');
  img.className = 'lightbox-img';
  img.alt = '';

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'lightbox-close';
  closeBtn.setAttribute('aria-label', 'Close image');
  closeBtn.textContent = '✕';

  root.replaceChildren(closeBtn, img);

  const prefersReducedMotion = () =>
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let lastFocus = null;

  const open = (src, alt) => {
    lastFocus = document.activeElement;
    img.src = src;
    img.alt = alt || '';
    root.hidden = false;
    document.body.classList.add('lightbox-open');
    // Next frame so the .open transition (opacity + scale) actually plays.
    requestAnimationFrame(() => {
      root.classList.add('open');
      closeBtn.focus({ preventScroll: true });
    });
  };

  const close = () => {
    if (root.hidden) return;
    root.classList.remove('open');
    document.body.classList.remove('lightbox-open');
    if (lastFocus && typeof lastFocus.focus === 'function') {
      lastFocus.focus({ preventScroll: true });
    }
    lastFocus = null;
    const settle = () => {
      // A fast re-open during the fade-out re-adds .open — don't hide then.
      if (root.classList.contains('open')) return;
      root.hidden = true;
      img.removeAttribute('src');
    };
    if (prefersReducedMotion()) settle();
    else {
      // Use transitionend so the close settle tracks the actual CSS duration
      // rather than a hardcoded copy of it. A fallback timeout guards against
      // edge cases where the event never fires (e.g. display:none mid-anim).
      const fallback = setTimeout(settle, 350);
      root.addEventListener('transitionend', function handler(e) {
        if (e.target !== root) return; // ignore child (img) transitions
        root.removeEventListener('transitionend', handler);
        clearTimeout(fallback);
        settle();
      });
    }
  };

  // Tapping anywhere on the overlay — backdrop, image, or the ✕ chip (which
  // bubbles here) — dismisses.
  root.addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !root.hidden) { e.preventDefault(); close(); }
  });

  _controller = { open, close };
}
