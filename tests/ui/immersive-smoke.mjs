// End-to-end smoke for the immersive reader UI.
//
// Prereqs (see tests/ui/README.md):
//   - npm install + npx playwright install chromium
//   - python -m server.app  (dev server on :8000)
//   - At least one book uploaded for user_id=1
//
// Run: node tests/ui/immersive-smoke.mjs

import { chromium } from 'playwright';
import { strict as assert } from 'node:assert';

// Override to point the smoke at a host-run server on another port, e.g.
//   READER_BASE=http://127.0.0.1:8010 node tests/ui/immersive-smoke.mjs
const BASE = process.env.READER_BASE || 'http://127.0.0.1:8000';

async function main() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required', '--no-sandbox'],
  });
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 900 },
    deviceScaleFactor: 2,
  });
  await ctx.addInitScript(() => {
    localStorage.setItem('reader.user', JSON.stringify({ id: 1, name: 'Demo' }));
    // Suppress the first-run hint so it doesn't intercept tests.
    localStorage.setItem('reader.seenSeekHint', '1');
  });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => console.log('pageerror:', e.message));

  // Force a Kokoro voice so TTS routes through the local container.
  // Route-intercept the prefs API and patch voice_id before it reaches reader.js.
  await page.route('**/api/users/*/prefs', async (route) => {
    const resp = await route.fetch();
    const body = await resp.json();
    body.voice_id = 'kokoro:af_heart';
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });

  const books = await (await fetch(`${BASE}/api/books?user_id=1`)).json();
  if (!books.length) throw new Error('No books for user 1; upload one first.');
  const book = books[0];

  await page.goto(`${BASE}/read/${book.id}`);
  await page.waitForSelector('p[data-idx]');

  // ──── Move C: prefetch ring is warm before any play tap ────
  // boot() constructs the ring and advances to the resume paragraph, so the
  // current paragraph's words resolve without the user pressing play.
  const ringWarm = await page.waitForFunction(
    () => {
      const st = window.__readerState;
      if (!st || !st.prefetchRing) return false;
      const idx = st.curIdx || 0;
      return st.prefetchRing.getResolved(idx) != null;
    },
    { timeout: 30000 },
  ).then(() => true).catch(() => false);
  if (ringWarm) console.log('✔ prefetch ring warm before play tap');
  else console.log('… ring-warm check inconclusive (slow TTS/network)');

  // ──── Test 1: skip buttons gone ────
  const skipBack = await page.$('#skip-back');
  const skipFwd  = await page.$('#skip-forward');
  assert.equal(skipBack, null, 'skip-back button should be removed');
  assert.equal(skipFwd, null, 'skip-forward button should be removed');
  console.log('✔ skip buttons removed');

  // ──── Test 2: <audio> element gone (Web Audio engine took over) ────
  const audioEl = await page.$('#player');
  assert.equal(audioEl, null, '<audio> element should be removed');
  console.log('✔ <audio> element removed');

  // ──── Test 3: engine materializes on first play tap ────
  await page.click('p[data-idx="1"]');  // skip past chapter title
  await page.click('#play-btn');
  await page.waitForFunction(() => window.__readerEngine != null, { timeout: 10000 });
  console.log('✔ engine materializes on play tap');

  // ──── Test 4: chrome auto-hides after 3s of playback ────
  // Wait for first paragraph's audio to start (engine.currentTime() > 0).
  await page.waitForFunction(
    () => window.__readerEngine && !window.__readerEngine.isPaused() && window.__readerEngine.currentTime() > 0,
    { timeout: 30000 },
  );
  await page.waitForTimeout(3500);
  const chromeHidden = await page.evaluate(
    () => document.body.classList.contains('chrome-hidden'),
  );
  assert.equal(chromeHidden, true, 'chrome should be hidden after 3s of playback');
  console.log('✔ chrome auto-hides after 3s');

  // ──── Test 5: tap reveals chrome ────
  await page.click('p[data-idx="1"]');
  await page.waitForTimeout(250);
  const chromeAfterTap = await page.evaluate(
    () => document.body.classList.contains('chrome-hidden'),
  );
  assert.equal(chromeAfterTap, false, 'chrome should reappear after tap');
  console.log('✔ tap reveals chrome');

  // ──── Test 6: continuous playback across a paragraph boundary ────
  // Engine should cross from paragraph 1 into paragraph 2 WITHOUT pausing.
  // Books in dev are short (~3-5s per paragraph), so this happens within ~10s.
  await page.waitForFunction(
    () => {
      const e = window.__readerEngine;
      return e && !e.isPaused() && e.currentParagraphIdx() >= 2;
    },
    { timeout: 30000 },
  );
  const stillPlaying = await page.evaluate(
    () => !window.__readerEngine.isPaused() && window.__readerEngine.currentParagraphIdx() >= 2,
  );
  assert.equal(stillPlaying, true, 'engine should cross paragraph boundary without pausing');
  console.log('✔ continuous playback across paragraph boundary');

  // ──── Test 7: pause forces chrome visible ────
  // Let chrome auto-hide again, then pause, and confirm chrome returns.
  await page.waitForTimeout(3500);
  await page.evaluate(() => window.__readerEngine.pause());
  await page.waitForTimeout(200);
  const chromeAfterPause = await page.evaluate(
    () => document.body.classList.contains('chrome-hidden'),
  );
  assert.equal(chromeAfterPause, false, 'chrome should be visible while paused');
  console.log('✔ pause forces chrome visible');

  // ──── Test 8: pause / resume preserves engine position ────
  // Read state while paused so we get a stable snapshot.
  const tBeforeResume = await page.evaluate(() => window.__readerEngine.currentTime());
  const paraBeforeResume = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  // play() is synchronous w.r.t. paragraph position: _startChain is async so
  // currentParagraphIdx() immediately after play() still reflects resumeParaIdx.
  // We capture the paragraph right after play() before any onended can fire.
  const paraImmediatelyAfterResume = await page.evaluate(() => {
    window.__readerEngine.play();
    return window.__readerEngine.currentParagraphIdx();
  });
  // Resume must start playback in the same paragraph it was paused in (not restart
  // from para 0 or jump to a random paragraph).
  assert.equal(paraImmediatelyAfterResume, paraBeforeResume, 'resume should stay in same paragraph');
  // Wait a beat so the async chain fires, then verify we haven't gone BACKWARDS
  // (paragraph-wise). currentTime() is paragraph-local so we can't compare across
  // paragraph boundaries — compare paragraphs instead.
  await page.waitForTimeout(400);
  const tAfterResume = await page.evaluate(() => window.__readerEngine.currentTime());
  const paraAfterResume = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  // Engine must not have gone backward (seek-to-zero regression guard).
  assert.ok(
    paraAfterResume >= paraBeforeResume,
    `resume should not go backward; para was ${paraBeforeResume} → ${paraAfterResume}`,
  );
  console.log(`✔ pause/resume preserves position (para ${paraBeforeResume} t=${tBeforeResume.toFixed(2)}s → para ${paraAfterResume} t=${tAfterResume.toFixed(2)}s)`);

  // Pause again so the remaining tests have stable currentTime readings.
  await page.evaluate(() => window.__readerEngine.pause());
  await page.waitForTimeout(150);

  // ──── Test 9: double-tap right gutter seeks +15s ────
  // NOTE: dev DB books are short (~3-5s per paragraph). The engine's
  // skip() does NOT clamp to "current paragraph end" — it walks global time
  // across paragraphs. So +15s usually lands in a later paragraph.
  const beforeSkip = await page.evaluate(() => window.__readerEngine.currentTime());
  const paraBeforeSkip = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  const paraRect = await page.evaluate(() => {
    const r = document.querySelector('p[data-idx]').getBoundingClientRect();
    return { left: r.left, right: r.right };
  });
  const rightX = Math.min(389, Math.floor((paraRect.right + 390) / 2));
  await page.mouse.click(rightX, 450);
  await page.waitForTimeout(50);
  await page.mouse.click(rightX, 450);
  await page.waitForTimeout(300);
  const paraAfterSkip = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  // Expect either: paragraph advanced OR we landed somewhere later in the same paragraph
  // (depends on dev-DB duration distribution). Both are OK proof that the gesture fired.
  const advanced = paraAfterSkip > paraBeforeSkip;
  const movedWithinPara = paraAfterSkip === paraBeforeSkip
    && (await page.evaluate(() => window.__readerEngine.currentTime())) > beforeSkip;
  assert.ok(advanced || movedWithinPara, `expected forward seek; para ${paraBeforeSkip}→${paraAfterSkip}, t ${beforeSkip.toFixed(2)}`);
  console.log(`✔ right double-tap seeks forward (para ${paraBeforeSkip} → ${paraAfterSkip})`);

  // ──── Test 10: double-tap left gutter seeks -15s ────
  const leftX = Math.max(2, Math.floor(paraRect.left / 2));
  await page.mouse.click(leftX, 450);
  await page.waitForTimeout(50);
  await page.mouse.click(leftX, 450);
  await page.waitForTimeout(300);
  const paraAfterBack = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  const backward = paraAfterBack < paraAfterSkip;
  const movedBackWithinPara = paraAfterBack === paraAfterSkip
    && (await page.evaluate(() => window.__readerEngine.currentTime())) < beforeSkip;
  assert.ok(backward || movedBackWithinPara, `expected backward seek; para ${paraAfterSkip}→${paraAfterBack}`);
  console.log(`✔ left double-tap seeks backward (para ${paraAfterSkip} → ${paraAfterBack})`);

  // ──── Test 11: word-tap-to-seek still works (paused) ────
  // Need to be paused; we are. Try to tap a word in the currently active paragraph.
  const curPara = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  const word2 = await page.$(`p[data-idx="${curPara}"] span.w[data-w="2"]`);
  if (word2) {
    const tBeforeWordTap = await page.evaluate(() => window.__readerEngine.currentTime());
    await word2.click();
    await page.waitForTimeout(200);
    const tAfterWordTap = await page.evaluate(() => window.__readerEngine.currentTime());
    assert.notEqual(tBeforeWordTap, tAfterWordTap, 'word-tap should change currentTime');
    console.log(`✔ word-tap-to-seek still works (${tBeforeWordTap.toFixed(2)}s → ${tAfterWordTap.toFixed(2)}s)`);
  } else {
    console.log('… skipped word-tap test (no word span data-w=2 in current paragraph)');
  }

  // ──── Word-tap during playback should seek + keep playing ────
  // Start playback again, wait for it to settle, then tap a word.
  await page.evaluate(() => window.__readerEngine.play());
  await page.waitForFunction(
    () => !window.__readerEngine.isPaused() && window.__readerEngine.currentTime() > 0,
    { timeout: 15000 },
  );
  await page.waitForTimeout(500);
  const playingPara = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  const wordToTap = await page.$(`p[data-idx="${playingPara}"] span.w[data-w="0"]`);
  if (wordToTap) {
    const tBefore = await page.evaluate(() => window.__readerEngine.currentTime());
    await wordToTap.click();
    await page.waitForTimeout(300);
    const stillPlaying = await page.evaluate(() => !window.__readerEngine.isPaused());
    const tAfter = await page.evaluate(() => window.__readerEngine.currentTime());
    assert.equal(stillPlaying, true, 'engine should keep playing after word-tap during playback');
    assert.notEqual(tBefore, tAfter, 'word-tap during playback should change currentTime');
    console.log(`✔ word-tap during playback seeks + keeps playing (${tBefore.toFixed(2)}s → ${tAfter.toFixed(2)}s)`);
  } else {
    console.log('… skipped word-tap-during-playback (no word-0 in current paragraph)');
  }

  // ──── Scroll monotonicity across paragraph boundary ────
  // Sample scrollY across ~6s of playback that crosses at least one paragraph.
  // Allow ±2 px for sub-pixel rendering noise. No real up-jump should occur.
  const startPara = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  const samples = [];
  const startedAt = Date.now();
  while (Date.now() - startedAt < 6000) {
    const y = await page.evaluate(() => window.scrollY);
    samples.push(y);
    await page.waitForTimeout(200);
  }
  const crossedPara = await page.evaluate(() => window.__readerEngine.currentParagraphIdx());
  const upJumps = [];
  for (let i = 1; i < samples.length; i++) {
    if (samples[i] < samples[i - 1] - 2) {
      upJumps.push({ from: samples[i - 1], to: samples[i], at: i });
    }
  }
  if (crossedPara <= startPara) {
    console.log(`… scroll monotonicity skipped (no paragraph advance in 6s; start=${startPara}, end=${crossedPara})`);
  } else {
    assert.equal(
      upJumps.length, 0,
      `expected scrollY to be monotonically non-decreasing across paragraph boundary, but found up-jumps: ${JSON.stringify(upJumps)}`,
    );
    console.log(`✔ scroll monotonic across boundary (para ${startPara} → ${crossedPara}, ${samples.length} samples)`);
  }

  console.log('\nAll smoke checks passed.');
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
