/**
 * zer0-CMS build. Five bundles, one tool, no webpack.
 *
 *   dist/extension.js   the VS Code host    (node, `vscode` external)
 *   dist/mcp-server.js  the bundled MCP server (node, NOTHING external)
 *   dist/panel.js       the sidebar webview (browser, iife)
 *   dist/dashboard.js   the dashboard webview (browser, iife)
 *   dist/agent.js       the agent webview   (browser, iife)
 *
 * The MCP bundle's empty `external` list is the layering gate: src/mcp and
 * src/core must stay pure Node, so a stray `import 'vscode'` anywhere in that
 * import graph becomes a BUILD ERROR here — not a runtime crash inside an MCP
 * client launched outside the extension host.
 */

const esbuild = require('esbuild');
const fs = require('fs');
const path = require('path');

const production = process.argv.includes('--production');
const watch = process.argv.includes('--watch');

/** Surfaces esbuild errors in the format VS Code's problem matcher understands. */
const problemMatcherPlugin = {
  name: 'problem-matcher',
  setup(build) {
    build.onStart(() => console.log('[watch] build started'));
    build.onEnd((result) => {
      for (const { text, location } of result.errors) {
        console.error(`✘ [ERROR] ${text}`);
        if (location) {
          console.error(`    ${location.file}:${location.line}:${location.column}:`);
        }
      }
      console.log('[watch] build finished');
    });
  },
};

/**
 * Codicon assets, copied out of the `@vscode/codicons` devDependency.
 *
 * `codicon.css` carries the `@font-face` and the 576 `content:` rules; the
 * `.ttf` is the glyphs. Both land in `dist/media/`, which is a
 * `localResourceRoot` for all three webviews, and the stylesheet's relative
 * `url("./codicon.ttf?…")` resolves next to it.
 *
 * Missing files are a **build error**, not a warning. A webview does not get
 * codicons for free — without these, every `icon()` in `src/webview` renders an
 * empty element and every icon-only control becomes an invisible box, which is
 * a failure that looks exactly like a working build.
 */
const CODICON_FILES = ['codicon.css', 'codicon.ttf'];
const CODICON_DIR = path.join(__dirname, 'node_modules', '@vscode', 'codicons', 'dist');

/** Copies the stylesheets and the icon font the webviews load through `asWebviewUri`. */
const copyMediaPlugin = {
  name: 'copy-media',
  setup(build) {
    build.onEnd(() => {
      const dest = path.join(__dirname, 'dist', 'media');
      fs.mkdirSync(dest, { recursive: true });
      const src = path.join(__dirname, 'media');
      for (const file of fs.readdirSync(src)) {
        if (file.endsWith('.css')) {
          fs.copyFileSync(path.join(src, file), path.join(dest, file));
        }
      }
      for (const file of CODICON_FILES) {
        const from = path.join(CODICON_DIR, file);
        if (!fs.existsSync(from)) {
          throw new Error(
            `esbuild: ${from} is missing. The webviews need @vscode/codicons — run 'npm install'.`,
          );
        }
        fs.copyFileSync(from, path.join(dest, file));
      }
    });
  },
};

/** @type {import('esbuild').BuildOptions[]} */
const targets = [
  {
    entryPoints: ['src/extension.ts'],
    outfile: 'dist/extension.js',
    platform: 'node',
    target: 'node20',
    format: 'cjs',
    // The agent SDK is an optionalDependency loaded through a dynamic import at
    // runtime; it must not be pulled into the bundle.
    external: ['vscode', '@anthropic-ai/claude-agent-sdk'],
    plugins: [problemMatcherPlugin, copyMediaPlugin],
  },
  {
    entryPoints: ['src/mcp/server.ts'],
    outfile: 'dist/mcp-server.js',
    platform: 'node',
    target: 'node20',
    format: 'cjs',
    external: [], // ← the layering gate. Do not add 'vscode' here.
    plugins: [problemMatcherPlugin],
  },
  {
    entryPoints: ['src/webview/panel/main.ts'],
    outfile: 'dist/panel.js',
    platform: 'browser',
    target: 'es2022',
    format: 'iife',
    external: [],
    plugins: [problemMatcherPlugin],
  },
  {
    entryPoints: ['src/webview/dashboard/main.ts'],
    outfile: 'dist/dashboard.js',
    platform: 'browser',
    target: 'es2022',
    format: 'iife',
    external: [],
    plugins: [problemMatcherPlugin],
  },
  {
    entryPoints: ['src/webview/agent/main.ts'],
    outfile: 'dist/agent.js',
    platform: 'browser',
    target: 'es2022',
    format: 'iife',
    external: [],
    plugins: [problemMatcherPlugin],
  },
];

async function main() {
  const shared = {
    bundle: true,
    minify: production,
    sourcemap: !production,
    sourcesContent: false,
    logLevel: 'silent',
  };

  if (watch) {
    const contexts = await Promise.all(targets.map((t) => esbuild.context({ ...shared, ...t })));
    await Promise.all(contexts.map((c) => c.watch()));
    return;
  }

  await Promise.all(targets.map((t) => esbuild.build({ ...shared, ...t })));
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
