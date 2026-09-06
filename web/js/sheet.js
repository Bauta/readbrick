// Bottom sheet behaviour shared by the library and the reader.
//
// Three things every sheet here needs and used to get inconsistently:
//   - a Done button, because tapping the sliver of page above an 85%-tall
//     sheet is not a dismissal anyone can discover;
//   - swipe-down on the handle, because the handle promises it;
//   - `inert` while closed, because a sheet that is only translated off-screen
//     is still in the tab order, and a keyboard user Tab-bing through the page
//     lands inside settings they never opened.

const SWIPE_CLOSE_PX = 80;
const CLOSE_ANIM_MS = 240;

export function setupSheet({ sheet, backdrop, trigger, onOpen, onClose }) {
  const handle = sheet.querySelector('.sheet-handle');
  const done = sheet.querySelector('.sheet-done');

  const open = () => {
    onOpen?.();
    sheet.inert = false;
    sheet.classList.add('open');
    backdrop.hidden = false;
    requestAnimationFrame(() => backdrop.classList.add('open'));
  };
  const close = () => {
    sheet.classList.remove('open');
    backdrop.classList.remove('open');
    sheet.style.transform = '';
    setTimeout(() => { backdrop.hidden = true; sheet.inert = true; }, CLOSE_ANIM_MS);
    onClose?.();
  };
  const toggle = () => (sheet.classList.contains('open') ? close() : open());

  sheet.inert = true;                       // starts closed, and out of reach
  trigger?.addEventListener('click', toggle);
  backdrop.addEventListener('click', close);
  done?.addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sheet.classList.contains('open')) close();
  });

  // Swipe-down to dismiss. Tracked on the handle only, so dragging a slider
  // inside the sheet never accidentally closes it.
  if (handle) {
    let startY = null;
    handle.addEventListener('touchstart', (e) => { startY = e.touches[0].clientY; }, { passive: true });
    handle.addEventListener('touchmove', (e) => {
      if (startY === null) return;
      const dy = Math.max(0, e.touches[0].clientY - startY);
      sheet.style.transform = `translateY(${dy}px)`;
    }, { passive: true });
    handle.addEventListener('touchend', (e) => {
      if (startY === null) return;
      const dy = e.changedTouches[0].clientY - startY;
      startY = null;
      if (dy > SWIPE_CLOSE_PX) close();
      else sheet.style.transform = '';
    });
  }

  return { open, close, toggle };
}
