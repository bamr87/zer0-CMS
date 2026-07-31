// @ts-check
import tseslint from 'typescript-eslint';

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

  // 2 — THE LAYERING GATE. src/core and src/mcp must stay pure Node so the MCP
  //     server bundles standalone and the core stays unit-testable.
  {
    files: ['src/core/**/*.ts', 'src/mcp/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: 'vscode',
              message:
                'src/core and src/mcp must stay pure Node. The vscode API is only available in ' +
                'src/extension.ts, src/config.ts, src/commands, src/views, src/panel, ' +
                'src/dashboard and src/agent.',
            },
          ],
        },
      ],
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
          paths: [{ name: 'vscode', message: 'Webview code runs in a browser context.' }],
          patterns: ['**/commands/*', '**/views/*'],
        },
      ],
    },
  },

  // 4 — tests may use loose shapes for fixtures
  {
    files: ['src/test/**/*.ts'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
    },
  },
);
