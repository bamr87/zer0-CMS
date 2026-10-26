// @ts-check
// Lint for the whole web workspace. Beyond the recommended rules it holds the
// line the shared packages need to render inside VS Code webviews (PLAN G10):
// @zer0/ui takes its router, transport and storage from its host, so it may
// not import a router, reach for fetch/EventSource/storage/location/cookies,
// or inject HTML. Type errors are never suppressed (AGENTS.md).
import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

const HOST_GLOBALS = ['fetch', 'EventSource', 'XMLHttpRequest', 'WebSocket', 'localStorage', 'sessionStorage', 'location', 'history'].map(
  (name) => ({ name, message: `@zer0/ui is rendered by hosts (the studio, the extension's webviews): take ${name} from the host through StudioProvider.` }),
);

export default tseslint.config(
  { ignores: ['**/dist/**', '**/node_modules/**', 'packages/api/src/schema.d.ts'] },
  js.configs.recommended,
  ...tseslint.configs.strict,
  reactHooks.configs.flat['recommended-latest'],
  {
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    rules: {
      '@typescript-eslint/ban-ts-comment': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      'no-empty': ['error', { allowEmptyCatch: false }],
    },
  },
  {
    files: ['packages/ui/src/**'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          paths: [
            { name: 'react-router', message: '@zer0/ui is router-agnostic: navigate through useGo().' },
            { name: 'openapi-fetch', message: '@zer0/ui is transport-agnostic: take the client from useApi().' },
          ],
        },
      ],
      'no-restricted-globals': ['error', ...HOST_GLOBALS],
      'no-restricted-properties': [
        'error',
        { object: 'window', property: 'location', message: 'No page globals in @zer0/ui.' },
        { object: 'document', property: 'cookie', message: 'No page globals in @zer0/ui.' },
        { object: 'window', property: 'fetch', message: 'Take the client from useApi().' },
      ],
      'no-restricted-syntax': [
        'error',
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: 'No injected HTML: render nodes.' },
      ],
    },
  },
);
