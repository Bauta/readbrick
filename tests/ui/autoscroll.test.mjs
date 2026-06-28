import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldAutoScroll } from '../../web/js/reader/autoscroll.js';

const VH = 800;  // viewport height
const NOW = 10_000;  // arbitrary "now" timestamp

test('returns false when word is inside comfort band', () => {
  const wordRect = { top: 400, bottom: 420 };  // mid-screen
  const result = shouldAutoScroll({
    wordRect, viewportHeight: VH,
    lastScrollAt: 0, lastInteractionAt: 0, now: NOW,
  });
  assert.equal(result, false);
});

test('returns true when word is above comfort band (top < 0.2 * VH)', () => {
  const wordRect = { top: 100, bottom: 120 };  // VH=800, threshold=160
  const result = shouldAutoScroll({
    wordRect, viewportHeight: VH,
    lastScrollAt: 0, lastInteractionAt: 0, now: NOW,
  });
  assert.equal(result, true);
});

test('returns true when word is below comfort band (bottom > 0.8 * VH)', () => {
  const wordRect = { top: 700, bottom: 720 };  // VH=800, threshold=640
  const result = shouldAutoScroll({
    wordRect, viewportHeight: VH,
    lastScrollAt: 0, lastInteractionAt: 0, now: NOW,
  });
  assert.equal(result, true);
});

test('returns false when auto-scrolled within last 400ms', () => {
  const wordRect = { top: 700, bottom: 720 };  // would otherwise trigger
  const result = shouldAutoScroll({
    wordRect, viewportHeight: VH,
    lastScrollAt: NOW - 200, lastInteractionAt: 0, now: NOW,
  });
  assert.equal(result, false);
});

test('returns false when user interacted within last 1500ms', () => {
  const wordRect = { top: 700, bottom: 720 };
  const result = shouldAutoScroll({
    wordRect, viewportHeight: VH,
    lastScrollAt: 0, lastInteractionAt: NOW - 1000, now: NOW,
  });
  assert.equal(result, false);
});

test('returns true after interaction suppression window expires', () => {
  const wordRect = { top: 700, bottom: 720 };
  const result = shouldAutoScroll({
    wordRect, viewportHeight: VH,
    lastScrollAt: 0, lastInteractionAt: NOW - 1600, now: NOW,
  });
  assert.equal(result, true);
});

test('returns false when wordRect is null (no active word)', () => {
  const result = shouldAutoScroll({
    wordRect: null, viewportHeight: VH,
    lastScrollAt: 0, lastInteractionAt: 0, now: NOW,
  });
  assert.equal(result, false);
});
