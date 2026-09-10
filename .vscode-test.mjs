import { defineConfig } from '@vscode/test-cli';

/**
 * Two extension-host runs, because two of the questions this repository asks
 * need two different windows.
 *
 * The first is the one that has always existed: every integration suite against
 * the single-folder fixture workspace. The second opens
 * `src/test/fixtures/multi.code-workspace` — two folders, a Jekyll site and an
 * MkDocs one — and runs only `multiroot.test.js`, because "twelve folders are
 * open and eleven of them are invisible" is not a thing a one-folder window can
 * be asked about.
 *
 * The first entry's glob still matches `multiroot.test.js`; `files` is a plain
 * glob list with no exclusion, and inventing one would be a config trick that
 * the next person has to decode. Instead the suite declares its own
 * precondition: opened in a window with fewer than two folders it skips itself
 * and logs why. A test that knows which window it belongs in is easier to trust
 * than a glob that knows it for the test.
 */
export default defineConfig([
  {
    label: 'workspace',
    files: 'out/test/**/*.test.js',
    version: '1.101.0',
    workspaceFolder: './src/test/fixtures/workspace',
    mocha: {
      ui: 'tdd',
      timeout: 30000,
    },
  },
  {
    label: 'multiroot',
    files: 'out/test/multiroot.test.js',
    version: '1.101.0',
    workspaceFolder: './src/test/fixtures/multi.code-workspace',
    mocha: {
      ui: 'tdd',
      timeout: 30000,
    },
  },
]);
