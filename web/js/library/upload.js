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
      zone.textContent = `Uploading ${file.name}… ${Math.round(p * 100)}%`;
    });
    zone.textContent = `Imported: ${book.title}`;
    setTimeout(() => { zone.hidden = true; }, 1500);
    await onUploaded(book);
  } catch (e) {
    zone.textContent = `Upload failed: ${e.message}`;
    toast(e.message);
  }
}
