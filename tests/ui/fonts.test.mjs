import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveFont, addRecent, filterCatalog } from '../../web/js/reader/fonts.js';

const KEYS = ['sans', 'serif', 'slab', 'hyperlegible', 'dyslexic'];

test('resolveFont maps a bundled key to its CSS var', () => {
  const r = resolveFont('serif', KEYS);
  assert.equal(r.cssValue, 'var(--font-reader-serif)');
  assert.equal(r.isBundled, true);
});

test('resolveFont treats an unknown value as a Google family', () => {
  const r = resolveFont('EB Garamond', KEYS);
  assert.equal(r.isBundled, false);
  assert.equal(r.family, 'EB Garamond');
  assert.match(r.cssValue, /"EB Garamond"/);
  assert.match(r.cssValue, /var\(--font-reader-serif\)/); // fallback
});

test('resolveFont falls back to serif for empty input', () => {
  assert.equal(resolveFont('', KEYS).cssValue, 'var(--font-reader-serif)');
});

test('addRecent keeps most-recent-first, deduped and capped', () => {
  let r = [];
  r = addRecent(r, 'Lora');
  r = addRecent(r, 'Bitter');
  r = addRecent(r, 'Lora'); // moves to front, no dup
  assert.deepEqual(r, ['Lora', 'Bitter']);
  for (let i = 0; i < 10; i++) r = addRecent(r, `F${i}`, 3);
  assert.equal(r.length, 3);
  assert.equal(r[0], 'F9');
});

test('filterCatalog matches case-insensitively, prefix first', () => {
  const fams = [
    { family: 'Roboto', category: 'sans-serif' },
    { family: 'Roboto Slab', category: 'serif' },
    { family: 'Slabo 27px', category: 'serif' },
  ];
  const out = filterCatalog(fams, 'slab');
  assert.deepEqual(out.map((f) => f.family), ['Slabo 27px', 'Roboto Slab']);
  assert.equal(filterCatalog(fams, '').length, 3);
});

test('addRecent moving an existing family does not grow the list', () => {
  const r = addRecent(addRecent(['B', 'C'], 'A'), 'C');
  assert.deepEqual(r, ['C', 'A', 'B']);
});
