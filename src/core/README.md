# `src/core` — the pure layer

> The pure layer — everything zer0-CMS knows how to do, with no `vscode` import: the one rule, the module map, where a type lives, and how it is tested.

Everything zer0-CMS knows how to *do*, with nothing that knows it is running inside an editor.

## The one rule

**No module under `src/core/` may import `vscode`.** It is enforced twice:

- `eslint.config.mjs` block 2 (`no-restricted-imports`) fails the lint, and
- `esbuild.js` builds `src/mcp/server.ts` with an **empty** `external` list, so
a stray `vscode` import anywhere in this graph becomes a *build* error rather than a crash inside somebody's MCP client.

If a core function needs the editor, it takes what it needs as a parameter — a path, a `LogSink`, a callback — and the shell supplies it. That is what makes this layer unit-testable with plain `node`, reusable from the bundled MCP server, and runnable from a script.

The second rule: **zero *shipped* runtime dependencies, and libraries over hand-rolled code** (ADR 0006 decision 9, amending D3 and D14). YAML (`yaml`), JSON with comments (`jsonc-parser`), globs (`picomatch`) and dates (`date-fns`, `@date-fns/tz`) are the maintained libraries, bundled by esbuild into both node bundles from `devDependencies` (`esbuild.js`'s `CORE_LIBRARIES`); Python-parity JSON output stays hand-rolled, because no library writes `json.dumps` byte for byte. The engines package never enters this layer's graph.

## Layout

| Directory | What lives there |
|---|---|
| [`shared/`](shared/README.md) | Primitives with no domain knowledge: types, config resolution, atomic writes, JSON I/O, timestamps, dates, globbing, text. See `shared/README.md`. |
| [`content/`](content/README.md) | The content model: front-matter parse/serialize, fields, content types, folders, placeholders, slugs, article read/write, the page index, SEO metrics. |
| [`governance/`](governance/README.md) | The governed queue: drafts, the brand guard, the ledger, the approval gates, publishing. |
| [`catering/`](catering/README.md) | Distribution planning: the four lanes and the worklist renderer. |
| [`contract/`](contract/README.md) | The `.cms/` file bus: loader, fallback projection, and the Python engine driver. |
| [`analytics/`](analytics/README.md) | The read surface, and the join that turns a platform's statistics into `performance.json`. |
| [`portfolio/`](portfolio/README.md) | The published track record: volume, cadence, streak, collections. |
| [`media/`](media/README.md) | Resolving the preview image a page already has, or emitting the generator's brief. |
| [`platform/`](platform/README.md) | What kind of site this is (decision D12): seven profiles as data, the zer0-mistakes overlay on Jekyll, marker-file detection over injected readers, the site's own config, and the permalink and content-root derivations. See `platform/README.md`. |
| [`fleet/`](fleet/README.md) | The Fleet console's pure half: `fleet.manifest.yml` → typed lanes, the switch/dispatch gate, and the GitHub surface declared as data over an injected `fetch`. See `fleet/README.md`. |
| `studio/` | The studio in a webview (PLAN G10): `bridge.ts`, the host side of the studio webviews' postMessage transport — every gate on a request a webview asks for (the path, the method, a modal before a live-site change, the token added for the configured origin only) over an injected `fetch` — and `page.ts`, the strict-CSP page those webviews load. |
| [`harness/`](harness/README.md) | One vocabulary for the editor agent and CI: the agent, skill and `_data/ai.yml` readers, the harness profile (model precedence, permission-mode clamp, SDK and CI projections), the inventory and its joins, the `wtd fleet adopt` port, the usage ledger, and lane generation. See `harness/README.md`. |
| `index.ts` | The barrel. Import from `../core`, not from individual files, outside of core itself. |

## Where a type lives

Cross-cutting domain types are declared **once**, in `shared/types.ts`: `Zer0Config`, `Field`, `ContentType`, `ContentFolder`, `FieldGroup`, `PageEntry`, `ContentRecord`, `CmsIssue`, `PerfStats`, `Severity`, `Lane`, `Freshness`, `LogSink`, the platform vocabulary `PlatformId`, `PLATFORM_IDS`, `PlatformOverlay`, `PlatformConfig`, `PlatformProbe`, `RootMode`, `DatePrefixRule`, `PlatformContentRoot`, `PlatformProfile`, `PlatformProfileJson`, `SiteConfigFacts`, `ResolvedPlatform`, and the fleet vocabulary `FleetManifest`, `FleetLane`, `FleetTrigger`, `FleetGuardrails`, `FleetToken`, `FleetConfig`.

Types owned by a single module stay with that module and are re-exported by the barrel: `FmValue`/`FrontMatter` (`content/frontmatter.ts`), `DraftFile` (`governance/drafts.ts`), `GuardFinding` (`governance/guard.ts`), `LedgerEntry`/`Ledger` (`governance/ledger.ts`), `Blocker` (`governance/approval.ts`), `Contract` (`contract/contract.ts`), `FleetBlocker`/`FleetLaneState` (`fleet/fleet.ts`), `FleetCall`/`FleetClient` (`fleet/github.ts`).

Declaring the same name in two modules makes `export *` ambiguous and breaks the barrel for everyone — so import a type from where it lives, never redeclare it locally.

## Testing

Core tests run outside the extension host:

```bash
npx tsc -p . --outDir out && npx mocha --ui tdd out/test/{core,fields,governance,golden,loop,fleet,engines,routes,webview,styling,platform,audit,harness,lanes}.test.js   # the fourteen pure-Node suites; or: npm test
```

If a test needs `vscode`, it belongs in `extension.test.ts` (or `multiroot.test.ts` for the two-folder window), not here.
