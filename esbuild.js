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
 * The dependency gate — decision D-A's other half.
 *
 * "Zero runtime dependencies" is now stated as "zero *shipped* runtime
 * dependencies": `dependencies` in `package.json` stays `{}`, and the one or
 * two build-time libraries we do consume (`@bamr87/fleet-engines` and its
 * `yaml`) are devDependencies that esbuild inlines into `dist/extension.js`.
 * That is a real distinction only while something enforces it, so this plugin
 * enforces it per target:
 *
 *   - a relative or absolute specifier is always fine;
 *   - a `node:`-prefixed builtin is always fine (and the prefix is the house
 *     convention, so a bare `fs` is deliberately NOT — it fails here);
 *   - anything already named in this target's `external` list is fine, because
 *     that is a declaration that the bundle does not contain it;
 *   - anything else must be named in this target's allow-list, by package name.
 *
 * `dist/mcp-server.js` is built with `external: []` **and** an empty allow-list.
 * Both halves matter: the empty `external` keeps `import 'vscode'` a build
 * error, and the empty allow-list keeps the engines package — and every other
 * bare import — out of the MCP process, which must stay pure Node with no
 * transitive surprises. Adding a name to the MCP target's allow-list is not a
 * build tweak; it is a change to the layering rule in CLAUDE.md.
 */
/** Node's own list of builtins, so the gate does not have to keep its own. */
const BUILTINS = new Set(require('node:module').builtinModules);

function bareImportGate(allow) {
  const allowed = new Set(allow);
  return {
    name: 'bare-import-gate',
    setup(build) {
      const external = new Set(build.initialOptions.external ?? []);
      build.onResolve({ filter: /.*/ }, (args) => {
        if (args.kind === 'entry-point') {
          return null;
        }
        const spec = args.path;
        if (spec.startsWith('.') || spec.startsWith('node:') || path.isAbsolute(spec)) {
          return null;
        }
        // A Node builtin is a builtin however it is spelled. The `node:` prefix
        // is the modern form, but plenty of published code still writes
        // `process`, `buffer` or `path` bare — `yaml` does — and refusing those
        // would make the gate a lint against other people's style rather than a
        // guard on what gets bundled. `builtinModules` is Node's own list.
        if (BUILTINS.has(spec)) {
          return null;
        }
        // `@scope/name/sub` and `name/sub` both belong to their package.
        const parts = spec.split('/');
        const pkg = spec.startsWith('@') ? parts.slice(0, 2).join('/') : parts[0];
        if (external.has(spec) || external.has(pkg) || allowed.has(pkg)) {
          return null;
        }
        const list = allowed.size === 0 ? '(nothing)' : [...allowed].join(', ');
        return {
          errors: [
            {
              text:
                `${spec} is a bare import that ${build.initialOptions.outfile} does not allow. ` +
                `This target bundles: ${list}. Import through a relative path, use a ` +
                `node: builtin, or — if this really is a new bundled dependency — add it to ` +
                `the target's allow-list in esbuild.js and to devDependencies (never to ` +
                `"dependencies", and never to the MCP target).`,
            },
          ],
        };
      });
    },
  };
}

/**
 * Version strings compiled into the two node bundles.
 *
 * They are `define`s rather than a `require('../package.json')` because the
 * bundles are single files with no `package.json` beside them at runtime: the
 * MCP server reports `SERVER_VERSION` to its client, and the engines seam
 * reports which engines build it was compiled against. A missing engines
 * package is a build error for the same reason a missing codicon font is —
 * a silently-wrong version number looks exactly like a working build.
 */
function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

const ENGINES_DIR = path.join(__dirname, 'node_modules', '@bamr87', 'fleet-engines');
const ENGINES_PKG = path.join(ENGINES_DIR, 'package.json');
const LANES_VERSION_FILE = path.join(__dirname, 'media', 'templates', 'ai-runner.VERSION');

