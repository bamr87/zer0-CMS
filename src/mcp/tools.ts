/**
 * The eight MCP tools, and the governance baked into their shapes.
 *
 * Every handler has the same signature — `(cfg, args) => Promise<string>` —
 * and returns **prose**, not structured data, including for its failures.
 * That is the MCP convention this server commits to: a model reads the answer,
 * so the answer is written for a reader. `ERROR_PREFIXES` is how a prose
 * result becomes a flagged one; a handler that wants `isError: true` starts
 * its sentence with `error:`, `refused:`, `blocked`, `not found` or
 * `publishing is disabled`.
 *
 * The safety ladder, in the order the tools are declared:
 *
 *   1-4  read-only. `zer0_status`, `zer0_list_content`, `zer0_get_content` and
 *        `zer0_preview` never write and never call out. `zer0_preview` renders
 *        the *exact* artifact a publish would write, built by the configured
 *        target, so it cannot drift from what publishing actually does.
 *     5  `zer0_draft` writes one file, always `status: pending`, into the
 *        governed queue. This is the doctrine-preferred path: the AI drafts,
 *        the human approves.
 *     6  `zer0_publish` is double-gated — `ZER0_CMS_MCP_ALLOW_PUBLISH` in the
 *        server environment AND `confirm: true` in the call. Each gate refuses
 *        on its own, with its own prose, so a refusal always names the thing
 *        that has to change.
 *     7  `zer0_worklist` writes only under `.cms/distribution/`.
 *     8  `zer0_contract` runs the repository's own engine; read-only unless
 *        the caller explicitly asks for `normalize-apply`.
 *
 * Nothing in this file may import `vscode` (decision D1) — the MCP bundle
 * marks nothing external, so a stray editor import is a build error rather
 * than a crash inside somebody's MCP client.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import {
  DEFAULT_CONFIG_FILE,
  ENGINE_COMMANDS,
  absPath,
  buildCatering,
  buildPreview,
  byPath,
  condenseNormalizerOutput,
  distributable,
  engineConfigFor,
  healthBucket,
  isDistributable,
  isEditable,
  issuesByLane,
  listQueue,
  loadContractOrScan,
  loadLedger,
  loadPerformance,
  publishPreview,
  publishedPathsFromLedger,
  readArticle,
  relPath,
  renderWorklist,
  resolveConfig,
  resolveSource,
  runEngine,
  runNormalizerApply,
  runNormalizerPreview,
  shareEntries,
  slugify,
  targetFor,
  utcDate,
  writeDraft,
  writeWorklist,
  type Article,
  type ContentRecord,
  type GuardFinding,
  type Preview,
  type PreviewRequest,
  type PublishOutcome,
  type Zer0Config,
} from '../core';

// ---------------------------------------------------------------------------
// Environment
// ---------------------------------------------------------------------------

/** The publish opt-in. Absent or falsy means `zer0_publish` refuses. */
export const PUBLISH_ENV_VAR = 'ZER0_CMS_MCP_ALLOW_PUBLISH';

/** Optional override for the project config file name, relative to `cwd`. */
export const CONFIG_ENV_VAR = 'ZER0_CMS_CONFIG';

const TRUTHY: ReadonlySet<string> = new Set(['1', 'true', 'yes', 'on']);

export function publishEnabled(env: NodeJS.ProcessEnv): boolean {
  return TRUTHY.has((env[PUBLISH_ENV_VAR] ?? '').trim().toLowerCase());
}

/**
 * Resolve the workspace configuration for a server rooted at `root`.
 *
 * `cwd` is the workspace folder — the extension sets it when it launches the
 * server, and a hand-run `node dist/mcp-server.js` inherits the shell's. The
 * settings layer carries exactly one value: `governance.publishAllow`, pinned
 * to the environment opt-in. That is deliberate. It means the core publish
 * gate and the MCP gate cannot disagree, and it means a `zer0.json` that says
 * `publishAllow: true` still does not let an MCP client publish unless the
 * process was started with the flag.
 */
