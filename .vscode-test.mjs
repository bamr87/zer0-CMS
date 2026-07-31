import { defineConfig } from '@vscode/test-cli';

export default defineConfig({
  files: 'out/test/**/*.test.js',
  version: '1.101.0',
  workspaceFolder: './src/test/fixtures/workspace',
  mocha: {
    ui: 'tdd',
    timeout: 30000,
  },
});