function buildDefines() {
  if (!fs.existsSync(ENGINES_PKG)) {
    throw new Error(
      `esbuild: ${ENGINES_PKG} is missing. The extension bundle needs ` +
        "@bamr87/fleet-engines — run 'npm install'.",
    );
  }
  return {
    __ZER0_CMS_VERSION__: JSON.stringify(readJson(path.join(__dirname, 'package.json')).version),
    __ENGINES_VERSION__: JSON.stringify(readJson(ENGINES_PKG).version),
    // The vendored ai-runner kit stamps generated lanes. Until the kit is
    // vendored (a later work package copies it under media/templates/), the
    // stamp is the kit's first published version rather than an empty string,
    // because a lane header reading "kit " is worse than one reading the wrong
    // number — the first is unreadable, the second is checkable.
    __LANES_VERSION__: JSON.stringify(
      fs.existsSync(LANES_VERSION_FILE)
        ? fs.readFileSync(LANES_VERSION_FILE, 'utf8').trim()
        : '0.1.0',
    ),
  };
}

/**
 * The merged esbuild metafile for the two node bundles, written to
 * `out/meta.json`.
 *
 * `outputs['dist/mcp-server.js'].inputs` is the literal list of files that
 * ended up inside the MCP bundle, which is how a test asserts the layering gate
 * from the outside: neither `@bamr87/fleet-engines` nor `yaml` may appear
 * there. The two node builds run concurrently, so each merges its own halves
 * into the shared document rather than overwriting the file.
 */
const META_FILE = path.join(__dirname, 'out', 'meta.json');
const mergedMeta = { inputs: {}, outputs: {} };

const metafilePlugin = {
  name: 'metafile',
  setup(build) {
    build.onEnd((result) => {
      if (!result.metafile) {
        return;
      }
      Object.assign(mergedMeta.inputs, result.metafile.inputs);
      Object.assign(mergedMeta.outputs, result.metafile.outputs);
      fs.mkdirSync(path.dirname(META_FILE), { recursive: true });
      fs.writeFileSync(META_FILE, `${JSON.stringify(mergedMeta, null, 2)}\n`, 'utf8');
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

const DEFINES = buildDefines();

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
    define: DEFINES,
    metafile: true,
    plugins: [
      problemMatcherPlugin,
      // Bundled, by decision D-A. `vscode` and the agent SDK stay external.
      bareImportGate(['@bamr87/fleet-engines', 'yaml']),
      metafilePlugin,
      copyMediaPlugin,
    ],
  },
  {
    entryPoints: ['src/mcp/server.ts'],
    outfile: 'dist/mcp-server.js',
    platform: 'node',
    target: 'node20',
    format: 'cjs',
    external: [], // ← the layering gate. Do not add 'vscode' here.
    define: DEFINES,
    metafile: true,
    // ← the other half of the layering gate: no bare import at all, so the
    // engines package can never reach the MCP process.
    plugins: [problemMatcherPlugin, bareImportGate([]), metafilePlugin],
  },
  {
    entryPoints: ['src/webview/panel/main.ts'],
    outfile: 'dist/panel.js',
    platform: 'browser',
    target: 'es2022',
    format: 'iife',
    external: [],
    plugins: [problemMatcherPlugin, bareImportGate([])],
  },
  {
    entryPoints: ['src/webview/dashboard/main.ts'],
    outfile: 'dist/dashboard.js',
    platform: 'browser',
    target: 'es2022',
    format: 'iife',
    external: [],
    plugins: [problemMatcherPlugin, bareImportGate([])],
  },
  {
    entryPoints: ['src/webview/agent/main.ts'],
    outfile: 'dist/agent.js',
    platform: 'browser',
    target: 'es2022',
    format: 'iife',
    external: [],
    plugins: [problemMatcherPlugin, bareImportGate([])],
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

// Running the file builds; requiring it hands back the gate so a test can
// assert what it refuses without shelling out to a whole build.
if (require.main === module) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}

module.exports = { bareImportGate, targets };
