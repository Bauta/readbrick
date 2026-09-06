import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  MPRIS_IDENTITY,
  buildMetadata,
  cumulativeWords,
  totalWords,
  estimateDuration,
  estimatePosition,
  paragraphAtPosition,
} from '../../web/js/reader/media-session.js';

// ───── buildMetadata ─────
//
// The album slot is the only stable identifier a desktop widget can key on:
// the browser reports Identity as "Chromium" and omits DesktopEntry entirely.
// So album carries the app name, never the book's.

test('buildMetadata puts the app identity in album, not the book', () => {
  const m = buildMetadata({ title: 'Appetites', author: 'Anthony Bourdain' });
  assert.equal(m.album, MPRIS_IDENTITY);
  assert.equal(m.title, 'Appetites');
  assert.equal(m.artist, 'Anthony Bourdain');
});

test('buildMetadata survives a book with no author', () => {
  const m = buildMetadata({ title: 'Untitled' });
  assert.equal(m.artist, '');
  assert.equal(m.album, MPRIS_IDENTITY);
});

test('buildMetadata still identifies itself with no book at all', () => {
  const m = buildMetadata(null);
  assert.equal(m.album, MPRIS_IDENTITY);
  assert.equal(typeof m.title, 'string');
});

test('buildMetadata includes cover artwork when a url is given', () => {
  const m = buildMetadata({ title: 'A' }, '/api/books/x/cover');
  assert.equal(m.artwork.length, 1);
  assert.equal(m.artwork[0].src, '/api/books/x/cover');
});

test('buildMetadata omits artwork when no url is given', () => {
  assert.deepEqual(buildMetadata({ title: 'A' }).artwork, []);
});

// ───── cumulativeWords ─────

test('cumulativeWords accumulates word counts per paragraph', () => {
  const paras = [{ text: 'one two' }, { text: 'three' }, { text: 'four five six' }];
  assert.deepEqual(cumulativeWords(paras), [0, 2, 3]);
});

test('cumulativeWords tolerates empty and missing text', () => {
  assert.deepEqual(cumulativeWords([{ text: '' }, {}, { text: 'a' }]), [0, 0, 0]);
});

test('cumulativeWords on an empty book is empty', () => {
  assert.deepEqual(cumulativeWords([]), []);
});

test('totalWords counts the whole book, including the last paragraph', () => {
  const paras = [{ text: 'one two' }, { text: 'three' }, { text: 'four five six' }];
  assert.equal(totalWords(paras), 6);
  // The last paragraph is exactly what a naive read of cumulativeWords misses.
  assert.equal(totalWords(paras), cumulativeWords(paras).at(-1) + 3);
});

test('totalWords is 0 for an empty book', () => {
  assert.equal(totalWords([]), 0);
});

// ───── estimateDuration ─────
//
// Book-level, never per-paragraph. The two alternating <audio> elements each
// report their own clip length; reporting that to MPRIS is what made the
// player useless before this module existed.

test('estimateDuration prefers the server est_minutes', () => {
  assert.equal(estimateDuration({ est_minutes: 120, word_count: 1 }, 1), 7200);
});

test('estimateDuration falls back to word count at the narration baseline', () => {
  // 150 wpm → 300 words is 2 minutes
  assert.equal(estimateDuration({ word_count: 300 }, 1), 120);
});

test('estimateDuration shortens as playback rate rises', () => {
  assert.equal(estimateDuration({ est_minutes: 60 }, 2), 1800);
});

test('estimateDuration returns 0 when the book size is unknown', () => {
  assert.equal(estimateDuration({}, 1), 0);
  assert.equal(estimateDuration(null, 1), 0);
});

test('estimateDuration ignores a nonsense rate rather than dividing by zero', () => {
  assert.equal(estimateDuration({ est_minutes: 60 }, 0), 3600);
});

// ───── estimatePosition ─────

test('estimatePosition scales by words consumed, not paragraph index', () => {
  // Paragraph 1 starts after 2 of 6 words → one third through a 300s book.
  const cum = [0, 2, 3];
  assert.equal(estimatePosition(cum, 6, 300, 1), 100);
});

test('estimatePosition is 0 at the start of the book', () => {
  assert.equal(estimatePosition([0, 2, 3], 6, 300, 0), 0);
});

test('estimatePosition never exceeds the duration', () => {
  const pos = estimatePosition([0, 2, 3], 6, 300, 99);
  assert.ok(pos <= 300, `expected <= 300, got ${pos}`);
});

test('estimatePosition is 0 when the book size is unknown', () => {
  assert.equal(estimatePosition([], 0, 0, 0), 0);
});

// ───── paragraphAtPosition ─────
//
// The inverse of estimatePosition, so an external MPRIS SetPosition lands on a
// paragraph. Paragraph granularity is the honest limit: the engine seeks to
// paragraph starts, not arbitrary offsets into the book.

test('paragraphAtPosition inverts estimatePosition', () => {
  const cum = [0, 2, 3];
  assert.equal(paragraphAtPosition(cum, 6, 300, 100), 1);
});

test('paragraphAtPosition clamps below the start and past the end', () => {
  const cum = [0, 2, 3];
  assert.equal(paragraphAtPosition(cum, 6, 300, -50), 0);
  assert.equal(paragraphAtPosition(cum, 6, 300, 99999), 2);
});

test('paragraphAtPosition returns the containing paragraph, not the next one', () => {
  const cum = [0, 2, 3];
  // 60s is inside paragraph 0 (which spans 0-100s), not paragraph 1.
  assert.equal(paragraphAtPosition(cum, 6, 300, 60), 0);
});

test('paragraphAtPosition is 0 when the book size is unknown', () => {
  assert.equal(paragraphAtPosition([], 0, 0, 42), 0);
});