export async function loadServerConfig(
  root: string,
  env: NodeJS.ProcessEnv = process.env,
): Promise<Zer0Config> {
  const configFile = (env[CONFIG_ENV_VAR] ?? '').trim() || DEFAULT_CONFIG_FILE;
  let file: unknown;
  try {
    file = JSON.parse(await fs.readFile(path.resolve(root, configFile), 'utf8')) as unknown;
  } catch {
    // No config file yet, or an unparseable one. Both mean "use the defaults";
    // `zer0_status` reports which of the two it was, so the model can say so.
    file = {};
  }
  return resolveConfig(root, file, {
    configFile,
    governance: { publishAllow: publishEnabled(env) },
  });
}

// ---------------------------------------------------------------------------
// Argument helpers — every tool argument arrives as `unknown`
// ---------------------------------------------------------------------------

export type ToolArgs = Record<string, unknown>;

function argString(args: ToolArgs, key: string): string {
  const value = args[key];
  return value === undefined || value === null ? '' : String(value).trim();
}

function argBool(args: ToolArgs, key: string): boolean {
  return args[key] === true;
}

function argBoolDefaultTrue(args: ToolArgs, key: string): boolean {
  return args[key] === undefined ? true : args[key] === true;
}

function argCount(args: ToolArgs, key: string, fallback: number, min: number, max: number): number {
  const parsed = Number(args[key]);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(Math.trunc(parsed), max));
}

function reason(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// ---------------------------------------------------------------------------
// Shared rendering
// ---------------------------------------------------------------------------

/** The guard block every write-adjacent tool appends. `info` is not noise-worthy. */
function guardLines(findings: readonly GuardFinding[]): string[] {
  const actionable = findings.filter((finding) => finding.level !== 'info');
  if (actionable.length === 0) {
    return ['brand guard: clean'];
  }
  return ['brand guard:', ...actionable.map((f) => `  ${f.level}: ${f.message}`)];
}

function recordLine(record: ContentRecord): string {
  const health = (record.health >= 0 ? String(record.health) : '—').padStart(3);
  const fresh = record.freshness.padEnd(8);
  const title = record.title === '' ? '(untitled)' : record.title;
  return `  [${health}] ${fresh} ${record.path} — ${title}`;
}

/** Keep the tail of a long stream; the end is where the failure is. */
function tail(text: string, maxLines: number): string {
  const lines = text.trimEnd().split('\n');
  if (lines.length <= maxLines) {
    return lines.join('\n');
  }
  return [`… ${lines.length - maxLines} earlier line(s) omitted`, ...lines.slice(-maxLines)].join(
    '\n',
  );
}

/** The `PreviewRequest` keys a tool call may supply as plain text. */
const REQUEST_FIELDS = [
  'type',
  'ref',
  'message',
  'commentary',
  'title',
  'description',
  'link',
  'slug',
  'folder',
] as const;

function previewRequestFrom(args: ToolArgs): PreviewRequest {
  const request: PreviewRequest = {};
  for (const key of REQUEST_FIELDS) {
    const value = argString(args, key);
    if (value !== '') {
      request[key] = value;
    }
  }
  if (argBool(args, 'noThumbnail')) {
    request.noThumbnail = true;
  }
  return request;
}

/** Render the artifact a target produced: literal bytes when it has them. */
function artifactLines(preview: Preview): string[] {
  const artifact = preview.artifact;
  if (typeof artifact === 'object' && artifact !== null) {
    const shape = artifact as { target?: unknown; path?: unknown; contents?: unknown };
    if (typeof shape.contents === 'string') {
      return [
        `target      : ${typeof shape.target === 'string' ? shape.target : 'unknown'}`,
        `destination : ${typeof shape.path === 'string' ? shape.path : '(unresolved)'}`,
        '--- begin contents ---',
        shape.contents.replace(/\n+$/, ''),
        '--- end contents ---',
      ];
    }
  }
  if (artifact === undefined) {
    return ['(the configured target produced no artifact)'];
  }
  return [JSON.stringify(artifact, null, 2)];
}

// ---------------------------------------------------------------------------
// 1. zer0_status
// ---------------------------------------------------------------------------

async function exists(filePath: string): Promise<boolean> {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    // Missing or unreadable — either way the status line says "not found",
    // which is the only distinction a caller can act on.
    return false;
  }
}

