# `src/core` — the pure layer

Everything zer0-CMS knows how to *do*, with nothing that knows it is running
inside an editor.

## The one rule

**No module under `src/core/` may import `vscode`.** It is enforced twice:

- `eslint.config.mjs` block 2 (`no-restricted-imports`) fails the lint, and
- `esbuild.js` builds `src/mcp/server.ts` with an **empty** `external` list, so
  a stray `vscode` import anywhere in this graph becomes a *build* error rather
  than a crash inside somebody's MCP client.

If a core function needs the editor, it takes what it needs as a parameter — a
path, a `LogSink`, a callback — and the shell supplies it. That is what makes
this layer unit-testable with plain `node`, reusable from the bundled MCP
server, and runnable from a script.

The second rule follows from the first: **zero runtime dependencies**. YAML
subset parsing, globbing, date formatting, JSON-with-comments and Python-parity
JSON output are all hand-rolled here against the Node standard library.

## Layout

| Directory | What lives there |
|---|---|
| `shared/` | Primitives with no domain knowledge: types, config resolution, atomic writes, JSON I/O, timestamps, dates, globbing, text. See `shared/README.md`. |
| `content/` | The content model: front-matter parse/serialize, fields, content types, folders, placeholders, slugs, article read/write, the page index, SEO metrics. |
| `governance/` | The governed queue: drafts, the brand guard, the ledger, the approval gates, publishing. |
| `catering/` | Distribution planning: the four lanes and the worklist renderer. |
| `contract/` | The `.cms/` file bus: loader, fallback projection, and the Python engine driver. |
| `index.ts` | The barrel. Import from `../core`, not from individual files, outside of core itself. |

## Where a type lives

Cross-cutting domain types are declared **once**, in `shared/types.ts`:
`Zer0Config`, `Field`, `ContentType`, `ContentFolder`, `FieldGroup`,
`PageEntry`, `ContentRecord`, `CmsIssue`, `PerfStats`, `Severity`, `Lane`,
`Freshness`, `LogSink`.

Types owned by a single module stay with that module and are re-exported by the
barrel: `FmValue`/`FrontMatter` (`content/frontmatter.ts`), `DraftFile`
(`governance/drafts.ts`), `GuardFinding` (`governance/guard.ts`),
`LedgerEntry`/`Ledger` (`governance/ledger.ts`), `Blocker`
(`governance/approval.ts`), `Contract` (`contract/contract.ts`).

Declaring the same name in two modules makes `export *` ambiguous and breaks
the barrel for everyone — so import a type from where it lives, never redeclare
it locally.

## Testing

Core tests run outside the extension host:

```bash
npm run compile-tests && node --test out/test/core.test.js   # or: npm test
```

If a test needs `vscode`, it belongs in `extension.test.ts`, not here.
