/**
 * zer0-CMS build. Six bundles, one tool, no webpack.
 *
 *   dist/extension.js   the VS Code host    (node, `vscode` external)
 *   dist/mcp-server.js  the bundled MCP server (node, NOTHING external)
 *   dist/panel.js       the sidebar webview, file mode (browser, iife)
 *   dist/dashboard.js   the dashboard webview, file mode (browser, iife)
 *   dist/agent.js       the agent webview, file mode (browser, iife)
 *   dist/studio.js      the studio's workspaces from web/packages, in every
 *                       webview when a platform is configured (browser, iife;
 *                       its styles land beside it as dist/studio.css)
 *
 * The MCP bundle's empty `external` list is the layering gate: src/mcp and
 * src/core must stay pure Node, so a stray `import 'vscode'` anywhere in that
 * import graph becomes a BUILD ERROR here — not a runtime crash inside an MCP
 * client launched outside the extension host.
 *
 * Every build also writes dist/THIRD_PARTY_NOTICES.txt: the licence of each
 * library the six bundles inline, which the vsix ships beside them.
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
 * The gate reads what *our* code imports — `src/` and `web/packages/` — and
 * not what a bundled library imports in turn: the allow-list names the
 * libraries this code depends on, each of which brings its own (React brings
 * `scheduler`, Mantine brings `@floating-ui/react`). Listing a library's
 * dependencies here would make every upgrade of it an edit to this file
 * without making the bundle any easier to audit; the metafile is that list.
 *
 * `dist/mcp-server.js` is built with `external: []` **and** an empty allow-list.
 * Both halves matter: the empty `external` keeps `import 'vscode'` a build
 * error, and the empty allow-list keeps the engines package — and every other
 * bare import — out of the MCP process, which must stay pure Node with no
 * transitive surprises. Adding a name to the MCP target's allow-list is not a
 * build tweak; it is a change to the layering rule in AGENTS.md.
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
        if (args.kind === 'entry-point' || args.importer.includes(`${path.sep}node_modules${path.sep}`)) {
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

/**
 * `dist/THIRD_PARTY_NOTICES.txt`: every package whose files a bundle inlines
 * — read from the six builds' metafiles, so nothing is listed by hand — with
 * its version, its licence and the licence text it ships. The bundles are
 * minified and keep no banners, and MIT, ISC, BSD and Apache-2.0 all ask for
 * the notice in every copy distributed, which the vsix is. A bundled package
 * that declares no licence fails the build: shipping it would be a question
 * nobody had asked.
 */
const NOTICES_FILE = path.join(__dirname, 'dist', 'THIRD_PARTY_NOTICES.txt');
const LICENCE_FILE = /^(licen[cs]e|copying|notice)/i;

function writeNotices(metafiles) {
  const dirs = new Map();
  for (const input of metafiles.flatMap((meta) => Object.keys(meta.inputs))) {
    const at = input.lastIndexOf('node_modules/');
    if (at >= 0) {
      const [scope, name] = input.slice(at + 'node_modules/'.length).split('/');
      const pkg = scope.startsWith('@') ? `${scope}/${name}` : scope;
      dirs.set(path.join(__dirname, input.slice(0, at), 'node_modules', pkg), pkg);
    }
  }
  const notices = new Map();
  for (const [dir, name] of dirs) {
    const pkg = readJson(path.join(dir, 'package.json'));
    const licence = typeof pkg.license === 'string' ? pkg.license : (pkg.license ?? pkg.licenses?.[0])?.type;
    if (!licence) {
      throw new Error(`esbuild: ${name} is bundled into dist/ and its package.json declares no licence.`);
    }
    const files = fs.readdirSync(dir).filter((file) => LICENCE_FILE.test(file)).sort();
    const text = files.map((file) => fs.readFileSync(path.join(dir, file), 'utf8').trim()).join('\n\n');
    const author = typeof pkg.author === 'string' ? pkg.author : pkg.author?.name;
    const declared = `(The package ships no licence file; its package.json says ${licence}${author ? `, by ${author}` : ''}.)`;
    notices.set(`${pkg.name}@${pkg.version}`, `${licence}\n\n${text || declared}`);
  }
  const body = [...notices]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([id, notice]) => `${'='.repeat(78)}\n${id} — ${notice}\n`);
  fs.mkdirSync(path.dirname(NOTICES_FILE), { recursive: true });
  fs.writeFileSync(
    NOTICES_FILE,
    'zer0-CMS bundles the following libraries into dist/. Their licences and notices follow.\n\n' +
      body.join('\n'),
    'utf8',
  );
}

/**
 * The libraries src/core reads its inputs with (ADR 0006 decision 9, which
 * amends D3 and D14): YAML, JSON with comments, globs and dates, each the
 * maintained library rather than a hand-rolled subset. Core runs in both
 * node bundles — the extension host and the MCP server — so both bundle these.
 * The MCP server still bundles nothing else: never `vscode` (its empty
 * `external`) and never the engines package (eslint's NO_ENGINES_FROM_MCP).
 */
