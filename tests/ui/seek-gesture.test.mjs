import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  computeGutterZones,
  classifyTap,
} from '../../web/js/reader/seek-gesture.js';

// computeGutterZones —————————————————————————

test('gutter zones cover everything outside the paragraph column', () => {
  const paragraphRect = { left: 100, right: 700 };
  const viewport = { width: 800 };
  const zones = computeGutterZones(paragraphRect, viewport);
  assert.deepEqual(zones.left, { x0: 0, x1: 100 });
  assert.deepEqual(zones.right, { x0: 700, x1: 800 });
});

test('gutter zones collapse to zero when paragraph fills viewport', () => {
  const paragraphRect = { left: 0, right: 800 };
  const viewport = { width: 800 };
  const zones = computeGutterZones(paragraphRect, viewport);
  assert.deepEqual(zones.left, { x0: 0, x1: 0 });
  assert.deepEqual(zones.right, { x0: 800, x1: 800 });
});

// classifyTap —————————————————————————

const ZONES = { left: { x0: 0, x1: 80 }, right: { x0: 320, x1: 400 } };
const OPTS = { zones: ZONES, doubleTapWindowMs: 400 };

test('classifyTap returns "ignored" when tap is outside both gutter zones', () => {
  const result = classifyTap(null, { x: 200, t: 1000 }, OPTS);
  assert.equal(result, 'ignored');
});

test('classifyTap returns "first" on the first tap in a gutter', () => {
  const result = classifyTap(null, { x: 40, t: 1000 }, OPTS);
  assert.equal(result, 'first');
});

test('classifyTap returns "double-left" on second left-gutter tap within window', () => {
  const prev = { x: 40, t: 1000, side: 'left' };
  const result = classifyTap(prev, { x: 50, t: 1200 }, OPTS);
  assert.equal(result, 'double-left');
});

test('classifyTap returns "double-right" on second right-gutter tap within window', () => {
  const prev = { x: 350, t: 1000, side: 'right' };
  const result = classifyTap(prev, { x: 360, t: 1300 }, OPTS);
  assert.equal(result, 'double-right');
});

test('classifyTap returns "first" when second tap is on opposite side', () => {
  const prev = { x: 40, t: 1000, side: 'left' };
  const result = classifyTap(prev, { x: 360, t: 1100 }, OPTS);
  assert.equal(result, 'first');
});

test('classifyTap returns "first" when second tap is outside the window', () => {
  const prev = { x: 40, t: 1000, side: 'left' };
  const result = classifyTap(prev, { x: 50, t: 1500 }, OPTS);
  assert.equal(result, 'first');
});

test('classifyTap returns "ignored" when current tap is outside gutters', () => {
  const prev = { x: 40, t: 1000, side: 'left' };
  const result = classifyTap(prev, { x: 200, t: 1100 }, OPTS);
  assert.equal(result, 'ignored');
});
