// Smoke tests for the HTML5-audio engine.
//
// We can't run real HTMLMediaElement under `node --test` (no DOM), so we
// stub document.createElement('audio') with a fake that supports the
// engine's API surface: src, currentTime, duration, playbackRate, play,
// pause, addEventListener('ended'/'canplay'), readyState.
//
// These tests verify the engine's CONTROL behaviour (play/pause/seek/skip,
// paragraph chain advance, rate change). They don't verify real audio
// playback — that's covered by the Playwright immersive-smoke.mjs harness.

import { test } from 'node:test';
import assert from 'node:assert/strict';

// ─── DOM stub: enough of document/body for the engine to create elements ─

class FakeAudioEl {
  constructor() {
    this.src = '';
    this.currentTime = 0;
    this.duration = 5;          // pretend each paragraph is 5s
    this.playbackRate = 1;
    this.preload = 'auto';
    this.readyState = 4;        // HAVE_ENOUGH_DATA — no canplay-await needed
    this.paused = true;
    this._listeners = {};
    this.style = {};
    this.attrs = {};
  }
  addEventListener(name, fn, _opts) {
    (this._listeners[name] ||= []).push(fn);
  }
  removeEventListener(name, fn) {
    const arr = this._listeners[name];
    if (arr) this._listeners[name] = arr.filter((f) => f !== fn);
  }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  load() { /* no-op */ }
  remove() { /* no-op */ }
  async play() { this.paused = false; }
  pause() { this.paused = true; }
  _emit(name) {
    for (const fn of (this._listeners[name] || [])) fn();
  }
}

function installDomStub() {
  const createdAudios = [];
  globalThis.document = {
    createElement(tag) {
      if (tag === 'audio') {
        const el = new FakeAudioEl();
        createdAudios.push(el);
        return el;
      }
      throw new Error(`unexpected createElement('${tag}')`);
    },
    body: { appendChild() {} },
  };
  globalThis.location = { href: 'http://test.example/' };
  globalThis.URL = class { constructor(u) { this.href = u; } toString() { return this.href; } };
  return createdAudios;
}

function makeRing(paraDurations) {
  // Each slot resolves immediately with a fake audioUrl + duration.
  return {
    advance() {},
    async await(idx) {
      if (idx < 0 || idx >= paraDurations.length) throw new Error('out of range');
      return {
        words: [{ text: 'w', start_ms: 0, end_ms: paraDurations[idx] * 1000 }],
        audioUrl: `/api/tts/cache/p${idx}/audio.mp3`,
        duration: paraDurations[idx],
      };
    },
    getResolved() { return null; },
  };
}

// Settle microtasks so any awaits inside the engine resolve.
async function flush(rounds = 30) {
  for (let i = 0; i < rounds; i++) await Promise.resolve();
}

// ─── Tests ──────────────────────────────────────────────────────────────

test('engine starts paused at paragraph 0', async () => {
  installDomStub();
  const { createAudioEngine } = await import('../../web/js/reader/audio-engine.js?case=1');
  const engine = createAudioEngine({
    prefetchRing: makeRing([4, 4, 4]),
    getTotalParas: () => 3,
    getDurations: () => [4, 4, 4],
  });
  assert.equal(engine.isPaused(), true);
  assert.equal(engine.currentParagraphIdx(), 0);
  assert.equal(engine.currentTime(), 0);
});

test('play() sets the active element source and starts playback', async () => {
  const audios = installDomStub();
  const { createAudioEngine } = await import('../../web/js/reader/audio-engine.js?case=2');
  const engine = createAudioEngine({
    prefetchRing: makeRing([4, 4]),
    getTotalParas: () => 2,
    getDurations: () => [4, 4],
  });
  engine.play();
  await flush();
  // Two elements created (alternating). Active should have its src set.
  assert.equal(audios.length, 2);
  assert.ok(audios[0].src.endsWith('/api/tts/cache/p0/audio.mp3'));
  assert.equal(audios[0].paused, false);
  assert.equal(engine.isPaused(), false);
});

test('paragraph advances when active element fires ended', async () => {
  const audios = installDomStub();
  const { createAudioEngine } = await import('../../web/js/reader/audio-engine.js?case=3');
  const para = [];
  const engine = createAudioEngine({
    prefetchRing: makeRing([4, 4, 4]),
    getTotalParas: () => 3,
    getDurations: () => [4, 4, 4],
  });
  engine.onParagraphChange = (idx) => para.push(idx);
  engine.play();
  await flush();
  // Fake the end of paragraph 0
  audios[0]._emit('ended');
  await flush();
  assert.deepEqual(para, [1]);
  assert.equal(engine.currentParagraphIdx(), 1);
  // The other element should now be the active one and have para 1 loaded
  assert.equal(audios[1].paused, false);
  assert.ok(audios[1].src.endsWith('/api/tts/cache/p1/audio.mp3'));
});

test('end of book triggers onPause, not onParagraphChange', async () => {
  const audios = installDomStub();
  const { createAudioEngine } = await import('../../web/js/reader/audio-engine.js?case=4');
  const events = [];
  const engine = createAudioEngine({
    prefetchRing: makeRing([4]),
    getTotalParas: () => 1,
    getDurations: () => [4],
  });
  engine.onPause = () => events.push('pause');
  engine.onParagraphChange = () => events.push('paraChange');
  engine.play();
  await flush();
  audios[0]._emit('ended');
  await flush();
  assert.deepEqual(events, ['pause']);
  assert.equal(engine.isPaused(), true);
});

test('pause() remembers current position; play() resumes from there', async () => {
  const audios = installDomStub();
  const { createAudioEngine } = await import('../../web/js/reader/audio-engine.js?case=5');
  const engine = createAudioEngine({
    prefetchRing: makeRing([4, 4]),
    getTotalParas: () => 2,
    getDurations: () => [4, 4],
  });
  engine.play();
  await flush();
  audios[0].currentTime = 1.7;
  engine.pause();
  assert.equal(engine.isPaused(), true);
  assert.equal(audios[0].paused, true);
  // currentTime() while paused returns the remembered offset
  assert.ok(Math.abs(engine.currentTime() - 1.7) < 0.001);
  // Resume
  engine.play();
  await flush();
  // The same paragraph should still be loaded and resumed near 1.7s
  assert.equal(audios[0].paused, false);
  assert.ok(Math.abs(audios[0].currentTime - 1.7) < 0.001);
});

test('setRate updates both elements live', async () => {
  const audios = installDomStub();
  const { createAudioEngine } = await import('../../web/js/reader/audio-engine.js?case=6');
  const engine = createAudioEngine({
    prefetchRing: makeRing([4, 4]),
    getTotalParas: () => 2,
    getDurations: () => [4, 4],
  });
  engine.play();
  await flush();
  engine.setRate(1.5);
  assert.equal(audios[0].playbackRate, 1.5);
  assert.equal(audios[1].playbackRate, 1.5);
  assert.equal(engine._rate(), 1.5);
});

test('seek(idx, sec) repositions and resumes when playing', async () => {
  const audios = installDomStub();
  const { createAudioEngine } = await import('../../web/js/reader/audio-engine.js?case=7');
  const engine = createAudioEngine({
    prefetchRing: makeRing([4, 4, 4]),
    getTotalParas: () => 3,
    getDurations: () => [4, 4, 4],
  });
  engine.play();
  await flush();
  engine.seek(2, 1.0);
  await flush();
  assert.equal(engine.currentParagraphIdx(), 2);
  assert.ok(Math.abs(audios[0].currentTime - 1.0) < 0.001 || Math.abs(audios[1].currentTime - 1.0) < 0.001);
});
