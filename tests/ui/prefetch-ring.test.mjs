import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPrefetchRing } from '../../web/js/reader/prefetch-ring.js';

function makeMockFetch() {
  const calls = [];
  const resolvers = new Map();
  const fetchAndDecode = (paraIdx) => {
    calls.push(paraIdx);
    return new Promise((resolve) => {
      resolvers.set(paraIdx, resolve);
    });
  };
  const resolve = (paraIdx, payload = { words: [], audioBuffer: { duration: 4 }, duration: 4 }) => {
    const r = resolvers.get(paraIdx);
    if (r) { r(payload); resolvers.delete(paraIdx); }
  };
  return { fetchAndDecode, calls, resolve };
}

test('advance(0) requests slots [0..4]', () => {
  const { fetchAndDecode, calls } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 100, fetchAndDecode });
  ring.advance(0);
  assert.deepEqual(calls.sort((a, b) => a - b), [0, 1, 2, 3, 4]);
});

test('advance(2) drops 0,1 and adds 5,6,7', () => {
  const { fetchAndDecode, calls } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 100, fetchAndDecode });
  ring.advance(0);
  calls.length = 0;  // reset
  ring.advance(2);
  assert.deepEqual(calls.sort((a, b) => a - b), [5, 6]);
  assert.equal(ring.get(0), undefined, 'slot 0 should be dropped');
  assert.equal(ring.get(1), undefined, 'slot 1 should be dropped');
  assert.notEqual(ring.get(2), undefined, 'slot 2 should still be in the ring');
});

test('advance is idempotent — same currentParaIdx does not re-request', () => {
  const { fetchAndDecode, calls } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 100, fetchAndDecode });
  ring.advance(0);
  ring.advance(0);
  ring.advance(0);
  assert.equal(calls.length, 5);
});

test('await(paraIdx) resolves once that slot is decoded', async () => {
  const { fetchAndDecode, resolve } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 100, fetchAndDecode });
  ring.advance(0);
  let resolved = false;
  const p = ring.await(2).then((slot) => { resolved = true; return slot; });
  // Not yet resolved.
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(resolved, false);
  // Resolve mock decode.
  resolve(2, { words: [{ text: 'x' }], audioBuffer: { duration: 7 }, duration: 7 });
  const slot = await p;
  assert.equal(resolved, true);
  assert.equal(slot.duration, 7);
  assert.equal(slot.audioBuffer.duration, 7);
});

test('await(paraIdx) rejects for an out-of-range paragraph', async () => {
  const { fetchAndDecode } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 100, fetchAndDecode });
  ring.advance(0);
  await assert.rejects(() => ring.await(99));
});

test('ring clamps to totalParas at the tail', () => {
  const { fetchAndDecode, calls } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 10, fetchAndDecode });
  ring.advance(8);
  assert.deepEqual(calls.sort((a, b) => a - b), [8, 9]);
});

test('getResolved returns null until the slot decodes', async () => {
  const { fetchAndDecode, resolve } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 100, fetchAndDecode });
  ring.advance(0);
  assert.equal(ring.getResolved(2), null);
  resolve(2, { words: [{ text: 'x' }], audioBuffer: { duration: 4 }, duration: 4 });
  // Microtask flush so the .then handler that fills `resolved` runs.
  await Promise.resolve(); await Promise.resolve();
  const slot = ring.getResolved(2);
  assert.notEqual(slot, null);
  assert.equal(slot.duration, 4);
});

test('getResolved returns null for evicted slots', async () => {
  const { fetchAndDecode, resolve } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 100, fetchAndDecode });
  ring.advance(0);
  resolve(0); resolve(1); resolve(2);
  await Promise.resolve(); await Promise.resolve();
  assert.notEqual(ring.getResolved(0), null);
  ring.advance(3);  // drops 0,1,2
  assert.equal(ring.getResolved(0), null);
});

test('reset clears all slots and resolved entries; next advance refetches', async () => {
  const { fetchAndDecode, resolve, calls } = makeMockFetch();
  const ring = createPrefetchRing({ size: 5, totalParas: 100, fetchAndDecode });
  ring.advance(0);
  resolve(0); resolve(1);
  await Promise.resolve(); await Promise.resolve();
  assert.notEqual(ring.getResolved(0), null);
  ring.reset();
  assert.equal(ring.get(0), undefined);
  assert.equal(ring.getResolved(0), null);
  // After reset, advance() to the same head triggers fresh fetches.
  calls.length = 0;
  ring.advance(0);
  assert.deepEqual(calls.sort((a, b) => a - b), [0, 1, 2, 3, 4]);
});
