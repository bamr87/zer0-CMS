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

// --- governance -------------------------------------------------------------
export * from './governance/drafts';
export * from './governance/guard';
export * from './governance/ledger';
export * from './governance/approval';
export * from './governance/publish';

// --- catering and the `.cms/` contract --------------------------------------
export * from './catering/catering';
export * from './catering/worklist';
export * from './contract/contract';
export * from './contract/engine';

// --- the feedback loop ------------------------------------------------------
export * from './analytics/analytics';
export * from './portfolio/portfolio';
export * from './media/media';