async function toolStatus(cfg: Zer0Config, _args: ToolArgs): Promise<string> {
  const lines: string[] = [
    `workspace   : ${cfg.workspaceRoot || '(none)'}`,
    `config      : ${cfg.configFile} ${(await exists(absPath(cfg, cfg.configFile))) ? '(found)' : '(not found — using defaults)'}`,
    `content     : ${cfg.contentFolders.length} folder(s), ${cfg.contentTypes.length} content type(s)`,
  ];

  const contract = await loadContractOrScan(cfg);
  const ready = distributable(contract);
  lines.push(
    contract.present
      ? `contract    : present, generated ${contract.generatedAt || '(no timestamp)'} — ` +
          `${contract.records.length} record(s), ${ready.length} distributable`
      : `contract    : absent — filesystem scan supplied ${contract.records.length} record(s), ` +
          `${ready.length} distributable (health is unscored)`,
  );

  try {
    const drafts = await listQueue(absPath(cfg, cfg.governance.draftsFolder));
    const counts = new Map<string, number>();
    for (const draft of drafts) {
      counts.set(draft.status, (counts.get(draft.status) ?? 0) + 1);
    }
    const summary =
      drafts.length === 0
        ? 'empty'
        : [...counts.entries()].map(([status, n]) => `${n} ${status}`).join(', ');
    lines.push(`drafts      : ${summary} (${cfg.governance.draftsFolder})`);
  } catch (error) {
    lines.push(`drafts      : unreadable — ${reason(error)}`);
  }

  try {
    const ledger = await loadLedger(absPath(cfg, cfg.governance.ledgerPath));
    lines.push(
      `ledger      : ${shareEntries(ledger).length} published (${cfg.governance.ledgerPath})`,
    );
  } catch (error) {
    lines.push(`ledger      : unreadable — ${reason(error)}`);
  }

  lines.push(
    `governance  : ${cfg.governance.enabled ? 'enabled' : 'disabled'}, target "${cfg.governance.target}"`,
    `publish tool enabled: ${publishEnabled(process.env)} ` +
      `(set ${PUBLISH_ENV_VAR}=1 in the server environment to enable)`,
    'Prefer zer0_draft: it stages a pending draft for a human to approve.',
  );
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 2. zer0_list_content
// ---------------------------------------------------------------------------

async function toolListContent(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  const contract = await loadContractOrScan(cfg);
  const query = argString(args, 'query').toLowerCase();
  const collection = argString(args, 'collection').toLowerCase();
  const limit = argCount(args, 'limit', 20, 1, 100);
  const onlyDistributable = argBool(args, 'onlyDistributable');

  const matched = contract.records.filter((record) => {
    if (onlyDistributable && !isDistributable(record)) {
      return false;
    }
    if (collection !== '' && record.collection.toLowerCase() !== collection) {
      return false;
    }
    if (query === '') {
      return true;
    }
    return (
      record.path.toLowerCase().includes(query) || record.title.toLowerCase().includes(query)
    );
  });

  matched.sort((a, b) => {
    const left = a.health >= 0 ? a.health : -1;
    const right = b.health >= 0 ? b.health : -1;
    if (right !== left) {
      return right - left;
    }
    return a.path < b.path ? -1 : a.path > b.path ? 1 : 0;
  });

  if (matched.length === 0) {
    return contract.present || contract.records.length > 0
      ? 'no content matched.'
      : 'no content found. Register a content folder in zer0.json, or run zer0_contract to build the index.';
  }

  const shown = matched.slice(0, limit);
  const head =
    `${shown.length} of ${matched.length} record(s)` +
    (contract.present ? ':' : ' (from a filesystem scan — health is unscored):');
  const lines = [head, ...shown.map(recordLine)];
  if (matched.length > shown.length) {
    lines.push(`  … ${matched.length - shown.length} more (raise "limit" to see them)`);
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 3. zer0_get_content
// ---------------------------------------------------------------------------

/**
 * The front-matter keys a model may see.
 *
 * A whitelist rather than a blocklist, for the same reason the LinkedIn port
 * whitelisted its response fields: front matter is arbitrary user data, and
 * "everything except the keys we thought of" is not a boundary. Anything not
 * named here is reported as a key name only.
 */
export const CONTENT_FIELDS: readonly string[] = [
  'title',
  'description',
  'excerpt',
  'summary',
  'date',
  'lastmod',
  'last_modified_at',
  'draft',
  'published',
  'categories',
  'category',
  'tags',
  'keywords',
  'slug',
  'permalink',
  'canonical_url',
  'layout',
  'author',
  'image',
  'preview',
];

const BODY_LIMIT = 4000;

async function toolGetContent(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  const ref = argString(args, 'ref');
  if (ref === '') {
    return "error: 'ref' is required (a workspace-relative path, or a filename slug)";
  }

  const contract = await loadContractOrScan(cfg);
  let record = byPath(contract, ref);
  let filePath = record ? absPath(cfg, record.path) : '';
  if (filePath === '' || !(await exists(filePath))) {
    // The contract did not recognise the reference. `resolveSource` knows the
    // fuzzier forms — a bare slug, a partial path — so resolve the file first
    // and then look the record up again by the path it actually found.
    const source = await resolveSource(cfg, ref);
    filePath = source?.filePath ?? '';
    if (source) {
      record = byPath(contract, source.relPath);
    }
  }
  if (filePath === '') {
    return `not found: ${ref}. Use zer0_list_content to see what exists.`;
  }

  let article: Article;
  try {
    article = await readArticle(filePath);
  } catch (error) {
    return `error: cannot read ${relPath(cfg, filePath)} — ${reason(error)}`;
  }

  const kept: Record<string, unknown> = {};
  const withheld: string[] = [];
  for (const [key, value] of Object.entries(article.data)) {
    if (CONTENT_FIELDS.includes(key)) {
      kept[key] = value;
    } else {
      withheld.push(key);
    }
  }

  const lines = [`path        : ${relPath(cfg, filePath)}`];
  if (record) {
    lines.push(
      `collection  : ${record.collection || '(none)'}`,
      `health      : ${record.health >= 0 ? `${record.health} (${healthBucket(record.health)})` : 'unscored'}`,
      `freshness   : ${record.freshness}`,
      `words       : ${record.wordCount}`,
      `editable    : ${isEditable(record)}`,
    );
    const mechanical = issuesByLane(record, 'mechanical');
    const substantive = issuesByLane(record, 'substantive');
    lines.push(
      `issues      : ${mechanical.length} mechanical, ${substantive.length} substantive`,
    );
    for (const issue of [...mechanical, ...substantive]) {
      lines.push(
        `  ${issue.lane}/${issue.severity} ${issue.kind}` +
          `${issue.field ? ` [${issue.field}]` : ''}: ${issue.message}` +
          `${issue.suggestion ? ` → ${issue.suggestion}` : ''}`,
      );
    }
  }

  lines.push('front matter (whitelisted fields):', JSON.stringify(kept, null, 2));
  if (withheld.length > 0) {
    lines.push(`other keys present but not returned: ${withheld.sort().join(', ')}`);
  }

  if (argBool(args, 'includeBody')) {
    const body = article.body.trim();
    lines.push(
      '--- begin body ---',
      body.length > BODY_LIMIT ? `${body.slice(0, BODY_LIMIT)}\n… truncated` : body,
      '--- end body ---',
    );
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 4. zer0_preview
// ---------------------------------------------------------------------------

async function toolPreview(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  let preview: Preview;
  try {
    preview = await buildPreview(cfg, previewRequestFrom(args));
  } catch (error) {
    return `error: ${reason(error)}`;
  }
  const lines = [
    'dry-run — this is the exact artifact a publish would write. Nothing was written.',
    `kind        : ${preview.kind}`,
    ...(preview.url === undefined
      ? ['canonical   : (none — a free-text update has no stable identity and is never ledgered)']
      : [`canonical   : ${preview.url}`]),
    ...artifactLines(preview),
    ...guardLines(preview.guard),
  ];
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 5. zer0_draft — the doctrine-preferred path
// ---------------------------------------------------------------------------

async function toolDraft(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  const requested = argString(args, 'type').toLowerCase();
  const isUpdate = requested === 'text' || requested === 'update';
  const ref = argString(args, 'ref');
  const title = argString(args, 'title');
  const body = isUpdate
    ? argString(args, 'message') || argString(args, 'commentary')
    : argString(args, 'commentary');

  if (isUpdate && body === '') {
    return "error: a text draft needs 'message'";
  }
  if (!isUpdate && ref === '' && title === '') {
    return "error: an article draft needs 'ref' (an existing page) or 'title' + 'description'";
  }

  const stem =
    argString(args, 'slug') ||
    (ref === '' ? '' : path.basename(ref).replace(/\.[^./]+$/, '').replace(/^\d{4}-\d{2}-\d{2}-/, '')) ||
    slugify(title) ||
    (isUpdate ? 'update' : 'article');

  let dest: string;
  try {
    dest = await writeDraft(absPath(cfg, cfg.governance.draftsFolder), {
      type: isUpdate ? 'update' : 'article',
      slug: stem,
      body,
      ...(ref === '' ? {} : { source: ref }),
      ...(title === '' ? {} : { title }),
      ...(argString(args, 'description') === ''
        ? {}
        : { description: argString(args, 'description') }),
      ...(argString(args, 'link') === '' ? {} : { link: argString(args, 'link') }),
      ...(argString(args, 'folder') === ''
        ? {}
        : { extras: { folder: argString(args, 'folder') } }),
    });
  } catch (error) {
    return `error: ${reason(error)}`;
  }

  const lines = [
    `drafted: ${relPath(cfg, dest)}`,
    `type: ${isUpdate ? 'update' : 'article'}  status: pending`,
  ];

  // Advisory only. The authoritative guard runs again at approve and publish.
  try {
    const preview = await buildPreview(cfg, previewRequestFrom(args));
    lines.push(...guardLines(preview.guard));
  } catch (error) {
    lines.push(`preview unavailable: ${reason(error)}`);
  }

  lines.push(
    'Nothing was published. A human reviews and approves the draft — in the editor ' +
      'with "zer0-CMS: Approve draft", then "zer0-CMS: Publish draft"; or, once ' +
      `${PUBLISH_ENV_VAR} is set, with zer0_publish and confirm=true.`,
  );
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 6. zer0_publish — double-gated
// ---------------------------------------------------------------------------

async function toolPublish(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  // Gate one: the environment. Refuses on its own, and names the variable.
  if (!publishEnabled(process.env)) {
    return (
      'publishing is disabled. This tool writes real content into the repository ' +
      `and records it in the idempotency ledger. To enable it, set ${PUBLISH_ENV_VAR}=1 ` +
      'in the server environment. Until then use zer0_preview (dry-run) or ' +
      'zer0_draft (the governed queue).'
    );
  }
  // Gate two: the call. Refuses on its own, and names the alternative.
  if (args.confirm !== true) {
    return (
      'refused: pass confirm=true to publish. Run zer0_preview first and read the ' +
      'exact artifact it returns — this tool writes that file and ledgers it.'
    );
  }

  let preview: Preview;
  try {
    preview = await buildPreview(cfg, previewRequestFrom(args));
  } catch (error) {
    return `error: ${reason(error)}`;
  }

  let outcome: PublishOutcome;
  try {
    outcome = await publishPreview(
      cfg,
      preview,
      targetFor(cfg),
      { force: argBool(args, 'force') },
      { log: (message) => process.stderr.write(`${message}\n`) },
    );
  } catch (error) {
    return `error: publish failed — ${reason(error)}`;
  }

  if (outcome.blocked) {
    return ['blocked:', ...outcome.blocked.map((message) => `  ${message}`)].join('\n');
  }
  if (outcome.skipped) {
    return `${outcome.skipped} (pass force=true to publish it again)`;
  }
  const lines = [...outcome.warnings, `published: ${outcome.urn ?? '(no identifier)'}`];
  if (preview.url !== undefined) {
    lines.push(`  canonical: ${preview.url}`, '  (recorded in the idempotency ledger)');
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 7. zer0_worklist
// ---------------------------------------------------------------------------

async function toolWorklist(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  const date = argString(args, 'date') || utcDate();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return `error: 'date' must be YYYY-MM-DD (got "${date}")`;
  }
  const write = argBoolDefaultTrue(args, 'write');

  const contract = await loadContractOrScan(cfg);
  const performance = await loadPerformance(contract);
  const ledger = await loadLedger(absPath(cfg, cfg.governance.ledgerPath));
  const plan = buildCatering(contract, performance, publishedPathsFromLedger(ledger));
  const body = renderWorklist(plan, date);

  const lines = [
    `lanes: A ${plan.undistributed.length} undistributed, B ${plan.proven.length} proven, ` +
      `C ${plan.quiet.length} quiet, D ${plan.refresh.length} to refresh ` +
      `(${plan.observations} observation(s))`,
  ];
  if (write) {
    try {
      lines.push(`wrote: ${relPath(cfg, await writeWorklist(contract, date, body))}`);
    } catch (error) {
      return `error: cannot write the worklist — ${reason(error)}`;
    }
  } else {
    lines.push('(not written — pass write=true to save it under .cms/distribution/worklists/)');
  }
  lines.push('', body);
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 8. zer0_contract
// ---------------------------------------------------------------------------

/** The engine's own subcommands, plus the two normalizer modes. */
const CONTRACT_COMMANDS: readonly string[] = [
  ...ENGINE_COMMANDS,
  'normalize-preview',
  'normalize-apply',
];

async function toolContract(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  const command = argString(args, 'command') || 'status';
  const engine = engineConfigFor(cfg);
  // `find` rather than a cast: the literal that survives the lookup *is* an
  // EngineCommand, so no assertion is needed to convince the compiler.
  const subcommand = ENGINE_COMMANDS.find((known) => known === command);

  let result;
  if (subcommand !== undefined) {
    result = await runEngine(engine, subcommand);
  } else if (command === 'normalize-preview') {
    result = await runNormalizerPreview(engine);
  } else if (command === 'normalize-apply') {
    result = await runNormalizerApply(engine);
  } else {
    return `error: unknown command "${command}" (one of: ${CONTRACT_COMMANDS.join(', ')})`;
  }

  // Exit 2 means "changes pending" for the *normalizer*. For the engine's own
  // subcommands it means whatever the engine says it means — and `python3`
  // itself exits 2 when it cannot open a script — so the friendly reading is
  // only applied where the contract actually promises it.
  const pending = subcommand === undefined && result.changesPending;
  const failed = result.code !== 0 && !pending;
  const lines = [
    `${failed ? 'error: ' : ''}${command} exited ${result.code}` +
      (pending ? ' — changes pending (exit 2 is "there is work to do")' : ''),
  ];

  const condensed = condenseNormalizerOutput(result.stdout);
  if (condensed.shown !== '') {
    lines.push(tail(condensed.shown, 60));
  }
  if (condensed.skipped > 0) {
    lines.push(`(${condensed.skipped} read-only/vendored file(s) skipped)`);
  }
  if (result.stderr.trim() !== '') {
    lines.push('stderr:', tail(result.stderr, 20));
  }

  const contract = await loadContractOrScan(cfg);
  lines.push(
    contract.present
      ? `contract: ${contract.records.length} record(s), generated ${contract.generatedAt || '(no timestamp)'}`
      : 'contract: still absent — the engine wrote no index. Check zer0Cms.cms.engineScript.',
  );
  if (command === 'normalize-preview') {
    lines.push('Nothing was written. Re-run with command="normalize-apply" to apply the fixes.');
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// The registry — order is the contract the MCP test pins
// ---------------------------------------------------------------------------

export interface ToolSchema {
  type: 'object';
  properties: Record<string, unknown>;
  required?: string[];
}

export interface ToolDef {
  name: string;
  description: string;
  inputSchema: ToolSchema;
  handler: (cfg: Zer0Config, args: ToolArgs) => Promise<string>;
}

const PREVIEW_PROPERTIES: Record<string, unknown> = {
  type: {
    type: 'string',
    enum: ['article', 'text'],
    description: 'article: a page built from a source or from title+description. text: a free update.',
  },
  ref: { type: 'string', description: 'article only: a workspace-relative path or a filename slug' },
  message: { type: 'string', description: 'text only: the update body' },
  commentary: { type: 'string', description: 'override the commentary derived from the source' },
  title: { type: 'string', description: 'article only: title, when no source page supplies one' },
  description: { type: 'string', description: 'article only: description, when no source supplies one' },
  link: { type: 'string', description: 'optional external link recorded in the front matter' },
  slug: { type: 'string', description: 'filename stem for the published file' },
  folder: { type: 'string', description: 'destination content folder, by title or path' },
  noThumbnail: { type: 'boolean', description: 'skip the source page preview image' },
};

export const TOOLS: readonly ToolDef[] = [
  {
    name: 'zer0_status',
    description:
      'Report the workspace configuration, whether the .cms/ contract is present, the ' +
      'draft queue, the ledger, and whether the publish tool is enabled. Read-only. Start here.',
    inputSchema: { type: 'object', properties: {} },
    handler: toolStatus,
  },
  {
    name: 'zer0_list_content',
    description:
      'List content records with health, freshness and path. Falls back to a filesystem ' +
      'scan when the .cms/ index is absent. Read-only.',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'substring matched against path and title' },
        collection: { type: 'string', description: 'restrict to one collection' },
        onlyDistributable: {
          type: 'boolean',
          description: 'only content that is honest to put in front of an audience',
        },
        limit: { type: 'integer', minimum: 1, maximum: 100, description: 'default 20' },
      },
    },
    handler: toolListContent,
  },
  {
    name: 'zer0_get_content',
    description:
      'Read one page: its contract record, its issues by lane, and a whitelisted subset ' +
      'of its front matter. Other front-matter keys are named but not returned. Read-only.',
    inputSchema: {
      type: 'object',
      properties: {
        ref: { type: 'string', description: 'workspace-relative path, or a filename slug' },
        includeBody: { type: 'boolean', description: 'also return the article body (truncated)' },
      },
      required: ['ref'],
    },
    handler: toolGetContent,
  },
  {
    name: 'zer0_preview',
    description:
      'Render the EXACT artifact a publish would write, plus the brand-guard result — ' +
      'without writing anything. Use before zer0_draft or zer0_publish. Read-only.',
    inputSchema: { type: 'object', properties: PREVIEW_PROPERTIES },
    handler: toolPreview,
  },
  {
    name: 'zer0_draft',
    description:
      'Stage a governed draft (status: pending) in the drafts folder for a human to ' +
      'review and approve. The doctrine-preferred path — the AI drafts, the human ' +
      'approves. Publishes nothing.',
    inputSchema: {
      type: 'object',
      properties: { ...PREVIEW_PROPERTIES },
    },
    handler: toolDraft,
  },
  {
    name: 'zer0_publish',
    description:
      'Publish content for real: write the file and record it in the idempotency ledger. ' +
      `OFF by default — needs ${PUBLISH_ENV_VAR}=1 in the server environment AND ` +
      'confirm=true in the call. Runs the brand guard and every publish gate. Prefer ' +
      'zer0_draft.',
    inputSchema: {
      type: 'object',
      properties: {
        ...PREVIEW_PROPERTIES,
        confirm: { type: 'boolean', description: 'must be true to publish' },
        force: {
          type: 'boolean',
          description: 'override brand-guard errors and republish an already-ledgered URL',
        },
      },
      required: ['confirm'],
    },
    handler: toolPublish,
  },
  {
    name: 'zer0_worklist',
    description:
      'Build the catering worklist — what to distribute, what to write more of, what ' +
      'landed quietly, what to refresh — and write it to ' +
      '.cms/distribution/worklists/<date>-catering.md.',
    inputSchema: {
      type: 'object',
      properties: {
        date: { type: 'string', description: 'YYYY-MM-DD; defaults to today (UTC)' },
        write: { type: 'boolean', description: 'write the file (default true)' },
      },
    },
    handler: toolWorklist,
  },
  {
    name: 'zer0_contract',
    description:
      "Run the repository's own content engine and report the result. Read-only for " +
      'index/analyze/plan/all/status and normalize-preview; normalize-apply writes the ' +
      'mechanical front-matter fixes.',
    inputSchema: {
      type: 'object',
      properties: {
        command: {
          type: 'string',
          enum: [...CONTRACT_COMMANDS],
          description: 'default "status"',
        },
      },
    },
    handler: toolContract,
  },
];

/** Lookup by name, built once. */
export const TOOLS_BY_NAME: ReadonlyMap<string, ToolDef> = new Map(
  TOOLS.map((tool) => [tool.name, tool]),
);

/**
 * How prose becomes a flagged result. Handlers return text for humans and
 * models alike, so the leading words are the only structured signal there is —
 * which is why every refusal in this file is written to start with one.
 */
export const ERROR_PREFIXES: readonly string[] = [
  'error:',
  'refused:',
  'blocked',
  'not found',
  'publishing is disabled',
];

export function isErrorText(text: string): boolean {
  const lowered = text.trimStart().toLowerCase();
  return ERROR_PREFIXES.some((prefix) => lowered.startsWith(prefix));
}
