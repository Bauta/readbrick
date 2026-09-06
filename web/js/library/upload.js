// Drag/drop + upload-zone wiring. Pure DOM module; emits onUploaded(book).
import { api, toast } from '../api.js';

const $ = (sel) => document.querySelector(sel);

export function setupUploadZone({ getUser, onUploaded }) {
  const zone = $('#upload-zone');
  const input = $('#file-input');
  const btn = $('#upload-btn');

  const triggerPicker = () => {
    if (!getUser()) { toast('Pick a user first'); return; }
    zone.hidden = false;
    input.click();
  };
  btn.addEventListener('click', triggerPicker);
  zone.addEventListener('click', () => input.click());
  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', async (e) => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files[0]) await doUpload(e.dataTransfer.files[0], { getUser, onUploaded });
  });
  input.addEventListener('change', async () => {
    if (input.files[0]) await doUpload(input.files[0], { getUser, onUploaded });
    input.value = '';
  });
}

async function doUpload(file, { getUser, onUploaded }) {
  if (!getUser()) { toast('Pick a user first'); return; }
  const zone = $('#upload-zone');
  zone.textContent = `Uploading ${file.name}…`;
  try {
    const book = await api.uploadBook(file, (p) => {
      // "100%" is a transfer fact, not an outcome: an EPUB then spends
      // several seconds being parsed server-side. Say so, or the zone looks
      // stuck and a first-time user reaches for + again.
      zone.textContent = p >= 1
        ? `Importing ${file.name}…`
        : `Uploading ${file.name}… ${Math.round(p * 100)}%`;
    });
    zone.hidden = true;
    await onUploaded(book);
    toast(`Added “${book.title}”`);
    // Point at the result: the new card is below the fold on a phone.
    document.querySelector(`[data-book-id="${book.id}"]`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  } catch (e) {
    zone.textContent = `Upload failed: ${e.message}`;
    toast(e.message);
  }
}
