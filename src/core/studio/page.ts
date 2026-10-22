/**
 * The page a studio webview loads (PLAN G10): `dist/studio.js` and its styles
 * under a strict Content-Security-Policy, as pure text so a test can read the
 * policy without an editor.
 *
 * `default-src 'none'`: no connection at all — the webview's API client and
 * its event streams go through the host (`bridge.ts`), which is what keeps the
 * person's token out of the page. Scripts run only with this render's nonce,
 * and styles come only from the extension's own files or the `<style>`
 * elements Mantine writes, which carry the same nonce (`main.tsx` reads it
 * from the `csp-nonce` meta) — no `'unsafe-inline'` anywhere. Images come from
 * the extension, the platform (a page shows its own media), `data:` and
 * `blob:` — the studio's own policy plus the platform's origin, and never any
 * other host: an image URL is a request, so a page that could load one from
 * anywhere could send what it shows anywhere. `media/tokens.css` loads first:
 * it maps the editor's theme onto the tokens `studio.css` reads.
 */

export type StudioView = 'dashboard' | 'page' | 'ai';

export interface StudioPage {
  /** The webview's own source expression (`webview.cspSource`). */
  cspSource: string;
  /** One per render, from a CSPRNG. */
  nonce: string;
  /** A file of the extension, as the webview may load it (`asWebviewUri`). */
  asset: (...parts: string[]) => string;
  view: StudioView;
  /** `sidebar` for a view in the side bar, `panel` for an editor panel. */
  surface: 'sidebar' | 'panel';
  /** The platform's origin, for images; validated by `platformOrigin`. */
  origin: string | undefined;
}

export function studioPage(page: StudioPage): string {
  const { cspSource, nonce, asset } = page;
  const images = [cspSource, page.origin, 'data:', 'blob:'].filter(Boolean).join(' ');
  const policy = [
    "default-src 'none'",
    `style-src ${cspSource} 'nonce-${nonce}'`,
    `script-src 'nonce-${nonce}'`,
    `font-src ${cspSource}`,
    `img-src ${images}`,
  ].join('; ');
  return `<!DOCTYPE html>
<html lang="en" data-surface="${page.surface}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="${policy};">
<meta property="csp-nonce" nonce="${nonce}">
<link nonce="${nonce}" rel="stylesheet" href="${asset('dist', 'media', 'tokens.css')}">
<link nonce="${nonce}" rel="stylesheet" href="${asset('dist', 'studio.css')}">
<title>zer0 studio</title>
</head>
<body>
<div id="root" data-view="${page.view}"></div>
<script nonce="${nonce}" src="${asset('dist', 'studio.js')}"></script>
</body>
</html>`;
}
