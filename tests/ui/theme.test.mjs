import { test } from 'node:test';
import assert from 'node:assert/strict';
import { THEMES, resolveTheme } from '../../web/js/theme.js';

// "Auto" means "match what I'm looking at". Where the desktop says which side
// it is on, that beats the browser's colour-scheme preference: a freshly made
// browser profile has no such preference, which is how a dark desktop produced
// a white reader.

test('auto wears the full desktop palette when the desktop offers one', () => {
  // On an Omarchy desktop this is the default look — nobody has to find it.
  assert.equal(resolveTheme('auto', { available: true, mode: 'dark' }), 'omarchy');
  assert.equal(resolveTheme('auto', { available: true, mode: 'light' }), 'omarchy');
});

test('auto follows the desktop side when only a mode is known', () => {
  assert.equal(resolveTheme('auto', { available: false, mode: 'dark' }), 'dark');
  assert.equal(resolveTheme('auto', { available: false, mode: 'light' }), 'light');
});

test('auto stays auto when the desktop says nothing', () => {
  // Leaves the CSS prefers-color-scheme rule in charge.
  assert.equal(resolveTheme('auto', null), 'auto');
  assert.equal(resolveTheme('auto', undefined), 'auto');
  assert.equal(resolveTheme('auto', { available: false, mode: 'purple' }), 'auto');
});

test('an explicit choice is never overridden by the desktop', () => {
  const desktop = { available: true, mode: 'dark' };
  assert.equal(resolveTheme('sepia', desktop), 'sepia');
  assert.equal(resolveTheme('light', desktop), 'light');
  assert.equal(resolveTheme('dark', { available: true, mode: 'light' }), 'dark');
});

test('an explicit omarchy choice degrades gracefully where no palette exists', () => {
  // Phone, or a machine without Omarchy: behave like auto, never unstyled.
  assert.equal(resolveTheme('omarchy', { available: false, mode: 'dark' }), 'dark');
  assert.equal(resolveTheme('omarchy', null), 'auto');
});

test('an unknown stored preference falls back to auto rather than unstyling the page', () => {
  assert.equal(resolveTheme('neon', { available: false, mode: 'dark' }), 'dark');
  assert.equal(resolveTheme(undefined, null), 'auto');
});

test('the theme list is what the pickers render, in order', () => {
  assert.deepEqual(THEMES, ['light', 'sepia', 'dark', 'auto', 'omarchy']);
});
