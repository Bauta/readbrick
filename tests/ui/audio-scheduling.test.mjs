import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  globalTimeToParagraph,
  ringSlotsFor,
} from '../../web/js/reader/audio-scheduling.js';

test('globalTimeToParagraph returns 0 with zero offset when global < first duration', () => {
  const r = globalTimeToParagraph([10, 8, 6], 3);
  assert.deepEqual(r, { paraIdx: 0, localOffset: 3 });
});

test('globalTimeToParagraph crosses into next paragraph at the boundary', () => {
  const r = globalTimeToParagraph([10, 8, 6], 12);
  assert.deepEqual(r, { paraIdx: 1, localOffset: 2 });
});

test('globalTimeToParagraph clamps to last paragraph end when global exceeds total', () => {
  const r = globalTimeToParagraph([10, 8, 6], 9999);
  assert.deepEqual(r, { paraIdx: 2, localOffset: 6 });
});

test('globalTimeToParagraph handles exactly-at-boundary as start of next', () => {
  const r = globalTimeToParagraph([10, 8, 6], 10);
  assert.deepEqual(r, { paraIdx: 1, localOffset: 0 });
});

test('ringSlotsFor returns ringSize paragraphs starting at current', () => {
  assert.deepEqual(ringSlotsFor(0, 100, 5), [0, 1, 2, 3, 4]);
  assert.deepEqual(ringSlotsFor(3, 100, 5), [3, 4, 5, 6, 7]);
});

test('ringSlotsFor clamps to totalParas at the tail', () => {
  assert.deepEqual(ringSlotsFor(8, 10, 5), [8, 9]);
  assert.deepEqual(ringSlotsFor(9, 10, 5), [9]);
});

test('ringSlotsFor returns empty when currentParaIdx out of range', () => {
  assert.deepEqual(ringSlotsFor(10, 10, 5), []);
  assert.deepEqual(ringSlotsFor(-1, 10, 5), []);
});
