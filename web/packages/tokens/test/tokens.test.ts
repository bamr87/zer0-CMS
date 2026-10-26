// @vitest-environment node
// The tokens and the theme agree: every token the theme reads is declared in
// tokens.css, colours carry both a light and a dark value, and the values are
// the zer0 kit's, so a typo cannot quietly turn a colour into nothing.
import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { roles, theme } from '../src';

const css = readFileSync(new URL('../src/tokens.css', import.meta.url), 'utf8');
const declared = new Map([...css.matchAll(/(--zer0-[\w-]+):\s*([^;]+);/g)].map((m) => [m[1] ?? '', m[2] ?? '']));
const used = (text: string) => [...text.matchAll(/var\((--zer0-[\w-]+)\)/g)].map((m) => m[1] ?? '');

describe('@zer0/tokens', () => {
  it('declares every token the Mantine theme reads', () => {
    const read = [...Object.values(roles), JSON.stringify(theme)].flatMap(used);
    expect(read.length).toBeGreaterThan(10);
    for (const token of read) expect(declared.has(token), token).toBe(true);
  });

  it('gives each surface and text colour a light and a dark value from the zer0 kit', () => {
    expect(declared.get('--zer0-bg')).toBe('light-dark(#f6f8fa, #0d1117)');
    expect(declared.get('--zer0-text')).toBe('light-dark(#1c2128, #e6edf3)');
    expect(declared.get('--zer0-accent')).toBe('light-dark(#0969da, #58a6ff)');
    expect(declared.get('--zer0-accent-strong')).toBe('light-dark(#0969da, #1f6feb)');
    for (const name of ['--zer0-bg-raised', '--zer0-bg-inset', '--zer0-border', '--zer0-text-dim']) {
      expect(declared.get(name)).toMatch(/^light-dark\(#[0-9a-f]{6}, #[0-9a-f]{6}\)$/);
    }
  });
});
