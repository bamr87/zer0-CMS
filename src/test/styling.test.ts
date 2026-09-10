/**
 * The styling gate — two claims the documentation has always made and CI has
 * never run.
 *
 * 1. **Only `media/tokens.css` may name a VS Code theme variable.** `media/
 *    README.md` says "CI greps for violations"; until this file existed, it did
 *    not. The indirection is the whole reason a vanilla rewrite is maintainable
 *    where the Tailwind original was not — the fork had roughly four hundred
 *    inline `bg-[var(--vscode-…)]` arbitrary values, so retheming one control
 *    meant finding every site that had hard-coded the same theme key. One
 *    `--vscode-*` outside the token layer and that property starts growing back.
 *
 * 2. **`el()` has no `style` prop.** Every shell serves `default-src 'none'`
 *    with `style-src <cspSource> 'nonce-…'`, and a nonce cannot apply to an
 *    attribute — so an inline style is dropped by the browser with no console
 *    error. `ElProps.style` carried eleven call sites that had all been doing
 *    nothing since the day they were written. Five new tabs are about to be
 *    written against this library; the idiom must not be available to them.
 *
 * Both are greps over the repository's own source, so they run in the fast
 * plain-Mocha loop with no DOM, no build and no network.
 */

import { strict as assert } from 'node:assert';
import * as fs from 'node:fs';
import * as path from 'node:path';

const ROOT = path.resolve(__dirname, '..', '..');
const MEDIA = path.join(ROOT, 'media');
const SRC = path.join(ROOT, 'src');

/** The one file allowed to know VS Code's variable names. */
const TOKEN_LAYER = 'media/tokens.css';

function walk(dir: string, extensions: readonly string[], out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walk(abs, extensions, out);
    } else if (extensions.includes(path.extname(entry.name))) {
      out.push(abs);
    }
  }
  return out;
}

function rel(abs: string): string {
  return path.relative(ROOT, abs).split(path.sep).join('/');
}

interface Hit {
  file: string;
  line: number;
  text: string;
}

function grep(files: readonly string[], pattern: RegExp): Hit[] {
  const hits: Hit[] = [];
  for (const file of files) {
    const lines = fs.readFileSync(file, 'utf8').split('\n');
    lines.forEach((text, index) => {
      if (pattern.test(text)) {
        hits.push({ file: rel(file), line: index + 1, text: text.trim() });
      }
    });
  }
  return hits;
}

function describe(hits: readonly Hit[]): string {
  return hits.map((hit) => `${hit.file}:${hit.line}  ${hit.text}`).join('\n');
}

suite('styling gate', () => {
  test('`--vscode-` appears only in media/tokens.css', () => {
    // The shipped surface: every stylesheet, and every TypeScript module that
    // could name a colour — the three webview bundles and the two host files
    // that template a `<style>` block. `src/test/` is excluded because this
    // very file has to be able to write the string it is banning.
    const files = [
      ...walk(MEDIA, ['.css']),
      ...walk(SRC, ['.ts']).filter((file) => !rel(file).startsWith('src/test/')),
    ].filter((file) => rel(file) !== TOKEN_LAYER);
    const hits = grep(files, /--vscode-/);
    // The positive half of the same rule, so a token layer that stopped
    // resolving theme variables would fail here rather than pass silently.
    const tokens = fs.readFileSync(path.join(ROOT, TOKEN_LAYER), 'utf8');
    assert.ok(tokens.includes('--vscode-'), `${TOKEN_LAYER} resolves no theme variable`);
    assert.equal(
      hits.length,
      0,
      `A VS Code theme variable is named outside ${TOKEN_LAYER}. Add a --z-* token there\n` +
        `and alias it, rather than reaching for the theme key at the call site:\n${describe(hits)}`,
    );
  });

  test('el() has no `style` prop, and no webview module passes one', () => {
    const dom = fs.readFileSync(path.join(SRC, 'webview', 'shared', 'dom.ts'), 'utf8');
    const props = /export type ElProps<[\s\S]*?\n};/.exec(dom);
    assert.ok(props !== null, 'ElProps is no longer declared the way this test reads it');
    assert.ok(
      !/^\s*style\?:/m.test(props[0]),
      'ElProps declares a `style` prop again. The strict CSP drops an inline style\n' +
        'attribute silently — put a class on the node and a rule in media/ instead.',
    );
    assert.ok(
      !/key === 'style'/.test(dom),
      "el() handles a 'style' key again — see the comment at the top of dom.ts",
    );

    const hits = grep(walk(path.join(SRC, 'webview'), ['.ts']), /(\{|,)\s*style:\s*['"`]/);
    assert.equal(
      hits.length,
      0,
      `An inline style is being passed to el(). It will be dropped by the CSP:\n${describe(hits)}`,
    );
  });

  test('the classes the CSP-dead styles became are all styled', () => {
    const base = fs.readFileSync(path.join(MEDIA, 'base.css'), 'utf8');
    for (const name of [
      'z-hidden',
      'z-center',
      'z-dim',
      'z-anchor',
      'z-row',
      'z-row--tight',
      'z-row--wide',
      'z-inset',
      'z-label__text',
      'z-label__suffix',
    ]) {
      assert.ok(base.includes(`.${name} {`), `media/base.css has no rule for .${name}`);
    }
  });

  test('base.css carries the agent transcript and diff rules', () => {
    // A concurrent work package drops the ~40-rule <style> block out of
    // `src/agent/agentPanel.ts` and relies on these being here. If they are
    // not, the agent panel renders as unstyled text and the build stays green.
    const base = fs.readFileSync(path.join(MEDIA, 'base.css'), 'utf8');
    for (const selector of [
      '#z-agent',
      '.z-agent__bar',
      '.z-agent__log',
      '.z-agent__line',
      '.z-agent__text',
      '.z-agent__card',
      '.z-agent__diff',
      '.z-agent__diff .is-add',
      '.z-agent__diff .is-del',
      '.z-agent__diff .is-meta',
      '.z-agent__composer',
    ]) {
      assert.ok(base.includes(`${selector} {`), `media/base.css has no rule for ${selector}`);
    }
  });
});
