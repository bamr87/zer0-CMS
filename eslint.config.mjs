// @ts-check
import tseslint from 'typescript-eslint';

/**
 * A note on how the gates below are arranged.
 *
 * `no-restricted-imports` takes ONE options object per file, and flat config
 * resolves that by last-writer-wins rather than by merging. So a second config
 * block matching the same file does not add a restriction — it silently replaces
 * the first. Every block below therefore carries the COMPLETE restriction list
 * for the files it matches, and the `files`/`ignores` are written so that no two
 * blocks overlap. Splitting a rule across two overlapping blocks is how a gate
 * disappears while the config still looks like it is there.
 */

/** The layering rule that has always held: pure Node means no editor API. */
const NO_VSCODE = {
  name: 'vscode',
  message:
    'src/core and src/mcp must stay pure Node. The vscode API is only available in ' +
    'src/extension.ts, src/config.ts, src/commands, src/views, src/panel, ' +
    'src/dashboard and src/agent.',
};

/**
 * The process gate (decision D13). Five vectors can start a process and every one
 * is behind Workspace Trust; keeping the actual `spawn` in two files is what makes
 * "five vectors" checkable by reading two files instead of grepping the tree.
 */
const NO_CHILD_PROCESS = [
  {
    name: 'node:child_process',
    message:
      'Process execution lives in core/contract/engine.ts and core/content/placeholders.ts, ' +
      'behind evaluateExecGate. Call runEngine / runVerifyCommand / resolvePlaceholders rather ' +
      'than spawning here — a sixth execution vector is a design decision, not an import.',
  },
  {
    name: 'child_process',
    message:
      'Process execution lives in core/contract/engine.ts and core/content/placeholders.ts, ' +
      'behind evaluateExecGate — and this repository writes node: builtins with their prefix.',
  },
];

/**
 * The bundle gate (decision D14). `dist/mcp-server.js` is built with an EMPTY
 * bare-import allow-list, and esbuild resolves the whole import graph before it
 * tree-shakes — so "the MCP server never calls it" is not a defence. These two
 * modules import `@bamr87/fleet-engines`, and neither is in the core barrel.
 */
const NO_ENGINES_FROM_MCP = {
  group: ['**/core/fleet/engines', '**/core/harness/selfAudit'],
  message:
    'This module imports @bamr87/fleet-engines, which dist/mcp-server.js may not bundle ' +
    '(that target allows no bare import at all). Take the engine result as a parameter, or ' +
    'convert at the boundary through core/fleet/adapters.ts, which is types-only.',
};

export default tseslint.config(
  {
    ignores: ['dist/**', 'out/**', 'node_modules/**', 'rails/**', 'tools/**', '.vscode-test/**'],
  },

  // 1 — baseline house rules
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.ts'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
    },
    rules: {
      curly: 'error',
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-throw-literal': 'error',
      'no-unused-expressions': 'error',
      // CLAUDE.md: don't suppress type errors or leave empty exception handlers.
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/ban-ts-comment': 'error',
      '@typescript-eslint/no-empty-function': 'error',
      'no-empty': ['error', { allowEmptyCatch: false }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
    },
  },

  // 2 — THE LAYERING GATE, for src/core. Pure Node, and no spawning outside the
  //     two files that own the execution vectors.
  {
    files: ['src/core/**/*.ts'],
    ignores: ['src/core/contract/engine.ts', 'src/core/content/placeholders.ts'],
    rules: {
      'no-restricted-imports': ['error', { paths: [NO_VSCODE, ...NO_CHILD_PROCESS] }],
    },
  },

  // 2a — the two modules that DO spawn. Still no vscode: the gate they enforce
  //      (`evaluateExecGate`) takes `trusted` as data so it stays testable.
  {
    files: ['src/core/contract/engine.ts', 'src/core/content/placeholders.ts'],
    rules: {
      'no-restricted-imports': ['error', { paths: [NO_VSCODE] }],
    },
  },

  // 2b — src/mcp: the layering gate, the process gate, and the bundle gate.
  {
    files: ['src/mcp/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        { paths: [NO_VSCODE, ...NO_CHILD_PROCESS], patterns: [NO_ENGINES_FROM_MCP] },
      ],
    },
  },

  // 2c — the vscode shell. It may import vscode; it may not spawn.
  {
    files: ['src/**/*.ts'],
    ignores: ['src/core/**/*.ts', 'src/mcp/**/*.ts', 'src/webview/**/*.ts', 'src/test/**/*.ts'],
    rules: {
      'no-restricted-imports': ['error', { paths: NO_CHILD_PROCESS }],
    },
  },

  // 3 — THE XSS GATE. Webview content arrives from user files; everything is
  //     built with el()/textContent so a strict CSP is not the only defence.
  {
    files: ['src/webview/**/*.ts'],
    rules: {
      'no-restricted-properties': [
        'error',
        { property: 'innerHTML', message: 'Use el()/textContent — innerHTML defeats the CSP.' },
        { property: 'outerHTML', message: 'Use el()/textContent.' },
        { property: 'insertAdjacentHTML', message: 'Use el()/textContent.' },
      ],
      'no-restricted-imports': [
        'error',
        {
          paths: [
            { name: 'vscode', message: 'Webview code runs in a browser context.' },
            ...NO_CHILD_PROCESS,
          ],
          patterns: ['**/commands/*', '**/views/*'],
        },
      ],
    },
  },

  // 4 — tests may use loose shapes for fixtures, and the stdio suite genuinely
  //     spawns the MCP server, which is the only honest way to test it.
  {
    files: ['src/test/**/*.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
);
