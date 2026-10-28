// The entry of the extension's webviews: esbuild.js at the repository root
// bundles it into dist/studio.js and its styles into dist/studio.css. The
// styles go in the studio's order — the zer0 tokens, Mantine's, @zer0/ui's —
// with the editor's theme last; then the VS Code message port, the CSP nonce
// the host put on the page, and the view it asked for.
import '@zer0/tokens/tokens.css';
import '@mantine/core/styles.css';
import '@mantine/notifications/styles.css';
import '@zer0/ui/ui.css';
import './editor.css';

import { createRoot } from 'react-dom/client';

import { App, type View } from './App';
import type { Port } from './transport';

declare function acquireVsCodeApi(): { postMessage: (message: unknown) => void };

const vscode = acquireVsCodeApi();
const port: Port = {
  post: (message) => vscode.postMessage(message),
  listen: (handler) => {
    const relay = (event: MessageEvent) => handler(event.data);
    window.addEventListener('message', relay);
    return () => window.removeEventListener('message', relay);
  },
};

const VIEWS: readonly View[] = ['dashboard', 'page', 'ai'];
const root = document.getElementById('root');
const view = VIEWS.find((v) => v === root?.dataset.view) ?? 'dashboard';
// `.nonce` is the attribute browsers keep readable (src/studio/studio.ts writes it).
const nonce = document.querySelector<HTMLMetaElement>('meta[property="csp-nonce"]')?.nonce || undefined;
if (root) createRoot(root).render(<App view={view} port={port} nonce={nonce} />);
