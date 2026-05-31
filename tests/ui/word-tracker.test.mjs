import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findCurrentWord } from '../../web/js/reader/word-tracker.js';

test('findCurrentWord returns -1 for empty words', () => {
  assert.equal(findCurrentWord([], 0), -1);
  assert.equal(findCurrentWord([], 500), -1);
});

test('clamps to first word when ms is before any word', () => {
  const words = [
    { text: 'a', start_ms: 100, end_ms: 200 },
    { text: 'b', start_ms: 200, end_ms: 300 },
  ];
  assert.equal(findCurrentWord(words, 0), 0);
  assert.equal(findCurrentWord(words, 50), 0);
});

test('returns the word whose start_ms <= ms with the largest start_ms', () => {
  const words = [
    { text: 'a', start_ms: 0,    end_ms: 100 },
    { text: 'b', start_ms: 100,  end_ms: 200 },
    { text: 'c', start_ms: 200,  end_ms: 300 },
  ];
  assert.equal(findCurrentWord(words, 0),   0);
  assert.equal(findCurrentWord(words, 50),  0);
  assert.equal(findCurrentWord(words, 100), 1);
  assert.equal(findCurrentWord(words, 150), 1);
  assert.equal(findCurrentWord(words, 199), 1);
  assert.equal(findCurrentWord(words, 200), 2);
});

test('stays on previous word during silent gap (end_ms < next.start_ms)', () => {
  const words = [
    { text: 'before',  start_ms: 0,    end_ms: 100 },
    { text: 'after',   start_ms: 500,  end_ms: 600 },
  ];
  // 200ms is in the silence between the two words — pill stays on 'before'
  // until 'after' actually begins.
  assert.equal(findCurrentWord(words, 200), 0);
  assert.equal(findCurrentWord(words, 499), 0);
  assert.equal(findCurrentWord(words, 500), 1);
});

// ───── Regression: overlap from comma/period trailing silence ─────
//
// Some engines report a word duration that includes trailing silence, so a
// word followed by punctuation has end_ms that overlaps the next word's
// audible start. Pre-fix the pill stuck to the first matching range; with
// "latest start wins" the overlap resolves correctly.

test('overlapping ranges: latest-started word wins ("wait, everyone" case)', () => {
  // A word followed by a comma can carry the pause in its duration:
  //   wait:     start=2000, end=3000  (1000ms because duration includes the
  //                                    trailing comma pause)
  //   everyone: start=2700, end=3100  (actual audible "everyone" range)
  const words = [
    { text: 'wait',     start_ms: 2000, end_ms: 3000 },
    { text: 'everyone', start_ms: 2700, end_ms: 3100 },
  ];
  // While the audio is still saying 'wait' (≤ 2699 ms), pill on wait.
  assert.equal(findCurrentWord(words, 2500), 0, 'still inside wait audible');
  assert.equal(findCurrentWord(words, 2699), 0);
  // The moment everyone.start_ms (2700) is reached, the pill must move —
  // even though wait.end_ms (3000) hasn't been crossed yet.
  assert.equal(findCurrentWord(words, 2700), 1, 'must jump to everyone at its start, not at wait.end');
  assert.equal(findCurrentWord(words, 2900), 1);
  assert.equal(findCurrentWord(words, 3050), 1);
});

test('overlapping ranges: handles "he not." case (period pause)', () => {
  // "he dared not. Instead" → trailing period pause inflates "not"'s
  // duration, but the same mechanic can also inflate "he"'s duration if
  // "not" is short. Pre-fix the pill hung on "he" through not's whole
  // audible time.
  const words = [
    { text: 'he',  start_ms: 1000, end_ms: 1800 },  // overlaps next
    { text: 'not', start_ms: 1500, end_ms: 2400 },
    { text: 'So',  start_ms: 2400, end_ms: 2500 },
  ];
  assert.equal(findCurrentWord(words, 1100), 0);  // mid-he
  assert.equal(findCurrentWord(words, 1499), 0);  // last ms still on he
  assert.equal(findCurrentWord(words, 1500), 1);  // not begins → jump
  assert.equal(findCurrentWord(words, 2100), 1);
  assert.equal(findCurrentWord(words, 2400), 2);
});

test('past the last word: pill stays on last word', () => {
  const words = [
    { text: 'a', start_ms: 0,   end_ms: 100 },
    { text: 'b', start_ms: 100, end_ms: 200 },
  ];
  assert.equal(findCurrentWord(words, 250), 1);
  assert.equal(findCurrentWord(words, 999999), 1);
});

test('single-word paragraph', () => {
  const words = [{ text: 'lone', start_ms: 50, end_ms: 200 }];
  assert.equal(findCurrentWord(words, 0), 0);
  assert.equal(findCurrentWord(words, 100), 0);
  assert.equal(findCurrentWord(words, 9999), 0);
});