const CORE_LIBRARIES = ['yaml', 'jsonc-parser', 'picomatch', 'date-fns', '@date-fns/tz'];

/**
 * A package's ESM build before its `main` for the node bundles (a package
 * with an `exports` map is unaffected): `jsonc-parser`'s `main` is a UMD build
 * whose factory takes `require` as a parameter, which a bundler cannot follow.
 */
const NODE_MAIN_FIELDS = ['module', 'main'];

/**
 * What the studio bundle may import from its own code: the shared web packages
 * and the libraries the studio is built on (web/README.md), by package name.
 * The same list, read from the studio's side, is the dependencies of the
 * package.json files under web/packages.
 */
const STUDIO_LIBRARIES = [
  '@zer0/api',
  '@zer0/tokens',
  '@zer0/ui',
  'react',
  'react-dom',
  '@mantine/core',
  '@mantine/hooks',
  '@mantine/notifications',
  '@mantine/tiptap',
  '@tanstack/react-query',
  '@tiptap/core',
  '@tiptap/extension-link',
  '@tiptap/markdown',
  '@tiptap/pm',
  '@tiptap/react',
  '@tiptap/starter-kit',
  'diff',
  'openapi-fetch',
];

/**
 * The studio bundle is built from web/, whose libraries web/'s own lockfile
 * installs (the root `postinstall` runs `npm ci` there). Without them every
 * import fails one by one; this says the one thing to do instead.
 */
const webInstalled = {
  name: 'web-installed',
  setup(build) {
    build.onStart(() => {
      if (!fs.existsSync(path.join(__dirname, 'web', 'node_modules', '@mantine', 'core'))) {
        return {
          errors: [
            {
              text:
                'dist/studio.js is built from web/packages, and web/ has no node_modules. ' +
                "Run 'npm ci' at the repository root (its postinstall installs web/) or 'npm ci' in web/.",
            },
          ],
        };
      }
      return null;
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
    mainFields: NODE_MAIN_FIELDS,
    // The agent SDK is an optionalDependency loaded through a dynamic import at
    // runtime; it must not be pulled into the bundle.
    external: ['vscode', '@anthropic-ai/claude-agent-sdk'],
    define: DEFINES,
    metafile: true,
    plugins: [
      problemMatcherPlugin,
      // Bundled, by decision D-A. `vscode` and the agent SDK stay external.
      // `eventsource` follows a run's event stream with the person's token
      // as a header, which the browser's EventSource cannot send (PLAN G10).
      bareImportGate(['@bamr87/fleet-engines', 'eventsource', ...CORE_LIBRARIES]),
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
    mainFields: NODE_MAIN_FIELDS,
    external: [], // ← the layering gate. Do not add 'vscode' here.
    define: DEFINES,
    metafile: true,
    // ← the other half of the layering gate: only the libraries core reads
    // with, so the engines package — and anything else — never reaches the
    // MCP process.
    plugins: [problemMatcherPlugin, bareImportGate(CORE_LIBRARIES), metafilePlugin],
  },
  {
    entryPoints: ['src/webview/panel/main.ts'],
    outfile: 'dist/panel.js',
    platform: 'browser',
    target: 'es2022',
    format: 'iife',
    external: [],
    // The date field formats and parses with core's dates.ts, in the page.
    plugins: [problemMatcherPlugin, bareImportGate(['date-fns', '@date-fns/tz'])],
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
  {
    // The studio's workspaces in every webview once a platform is configured
    // (PLAN G10, ADR 0006 decision 9): web/packages/webview's entry, with the
    // same libraries the studio uses bundled at build time — never shipped as
    // dependencies — and its CSS (Mantine's, the tokens', the editor theme's)
    // written beside it as dist/studio.css.
    entryPoints: ['web/packages/webview/src/main.tsx'],
    outfile: 'dist/studio.js',
    platform: 'browser',
    target: 'es2022',
    format: 'iife',
    jsx: 'automatic',
    external: [],
    plugins: [problemMatcherPlugin, webInstalled, bareImportGate(STUDIO_LIBRARIES)],
  },
];

async function main() {
  const shared = {
    bundle: true,
    minify: production,
    sourcemap: !production,
    sourcesContent: false,
    logLevel: 'silent',
    metafile: true,
  };

  if (watch) {
    const contexts = await Promise.all(targets.map((t) => esbuild.context({ ...shared, ...t })));
    await Promise.all(contexts.map((c) => c.watch()));
    return;
  }

  const results = await Promise.all(targets.map((t) => esbuild.build({ ...shared, ...t })));
  writeNotices(results.map((result) => result.metafile));
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
