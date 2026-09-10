/**
 * The core barrel — the one import path the vscode shell, the MCP server and
 * the tests use. `import { resolveConfig, buildPreview } from '../core'`.
 *
 * Everything re-exported here is pure Node: no module in this graph imports
 * `vscode`, which is what lets the same code run inside the extension host,
 * inside a standalone MCP process, and inside a plain `node` test.
 *
 * Rules for the modules behind these stars:
 *   - A name is declared in exactly one module. Duplicating a type across two
 *     modules makes the star export ambiguous and the barrel stops resolving.
 *   - Cross-cutting domain types (`Zer0Config`, `Field`, `ContentType`,
 *     `ContentRecord`, `CmsIssue`, `PageEntry`, `PerfStats`, `LogSink`, …)
 *     live in `shared/types` and are imported from there — never redeclared.
 */

// --- primitives -------------------------------------------------------------
export * from './shared/types';
export * from './shared/config';
export * from './shared/atomic';
export * from './shared/jsonio';
export * from './shared/timestamp';
export * from './shared/dates';
export * from './shared/glob';
export * from './shared/text';
export * from './shared/trust';

// --- content model ----------------------------------------------------------
export * from './content/frontmatter';
export * from './content/serialize';
export * from './content/fields';
export * from './content/contentType';
export * from './content/folders';
export * from './content/placeholders';
export * from './content/slug';
export * from './content/article';
export * from './content/pageIndex';
export * from './content/seo';
export * from './content/audit';
export * from './content/schema';

// --- the AI harness (decisions D10 and D14) ----------------------------------
// One vocabulary for the agent that runs in this editor and the lanes that run
// in CI: the repository's own model configuration, its `.claude/agents` roles
// and its skills, resolved into a profile that projects to either.
export * from './harness/agents';
export * from './harness/skills';
export * from './harness/aiConfig';
export * from './harness/profile';
export * from './harness/metering';
export * from './harness/workflows';
export * from './harness/derive';
export * from './harness/joins';
export * from './harness/inventory';
export * from './harness/ledger';
export * from './harness/lanes';
export * from './harness/render';
export * from './harness/emitYaml';
export * from './harness/manifestWrite';
export * from './harness/preflight';
// `./harness/selfAudit` is deliberately NOT here: it is the one module in this
// directory that imports the engines seam, and the MCP bundle reaches every
// module the barrel names. A lane can be planned and rendered without it; only
// the editor host audits what it is about to write.

// --- the site's platform (decision D12) --------------------------------------
// What a Jekyll site, an MkDocs site and a Hugo site each mean by "content
// root", "draft", "the date", "the URL" and "the directory to ignore" — as
// data, resolved once, so nothing below has to ask again.
export * from './platform/index';

// --- governance -------------------------------------------------------------
export * from './governance/drafts';
export * from './governance/guard';
export * from './governance/ledger';
export * from './governance/approval';
export * from './governance/publish';
export * from './governance/fileTarget';

// --- catering and the `.cms/` contract --------------------------------------
export * from './catering/catering';
export * from './catering/worklist';
export * from './contract/contract';
export * from './contract/engine';

// --- the feedback loop ------------------------------------------------------
export * from './analytics/analytics';
export * from './portfolio/portfolio';
export * from './media/media';

// --- the fleet console ------------------------------------------------------
export * from './fleet/manifest';
export * from './fleet/fleet';
export * from './fleet/github';

export * from './fleet/adapters';
export * from './fleet/registry';
export * from './fleet/handoff';
export * from './fleet/inspect';

// --- the module that is deliberately NOT here -------------------------------
//
// `./fleet/engines` is NEVER exported from this file, and that is a rule rather
// than an oversight (decision D-A / D14). It is the single import seam for the bundled
// `@bamr87/fleet-engines` package, and the barrel is what `src/mcp` imports
// through — a star export there would drag the package into `dist/mcp-server.js`,
// where `external: []` and the bare-import gate exist precisely to keep it out.
// `adapters.ts` is barrel-safe because it imports the package's *types* only,
// and `import type` is erased before anything is bundled.
