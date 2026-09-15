/**
 * The sixteen MCP tools, and the governance baked into their shapes.
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
 *        the caller explicitly asks for `normalize-apply`. It is gated on
 *        `ZER0_CMS_MCP_ALLOW_EXEC`, which only the editor sets and only in a
 *        **trusted** workspace — a server started by hand or from a committed
 *        `.vscode/mcp.json` gets no `env` at all and therefore spawns nothing.
 *    12  `zer0_fleet_status` reads the local `fleet.manifest.yml` and nothing
 *        else — no network from this process, ever. The switch state lives in
 *        the repository's Actions variables and only the dashboard reads it,
 *        behind a person's sign-in; this tool says so rather than guess.
 *    13  `zer0_audit` reads every page's front matter and reports what is
 *        missing, malformed or duplicated. It *describes* the change set that
 *        would repair each fixable finding and applies none of them: the tool
 *        that writes is the editor's `audit.fix`, which re-reads the file,
 *        re-runs the rule, renders a diff and asks a person (decision D5).
 * 14-15  `zer0_harness_inventory` and `zer0_lane_preview` are read-only over
 *        local files: what this repository's AI machinery *is*, and exactly
 *        what generating a new lane would write.
 *    16  `zer0_lane_scaffold` is the only non-content write in this file, and
 *        it is double-gated exactly as `zer0_publish` is —
 *        `ZER0_CMS_MCP_ALLOW_SCAFFOLD` in the environment AND `confirm: true`
 *        in the call — with the fleet's own scaffold gate behind both. It
 *        writes files and creates **no** repository variable: the lane stays
 *        inert until a person makes its `*_ENABLED` variable themselves.
 *
 * ### The three environment variables that are not the publish flag
 *
 * `ZER0_CMS_MCP_ALLOW_EXEC` is the execution opt-in (decision D13), and it
 * carries the editor's Workspace Trust answer across the process boundary:
 * this process cannot ask `vscode` anything, so the one thing it can do is
 * refuse unless it was *told*. `ZER0_CMS_PYTHON` pins the interpreter to the
 * settings layer exactly the way `governance.publishAllow` is pinned — a
 * `zer0.json` arrives with the repository, and choosing which binary runs is
 * not a decision a cloned file gets to make. The script it runs is fenced
 * separately, and always: `evaluateExecGate` refuses a path that resolves
 * outside the workspace root whichever layer supplied it.
 *
 * `ZER0_CMS_MCP_ALLOW_SCAFFOLD` is the publish flag pointed at the working
 * tree. On the other side of it is a **workflow file** written into the
 * repository, so the editor reads `zer0Cms.fleet.scaffoldAllow` from the
 * settings layer alone and injects the flag only in a trusted workspace whose
 * fleet console is enabled — which is why `zer0_lane_scaffold` can treat that
 * one bit as the answer to both settings-layer questions.
 *
 * Nothing in this file may import `vscode` (decision D1) — the MCP bundle
 * marks nothing external, so a stray editor import is a build error rather
 * than a crash inside somebody's MCP client.
 */

import { existsSync } from 'node:fs';
import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import {
  AUDIT_RULE_SPECS,
  DEFAULT_CONFIG_FILE,
  DEFAULT_INVENTORY_OPTIONS,
  ENGINE_COMMANDS,
  TEMPLATE_FILES,
  absPath,
  auditSite,
  buildCatering,
  buildIndex,
  buildPortfolio,
  buildPreview,
  byPath,
  condenseNormalizerOutput,
  countLabel,
  describeGuardrails,
  describeTriggers,
  describeHarnessInventory,
  detectPlatform,
  distributable,
  engineConfigFor,
  evaluateFleetGates,
  fixFor,
  insideWorkspace,
  healthBucket,
  isDistributable,
  isEditable,
  issuesByLane,
  listQueue,
  loadLedger,
  ingestPerformance,
  loadPerformance,
  mediaCoverage,
  parseKitVersion,
  planScaffold,
  publishPreview,
  publishedPathsFromLedger,
  renderCoverage,
  renderManifestLane,
  renderPortfolio,
  readArticle,
  readFleetManifest,
  readHarnessInventory,
  readJsonc,
  readSiteSchema,
  relPath,
  unwrapStats,
  writePerformance,
  renderWorklist,
  resolveConfig,
  resolveContentType,
  resolveSource,
  runEngine,
  scaffoldGateFacts,
  runNormalizerApply,
  runNormalizerPreview,
  shareEntries,
  slugify,
  splitFrontMatter,
  targetFor,
  utcDate,
  withPlatformDefaults,
  writeDraft,
  writeWorklist,
  type Article,
  type AuditIssue,
  type ContentRecord,
  type FleetGateInput,
  type FmBlock,
  type GuardFinding,
  type HarnessInventory,
  type HarnessIo,
  type KeyChange,
  type LaneKindVerb,
  type LaneSetup,
  type LaneSpec,
  type PageEntry,
  type PlatformIo,
  type PlatformProfile,
  type Preview,
  type PreviewRequest,
  type PublishOutcome,
  type ScaffoldPlan,
  type SiteSchema,
  type Zer0Config,
} from '../core';
import { loadContractCached } from './cache';

// ---------------------------------------------------------------------------
// Environment
// ---------------------------------------------------------------------------

/** The publish opt-in. Absent or falsy means `zer0_publish` refuses. */
export const PUBLISH_ENV_VAR = 'ZER0_CMS_MCP_ALLOW_PUBLISH';

/**
 * The execution opt-in. Absent or falsy means `zer0_contract` refuses.
 *
 * The editor sets it only when the workspace is **trusted** (D13), and sets it
 * to `null` — remove the variable — otherwise, never to `"0"`. This process
 * cannot read Workspace Trust for itself, so an absent variable and an
 * untrusted workspace have to look the same from here, and they do: no spawn.
 */
export const EXEC_ENV_VAR = 'ZER0_CMS_MCP_ALLOW_EXEC';

/**
 * The interpreter, pinned to the settings layer by the editor.
 *
 * Same reasoning as the publish flag: `zer0.json` ships with the repository, so
 * `{"cms":{"python":"./tools/definitely-python"}}` in a clone must not decide
 * which binary this server executes. When it is set, it wins over every layer;
 * when the editor did not set it, `zer0Cms.cms.pythonPath` was left at its
 * default and the default is what arrives here.
 */
export const PYTHON_ENV_VAR = 'ZER0_CMS_PYTHON';

/**
 * The lane-scaffolding opt-in. Absent or falsy means `zer0_lane_scaffold`
 * refuses.
 *
 * The publish flag's reasoning, pointed at the working tree instead of at a
 * publishing target: on the other side of this gate is a **workflow file**
 * written into a repository, and a `zer0.json` that arrived with a clone must
 * not be able to arm the thing that writes the repository's next workflow. The
 * editor injects it from `zer0Cms.fleet.scaffoldAllow` read through the
 * settings layer alone, and only in a trusted workspace — which is also why an
 * absent variable and an untrusted workspace look identical from here: no
 * write.
 */
export const SCAFFOLD_ENV_VAR = 'ZER0_CMS_MCP_ALLOW_SCAFFOLD';

/** Optional override for the project config file name, relative to `cwd`. */
export const CONFIG_ENV_VAR = 'ZER0_CMS_CONFIG';

const TRUTHY: ReadonlySet<string> = new Set(['1', 'true', 'yes', 'on']);

export function publishEnabled(env: NodeJS.ProcessEnv): boolean {
  return TRUTHY.has((env[PUBLISH_ENV_VAR] ?? '').trim().toLowerCase());
}

/** Whether this server may start a process at all. `zer0_contract`'s gate. */
export function execEnabled(env: NodeJS.ProcessEnv): boolean {
  return TRUTHY.has((env[EXEC_ENV_VAR] ?? '').trim().toLowerCase());
}

/** Whether this server may write a lane's files. `zer0_lane_scaffold`'s gate. */
export function scaffoldEnabled(env: NodeJS.ProcessEnv): boolean {
  return TRUTHY.has((env[SCAFFOLD_ENV_VAR] ?? '').trim().toLowerCase());
}

/**
 * Resolve the workspace configuration for a server rooted at `root`.
 *
 * `cwd` is the workspace folder — the extension sets it when it launches the
 * server, and a hand-run `node dist/mcp-server.js` inherits the shell's. The
 * settings layer carries exactly two values, and both are pinned to the
 * environment rather than read from the file:
 *
 *   - `governance.publishAllow`, from `ZER0_CMS_MCP_ALLOW_PUBLISH`. The core
 *     publish gate and the MCP gate therefore cannot disagree, and a
 *     `zer0.json` saying `publishAllow: true` still does not let an MCP client
 *     publish unless the process was started with the flag.
 *   - `cms.python`, from `ZER0_CMS_PYTHON`, when the editor set it. Same
 *     reasoning pointed at the interpreter: a file that arrives with a clone
 *     does not get to choose which binary runs.
 *
 * An absent `ZER0_CMS_PYTHON` is left absent rather than pinned to a guess, so
 * a hand-run server still resolves the interpreter through the normal three
 * layers — and refuses to spawn anyway, because `ZER0_CMS_MCP_ALLOW_EXEC` is
 * absent too.
 */
export async function loadServerConfig(
  root: string,
  env: NodeJS.ProcessEnv = process.env,
): Promise<Zer0Config> {
  const configFile = (env[CONFIG_ENV_VAR] ?? '').trim() || DEFAULT_CONFIG_FILE;
  let file: unknown;
  try {
    // readJsonc, not JSON.parse: the manifest maps `zer0.json` to the `jsonc`
    // language and the extension reads it the same way, so a config with a
    // comment in it is legal. Parsing it strictly here would send the server
    // silently back to defaults on a file the editor reads fine.
    file = readJsonc<unknown>(await fs.readFile(path.resolve(root, configFile), 'utf8'));
  } catch {
    // No config file yet, or an unparseable one. Both mean "use the defaults";
    // `zer0_status` reports which of the two it was, so the model can say so.
    file = {};
  }
  const python = (env[PYTHON_ENV_VAR] ?? '').trim();
  return resolveConfig(root, file, {
    configFile,
    governance: { publishAllow: publishEnabled(env) },
    // `exactOptionalPropertyTypes`: an unset variable is an absent key, not a
    // key holding `undefined` — the merge reads the two the same way, but the
    // shape is the one the settings layer everywhere else in this repo uses.
    ...(python === '' ? {} : { cms: { python } }),
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

  const contract = await loadContractCached(cfg);
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
    `engine execution enabled: ${execEnabled(process.env)} ` +
      `(${EXEC_ENV_VAR}; the editor sets it only in a trusted workspace)`,
    'Prefer zer0_draft: it stages a pending draft for a human to approve.',
  );
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 2. zer0_list_content
// ---------------------------------------------------------------------------

async function toolListContent(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  const contract = await loadContractCached(cfg);
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

  const contract = await loadContractCached(cfg);
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
      `words       : ${countLabel(record.wordCount, 'uncounted')}`,
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
    slugify(title, cfg.slug.stopWords) ||
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

  const contract = await loadContractCached(cfg);
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
// 8. zer0_ingest — the step that closes the loop
// ---------------------------------------------------------------------------

/**
 * Join a platform's statistics onto content paths and store them.
 *
 * Without this the catering lane can render a worklist but only from a file
 * somebody typed by hand, so Lanes B–D stayed empty in practice. There is no
 * fetch here on purpose: the statistics arrive as a file the operator exported,
 * which keeps the credential out of the pure layer and makes the input
 * something a human has looked at.
 */
async function toolIngest(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  const from = argString(args, 'path');
  if (from === '') {
    return "error: 'path' is required — a JSON file of statistics keyed by post id";
  }
  const write = argBoolDefaultTrue(args, 'write');

  let raw: unknown;
  try {
    raw = JSON.parse(await fs.readFile(absPath(cfg, from), 'utf8'));
  } catch (error) {
    return `error: cannot read ${from} — ${reason(error)}`;
  }

  const stats = unwrapStats(raw);
  if (Object.keys(stats).length === 0) {
    return `error: ${from} carries no statistics (expected an object keyed by post id, or {"posts": {...}})`;
  }

  const contract = await loadContractCached(cfg);
  const ledger = await loadLedger(absPath(cfg, cfg.governance.ledgerPath));
  const existing = await loadPerformance(contract);
  const result = ingestPerformance(ledger, stats, existing);

  const lines = [
    `ingested: ${result.matched.length} of ${Object.keys(stats).length} post(s) ` +
      `onto content paths (${Object.keys(result.performance).length} page(s) now carry data)`,
  ];
  if (result.unmatched.length > 0) {
    lines.push(
      `unmatched: ${result.unmatched.length} post id(s) have no ledger entry, so there is ` +
        'no page to attribute them to — ' +
        result.unmatched.slice(0, 5).join(', '),
    );
  }
  if (write) {
    try {
      lines.push(`wrote: ${relPath(cfg, await writePerformance(contract, result.performance))}`);
      lines.push('next: zer0_worklist');
    } catch (error) {
      return `error: cannot write the performance file — ${reason(error)}`;
    }
  } else {
    lines.push('(not written — pass write=true to save it under .cms/distribution/)');
  }
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 9. zer0_portfolio
// ---------------------------------------------------------------------------

async function toolPortfolio(cfg: Zer0Config, _args: ToolArgs): Promise<string> {
  const contract = await loadContractCached(cfg);
  const ledger = await loadLedger(absPath(cfg, cfg.governance.ledgerPath));
  return renderPortfolio(buildPortfolio(ledger, contract));
}

// ---------------------------------------------------------------------------
// 10. zer0_media
// ---------------------------------------------------------------------------

async function toolMedia(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  const limit = argCount(args, 'limit', 50, 1, 500);
  const contract = await loadContractCached(cfg);
  const records = distributable(contract).slice(0, limit);
  if (records.length === 0) {
    return 'media: no distributable content to check.';
  }
  return renderCoverage(await mediaCoverage(contract.root, records));
}

// ---------------------------------------------------------------------------
// 11. zer0_contract
// ---------------------------------------------------------------------------

/** The engine's own subcommands, plus the two normalizer modes. */
const CONTRACT_COMMANDS: readonly string[] = [
  ...ENGINE_COMMANDS,
  'normalize-preview',
  'normalize-apply',
];

async function toolContract(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  // The gate, ahead of everything: this tool is the one that starts a process
  // (decision D13). The editor sets the variable only for a trusted workspace,
  // so a server launched from a committed `.vscode/mcp.json`, or by hand, or
  // in a folder the user has not trusted, stops right here — and says which
  // thing has to change, the way every other refusal in this file does.
  if (!execEnabled(process.env)) {
    return (
      'engine execution is disabled. This tool runs the interpreter and scripts named by ' +
      `this repository's configuration. The editor sets ${EXEC_ENV_VAR}=1 only in a trusted ` +
      'workspace; a server started by hand never gets it. Use zer0_status, zer0_list_content ' +
      'or zer0_get_content to read what the contract already holds.'
    );
  }

  const command = argString(args, 'command') || 'status';
  // This process has no settings layer of its own — `ZER0_CMS_PYTHON` is the
  // only way a person's choice reaches it — and it cannot tell a `zer0.json`
  // value apart from the built-in default, because `loadServerConfig` has
  // already merged them. So it names the more suspicious of the two. `trusted`
  // is `true` because the environment variable above *is* the editor's trust
  // answer; the engine still refuses a script that leaves the workspace.
  const engine = engineConfigFor(cfg, {
    trusted: true,
    layer: (process.env[PYTHON_ENV_VAR] ?? '').trim() === '' ? 'zer0.json' : 'settings',
  });
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

  const contract = await loadContractCached(cfg);
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
// 12. zer0_fleet_status
// ---------------------------------------------------------------------------

/**
 * The lanes this repository's manifest declares, as prose. Local file only:
 * the MCP server never opens a socket, so the one thing it cannot report —
 * whether each `*_ENABLED` variable is set — is stated as unknown, with the
 * place that does know named.
 */
async function toolFleetStatus(cfg: Zer0Config, _args: ToolArgs): Promise<string> {
  const manifestPath = absPath(cfg, cfg.fleet.manifestPath);
  const parsed = await readFleetManifest(manifestPath);
  if (parsed.manifest === null) {
    return `not found: ${cfg.fleet.manifestPath} — ${parsed.reason}`;
  }
  const manifest = parsed.manifest;
  const lines = [
    `fleet: ${manifest.repo} (${manifest.specVersion}, provenance ${manifest.provenance})`,
    manifest.summary === '' ? '' : `  ${manifest.summary}`,
    `  manifest: ${cfg.fleet.manifestPath}`,
    `  console: ${cfg.fleet.enabled ? 'enabled' : 'disabled'} in this workspace`,
    '',
    `lanes (${manifest.lanes.length}):`,
  ];
  for (const lane of manifest.lanes) {
    lines.push(`  ${lane.id} — ${lane.description}`);
    lines.push(`    kind ${lane.kind} · harness ${lane.harness} · ${lane.implementation || '(no workflow)'}`);
    lines.push(`    triggers: ${describeTriggers(lane.triggers)}`);
    lines.push(
      lane.switch === null
        ? '    switch: none (ungated)'
        : `    switch: ${lane.switch} — state unknown from here; the dashboard reads it`,
    );
    lines.push(`    tokens: ${lane.usesTokens.length === 0 ? '(none declared)' : lane.usesTokens.join(', ')}`);
    lines.push(`    guardrails: ${describeGuardrails(lane.guardrails)}`);
  }
  if (manifest.tokens.length > 0) {
    lines.push('', `tokens (${manifest.tokens.length}), names only:`);
    for (const token of manifest.tokens) {
      lines.push(
        `  ${token.name} — ${token.required ? 'required' : 'optional'}, scope ${token.scope || '(unspecified)'}` +
          (token.purpose === '' ? '' : `: ${token.purpose}`),
      );
    }
  }
  if (manifest.agents.length > 0 || manifest.skills.length > 0) {
    lines.push('', `agents: ${manifest.agents.join(', ') || '(none)'}`, `skills: ${manifest.skills.join(', ') || '(none)'}`);
  }
  lines.push(
    '',
    'switch state unknown from here — the dashboard reads it. This tool reads the local',
    'manifest only; it makes no network calls and cannot flip a switch or dispatch a lane.',
  );
  return lines.filter((line, index) => !(line === '' && index === 1)).join('\n');
}

// ---------------------------------------------------------------------------
// 13. zer0_audit
// ---------------------------------------------------------------------------

/** How many files the audit reads at once when it re-reads blocks for lines. */
const AUDIT_READ_CONCURRENCY = 8;

/** The severities a caller may narrow to. Anything else is a refusal. */
const AUDIT_SEVERITIES: readonly string[] = ['error', 'warning', 'info'];

/** Detection and schema ingestion both read relative paths under the root. */
function auditIo(root: string): PlatformIo {
  return {
    exists: async (rel) => {
      try {
        await fs.access(path.resolve(root, rel));
        return true;
      } catch {
        // Missing or unreadable: either way this marker is not evidence.
        return false;
      }
    },
    read: async (rel) => {
      try {
        return await fs.readFile(path.resolve(root, rel), 'utf8');
      } catch {
        return undefined;
      }
    },
  };
}

/** Read every page's raw block, bounded, so findings can carry line numbers. */
async function auditBlocks(pages: readonly PageEntry[]): Promise<Map<string, FmBlock>> {
  const blocks = new Map<string, FmBlock>();
  let cursor = 0;
  const worker = async (): Promise<void> => {
    for (;;) {
      const index = cursor;
      cursor += 1;
      const page = pages[index];
      if (page === undefined) {
        return;
      }
      try {
        const { block } = splitFrontMatter(await fs.readFile(page.filePath, 'utf8'));
        if (block !== null) {
          blocks.set(page.relPath, block);
        }
      } catch {
        // Gone since the index was built. The projection still answers every
        // rule that does not need a line number (decision D9).
      }
    }
  };
  await Promise.all(
    Array.from({ length: Math.min(AUDIT_READ_CONCURRENCY, Math.max(pages.length, 1)) }, () =>
      worker(),
    ),
  );
  return blocks;
}

/** One `KeyChange`, as the sentence a model should read before proposing it. */
function changeLine(change: KeyChange): string {
  if (change.value === undefined) {
    return `remove ${change.key}`;
  }
  return `set ${change.key} = ${
    typeof change.value === 'string' ? change.value : JSON.stringify(change.value)
  }`;
}

/**
 * The change set that would repair one finding, described and never applied.
 *
 * The article is read here, inside the tool, so the proposal is derived from
 * the bytes on disk at the moment of the call rather than from the index's
 * projection. It is still only a description: nothing in this file writes a
 * content file, and the editor's own `audit.fix` re-derives all of this from
 * scratch before it shows anybody a diff.
 */
async function proposedFix(
  cfg: Zer0Config,
  profile: PlatformProfile,
  issue: AuditIssue,
  now: Date,
): Promise<string> {
  let article: Article;
  try {
    article = await readArticle(absPath(cfg, issue.path));
  } catch {
    return '      fix: the file could not be re-read, so no change is proposed';
  }
  const ct = resolveContentType(cfg, article.data, article.filePath);
  const changes = fixFor(issue, cfg, profile, ct, article, now);
  if (changes === null) {
    return '      fix: none that is honest — this needs a person to decide the value';
  }
  return `      fix (NOT applied): ${changes.map(changeLine).join('; ')}`;
}

async function toolAudit(base: Zer0Config, args: ToolArgs): Promise<string> {
  if (base.workspaceRoot === '') {
    return 'error: no workspace root — start the server in the folder you want audited';
  }

  const severity = argString(args, 'severity').toLowerCase();
  if (severity !== '' && !AUDIT_SEVERITIES.includes(severity)) {
    return `refused: severity must be one of ${AUDIT_SEVERITIES.join(', ')}`;
  }
  const rule = argString(args, 'rule');
  const prefix = argString(args, 'path').replace(/^\.\//, '');
  const withFixes = argBoolDefaultTrue(args, 'fixes');
  const limit = argCount(args, 'limit', 40, 1, 500);

  const io = auditIo(base.workspaceRoot);
  const platform = await detectPlatform(base.workspaceRoot, io, base.platform);
  const profile = platform.profile;
  // A repository that never registered a content folder still has content:
  // the resolved profile's roots fill the gap, exactly as the editor's own
  // audit does, so a sister site answers on the first call.
  const cfg = withPlatformDefaults(base, platform);

  const { pages, cache } = await buildIndex(cfg, undefined, undefined, profile);
  const blocks = await auditBlocks(pages);
  const schema: SiteSchema = await readSiteSchema(cfg.workspaceRoot, profile, io.read);
  const skipped = Object.keys(cache.skipped ?? {}).map((filePath) => relPath(cfg, filePath));
  const now = new Date();
  const audit = auditSite(cfg, profile, pages, skipped, schema, now, undefined, blocks);

  const matched = audit.issues.filter(
    (issue) =>
      (severity === '' || issue.severity === severity) &&
      (rule === '' || issue.rule === rule || issue.kind === rule) &&
      (prefix === '' || issue.path === prefix || issue.path.startsWith(`${prefix}/`)),
  );

  const lines: string[] = [
    `audit      : ${cfg.workspaceRoot}`,
    `platform   : ${profile.id}${profile.overlay === null ? '' : ` + ${profile.overlay}`} (${platform.source})`,
    `schema     : ${schema.source}${schema.path === null ? '' : ` (${schema.path})`}`,
    `scanned    : ${audit.scanned} file(s), ${audit.skipped.length} skipped as generated or vendored`,
    `findings   : ${audit.counts.error} error(s), ${audit.counts.warning} warning(s), ${audit.counts.info} note(s)`,
    `generated  : ${audit.generatedAt}`,
  ];

  // What "required" means depends entirely on which of these answered, so the
  // tool says it in words rather than leaving a model to infer authority.
  lines.push(
    '',
    schema.source === 'profile-default' || schema.source === 'none'
      ? 'This site declares no front-matter schema, so "required" here is the platform ' +
          "profile's own default, not a rule the repository wrote down."
      : `"required" here is what ${schema.source} declares; the platform profile fills the gaps.`,
  );

  if (audit.issues.length === 0) {
    lines.push('', 'No findings. Every page this site registers parses and carries what it must.');
    return lines.join('\n');
  }

  lines.push('', `by rule (${Object.keys(audit.byRule).length}):`);
  for (const [name, count] of Object.entries(audit.byRule).sort(
    ([leftId, left], [rightId, right]) => right - left || leftId.localeCompare(rightId),
  )) {
    const spec = AUDIT_RULE_SPECS[name as AuditIssue['rule']];
    lines.push(
      `  ${String(count).padStart(4)}  ${name}${spec === undefined ? '' : ` — ${spec.severity}, ${spec.what}`}`,
    );
  }

  if (matched.length === 0) {
    lines.push('', 'No finding matches that filter.');
    return lines.join('\n');
  }

  const shown = matched.slice(0, limit);
  lines.push(
    '',
    `findings (${shown.length} of ${matched.length}${matched.length === audit.issues.length ? '' : ` matched, ${audit.issues.length} total`}), grouped by rule:`,
  );

  const grouped = new Map<string, AuditIssue[]>();
  for (const issue of shown) {
    const bucket = grouped.get(issue.rule);
    if (bucket === undefined) {
      grouped.set(issue.rule, [issue]);
    } else {
      bucket.push(issue);
    }
  }

  for (const [name, group] of grouped) {
    const spec = AUDIT_RULE_SPECS[name as AuditIssue['rule']];
    lines.push('', `  ${name} (${group.length})${spec === undefined ? '' : ` — ${spec.what}`}`);
    for (const issue of group) {
      lines.push(
        `    ${issue.path}${issue.line === null ? '' : `:${issue.line}`} [${issue.severity}/${issue.lane}] ${issue.message}`,
      );
      if (issue.suggestion !== null) {
        lines.push(`      suggestion: ${issue.suggestion}`);
      }
      if (withFixes && issue.fixable) {
        lines.push(await proposedFix(cfg, profile, issue, now));
      }
    }
  }

  lines.push(
    '',
    'This tool wrote nothing and opened no socket. Every "fix" above is a proposal;',
    "applying one is the editor's audit.fix, which re-reads the file, re-runs the rule,",
    'shows a diff and asks a person.',
  );
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 14. zer0_harness_inventory — this repository's whole AI machinery
// ---------------------------------------------------------------------------

/** The two methods the pure harness readers take, over `node:fs`. */
function harnessIo(root: string): HarnessIo {
  return {
    list: async (rel) => {
      try {
        return await fs.readdir(path.resolve(root, rel));
      } catch {
        // No such directory is the normal answer, not an error: a repository
        // with no `.claude/` runs no roles, and that is a finding, not a fault.
        return [];
      }
    },
    read: async (rel) => {
      try {
        return await fs.readFile(path.resolve(root, rel), 'utf8');
      } catch {
        return undefined;
      }
    },
  };
}

/** Which slices of the inventory a caller may narrow to. */
const HARNESS_SECTIONS: readonly string[] = [
  'all',
  'agents',
  'skills',
  'workflows',
  'joins',
  'findings',
];

async function readInventoryFor(cfg: Zer0Config): Promise<HarnessInventory> {
  return readHarnessInventory(cfg.workspaceRoot, harnessIo(cfg.workspaceRoot), {
    ...DEFAULT_INVENTORY_OPTIONS,
    manifestPath: cfg.fleet.manifestPath,
    aiConfigPath: cfg.cms.aiConfigPath,
  });
}

/**
 * The harness as prose: the roles, the routines, the workflows by runner shape,
 * the join, and where the four disagree.
 *
 * Local files only. This process opens no socket, so the one thing it cannot
 * report — whether each `*_ENABLED` variable is actually set — is named as
 * unknown with the place that does know, exactly as `zer0_fleet_status` does.
 * Tokens are **names**: the manifest declares them, this tool repeats the
 * names, and nothing here reads a value.
 */
async function toolHarnessInventory(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  if (cfg.workspaceRoot === '') {
    return 'error: no workspace root — start the server in the repository you want read';
  }
  const section = argString(args, 'section').toLowerCase() || 'all';
  if (!HARNESS_SECTIONS.includes(section)) {
    return `refused: section must be one of ${HARNESS_SECTIONS.join(', ')}`;
  }
  const limit = argCount(args, 'limit', 40, 1, 500);
  const wants = (name: string): boolean => section === 'all' || section === name;

  const inventory = await readInventoryFor(cfg);
  const manifest = inventory.manifest.manifest;
  const lines: string[] = [
    `harness    : ${cfg.workspaceRoot}`,
    `read at    : ${inventory.readAt}`,
    `manifest   : ${cfg.fleet.manifestPath}${
      manifest === null ? ` — ${inventory.manifest.reason ?? 'absent'}` : ` (${manifest.repo}, ${manifest.specVersion})`
    }`,
    `summary    : ${describeHarnessInventory(inventory)}`,
    `ai config  : ${
      inventory.aiConfig === null
        ? `${cfg.cms.aiConfigPath} — absent, so the lanes inherit the runner's own default model`
        : `${inventory.aiConfig.path} — model ${inventory.aiConfig.model ?? '(unset)'}${
            inventory.aiConfig.fallbackModel === null ? '' : `, fallback ${inventory.aiConfig.fallbackModel}`
          }`
    }`,
    `guardrails : ${
      inventory.guardrailsDoc === null
        ? 'no shared quarantine doc — the agents cite no common rules for reading untrusted text'
        : `${inventory.guardrailsDoc.path}${inventory.guardrailsDoc.kit === null ? '' : ` (kit ${inventory.guardrailsDoc.kit})`}`
    }`,
    `metering   : ${
      inventory.ledger === null
        ? 'unmetered — this repository keeps no usage ledger. Unmetered is not free.'
        : `${inventory.ledger.path}, ${inventory.ledger.records} record(s), ${
            inventory.ledger.last7dUsd === null ? 'no 7-day total' : `$${inventory.ledger.last7dUsd.toFixed(2)} in the last 7 days`
          } (${inventory.ledger.unit})`
    }`,
  ];

  if (wants('agents')) {
    lines.push('', `agents (${inventory.agents.length}), from .claude/agents/:`);
    for (const agent of inventory.agents.slice(0, limit)) {
      lines.push(
        `  ${agent.name} — ${agent.description || '(no description)'}`,
        `    ${agent.path} · model ${agent.model ?? '(inherit)'} · dialect ${agent.dialect}` +
          `${agent.nameMatchesFile ? '' : ' · NAME DOES NOT MATCH THE FILENAME'}`,
        `    tools: ${agent.tools.length === 0 ? '(none declared)' : agent.tools.join(', ')}`,
      );
    }
    lines.push(...omitted(inventory.agents.length, limit));
  }

  if (wants('skills')) {
    lines.push('', `skills (${inventory.skills.length}), from .claude/skills/:`);
    for (const skill of inventory.skills.slice(0, limit)) {
      lines.push(`  ${skill.name} — ${skill.description || '(no description)'}`);
    }
    lines.push(...omitted(inventory.skills.length, limit));
  }

  if (wants('workflows')) {
    const ai = inventory.workflows.filter((workflow) => workflow.runnerShape !== 'none');
    lines.push(
      '',
      `workflows (${inventory.workflows.length}, of which ${ai.length} reach a model):`,
    );
    for (const workflow of inventory.workflows.slice(0, limit)) {
      lines.push(
        `  ${workflow.path} — ${workflow.name}`,
        `    runner ${workflow.runnerShape} · switches ${
          workflow.switches.length === 0 ? '(ungated)' : workflow.switches.join(', ')
        }${workflow.switchHost === null ? '' : ` (read by ${workflow.switchHost})`}` +
          ` · dispatch ${
            workflow.dispatchBypassesSwitch === null
              ? 'n/a'
              : workflow.dispatchBypassesSwitch
                ? 'BYPASSES the switch'
                : 'respects the switch'
          }`,
        `    schedule ${workflow.crons.length === 0 ? '(none)' : workflow.crons.join(' · ')}` +
          `${workflow.dormantCrons.length === 0 ? '' : ` · parked: ${workflow.dormantCrons.join(' · ')}`}` +
          ` · timeout ${workflow.timeoutMinutes === null ? 'NONE DECLARED' : `${workflow.timeoutMinutes}m`}`,
        `    secrets (names only): ${
          workflow.secrets.length === 0 ? '(none)' : workflow.secrets.join(', ')
        }`,
      );
    }
    lines.push(...omitted(inventory.workflows.length, limit));
  }

  if (wants('joins')) {
    lines.push('', `joins (${inventory.joins.length}) — workflow → lane, role, routine, switch:`);
    for (const join of inventory.joins.slice(0, limit)) {
      lines.push(
        `  ${join.workflowPath} → lane ${join.laneId ?? '(none declares it)'} · role ${
          join.agent ?? '(none)'
        } · skill ${join.skill ?? '(none)'} · switch ${join.switch ?? '(ungated)'}` +
          ` · tokens ${join.tokens.length === 0 ? '(none)' : join.tokens.join(', ')}` +
          ` · spend ${join.costUsd === null ? '(unmetered)' : `$${join.costUsd.toFixed(2)}`}`,
      );
    }
    lines.push(...omitted(inventory.joins.length, limit));
  }

  if (wants('findings')) {
    const errors = inventory.findings.filter((finding) => finding.severity === 'error').length;
    const warnings = inventory.findings.filter((finding) => finding.severity === 'warning').length;
    lines.push(
      '',
      `findings (${inventory.findings.length}: ${errors} error(s), ${warnings} warning(s)) — places two of this repository's own files say different things:`,
    );
    for (const finding of inventory.findings.slice(0, limit)) {
      lines.push(
        `  [${finding.severity}] ${finding.kind}${finding.path === null ? '' : ` ${finding.path}`}`,
        `    ${finding.message}`,
      );
    }
    lines.push(...omitted(inventory.findings.length, limit));
  }

  if (manifest !== null && manifest.tokens.length > 0 && section === 'all') {
    lines.push('', `tokens the manifest declares (${manifest.tokens.length}), names only:`);
    for (const token of manifest.tokens) {
      lines.push(
        `  ${token.name} — ${token.required ? 'required' : 'optional'}, scope ${
          token.scope || '(unspecified)'
        }${token.purpose === '' ? '' : `: ${token.purpose}`}`,
      );
    }
  }

  lines.push(
    '',
    'Read from local files only: no network, no spawn, nothing written. Switch VALUES are not',
    'here — they live in the repository’s Actions variables, and only the editor’s dashboard reads',
    'them, behind a person’s sign-in. Token and secret names are shown; no value is ever read.',
  );
  return lines.join('\n');
}

/** `… N more not listed` — or nothing, when there is nothing more. */
function omitted(total: number, limit: number): string[] {
  return total <= limit ? [] : [`  … ${total - limit} more not listed (raise "limit")`];
}

// ---------------------------------------------------------------------------
// 15/16 — a lane spec from tool arguments, and the plan it makes
// ---------------------------------------------------------------------------

const LANE_VERBS: readonly LaneKindVerb[] = [
  'create',
  'improve',
  'review',
  'scout',
  'triage',
  'fix',
  'audit',
];

/** Runner versions, not platform facts. The twin lives in `commands/harness.ts`. */
const SETUP_VERSIONS = { ruby: '3.3', node: '20', python: '3.12' } as const;

/**
 * Which runtime a generated lane sets up, read out of the platform profile's own
 * serve/build command rather than switched on the platform id — so the one
 * platform-specific fact stays where decision D12 put it.
 */
function laneSetupFor(profile: PlatformProfile): LaneSetup {
  const argv = [...(profile.commands.serve ?? []), ...(profile.commands.build ?? [])];
  const tool = argv.find((word) =>
    /^(bundle|gem|ruby|mkdocs|pip|python3?|npm|npx|node|yarn|pnpm)$/.test(word),
  );
  switch (tool) {
    case 'bundle':
    case 'gem':
    case 'ruby':
      return { ruby: SETUP_VERSIONS.ruby, node: null, python: null };
    case 'mkdocs':
    case 'pip':
    case 'python':
    case 'python3':
      return { ruby: null, node: null, python: SETUP_VERSIONS.python };
    case 'npm':
    case 'npx':
    case 'node':
    case 'yarn':
    case 'pnpm':
      return { ruby: null, node: SETUP_VERSIONS.node, python: null };
    default:
      return { ruby: null, node: null, python: null };
  }
}

/** `content-review` → `CONTENT_REVIEW_ENABLED`. The fleet's own naming, exactly. */
function defaultSwitchFor(laneId: string): string {
  const stem = laneId
    .trim()
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .toUpperCase();
  return stem === '' ? '' : `${stem}_ENABLED`;
}

/**
 * Where the vendored kit templates live, found by walking up from this module.
 *
 * Two layouts have to work: the shipped bundle at `<extension>/dist/mcp-server.js`
 * and the compiled test tree at `<repo>/out/mcp/tools.js`. Walking beats
 * hard-coding a depth, which is what `src/core/fleet/engines.ts` does for the
 * engines' own version and for the same reason.
 */
function templatesDir(): string | undefined {
  let dir = __dirname;
  for (let depth = 0; depth < 6; depth += 1) {
    const candidate = path.join(dir, TEMPLATE_FILES.aiLane);
    if (existsSync(candidate)) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return undefined;
    }
    dir = parent;
  }
  return undefined;
}

interface LaneTemplates {
  template: string;
  agentTemplate: string;
  kitVersion: string;
}

async function laneTemplates(): Promise<LaneTemplates | { refused: string }> {
  const root = templatesDir();
  if (root === undefined) {
    return {
      refused: `error: ${TEMPLATE_FILES.aiLane} is not installed beside this server, so no lane can be rendered`,
    };
  }
  try {
    const [template, agentTemplate, version] = await Promise.all([
      fs.readFile(path.join(root, TEMPLATE_FILES.aiLane), 'utf8'),
      fs.readFile(path.join(root, TEMPLATE_FILES.agent), 'utf8'),
      fs.readFile(path.join(root, TEMPLATE_FILES.version), 'utf8'),
    ]);
    const kitVersion = parseKitVersion(version);
    if (kitVersion === null) {
      return { refused: `error: ${TEMPLATE_FILES.version} declares no version` };
    }
    return { template, agentTemplate, kitVersion };
  } catch (error) {
    return { refused: `error: the lane templates could not be read — ${reason(error)}` };
  }
}

/** Everything a plan needs, read fresh from disk for this call. */
interface LanePlanContext {
  spec: LaneSpec;
  plan: ScaffoldPlan;
  manifestText: string | undefined;
  manifestRel: string;
  inventory: HarnessInventory;
}

/**
 * Build the spec from the call's arguments and plan it — with **no** self-audit.
 *
 * `planScaffold` takes the engines-backed audit as an injected `ctx.audit`, and
 * this process deliberately does not pass one: `src/core/harness/selfAudit.ts`
 * imports `@bamr87/fleet-engines`, and `dist/mcp-server.js` is built with an
 * empty bare-import allow-list. eslint bans the path from `src/mcp/**` for the
 * same reason. What the plan carries here is the house preflight, and the
 * answers say which they are rather than implying the fuller audit ran.
 */
async function planLane(
  cfg: Zer0Config,
  args: ToolArgs,
): Promise<LanePlanContext | { refused: string }> {
  const id = argString(args, 'id');
  if (id === '') {
    return { refused: 'refused: a lane needs an id — it becomes the workflow filename' };
  }
  const files = await laneTemplates();
  if ('refused' in files) {
    return files;
  }

  const io = harnessIo(cfg.workspaceRoot);
  const manifestRel = cfg.fleet.manifestPath;
  const [inventory, manifestText, platform] = await Promise.all([
    readInventoryFor(cfg),
    io.read(manifestRel),
    detectPlatform(cfg.workspaceRoot, auditIo(cfg.workspaceRoot), cfg.platform),
  ]);

  const verbArg = argString(args, 'verb');
  const verb: LaneKindVerb = LANE_VERBS.includes(verbArg as LaneKindVerb)
    ? (verbArg as LaneKindVerb)
    : 'create';
  const description = argString(args, 'description');
  const agent = argString(args, 'agent') || id;
  const skill = argString(args, 'skill');
  const switchName = argString(args, 'switch') || defaultSwitchFor(id);
  const cron = argString(args, 'cron');
  const model = argString(args, 'model');
  const tools = argString(args, 'tools')
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part !== '');
  const projectName =
    inventory.manifest.manifest?.repo ?? (path.basename(cfg.workspaceRoot) || 'this repository');

  const spec: LaneSpec = {
    id,
    kind: argString(args, 'kind') || 'content',
    verb,
    description,
    agent,
    skill: skill === '' ? null : skill,
    projectName,
    platform: platform.profile.id,
    switch: switchName === '' ? null : switchName,
    dispatchBypassesSwitch: args.dispatchBypassesSwitch !== false,
    cron: cron === '' ? null : cron,
    events: [],
    prompt: argString(args, 'prompt'),
    system:
      description === ''
        ? `You are the ${agent} agent for ${projectName}. Do exactly one unit of work, open one pull request, and never merge.`
        : `You are the ${agent} agent for ${projectName}. ${description}`,
    tools: tools.length === 0 ? ['Read'] : tools,
    mcp: null,
    model: model === '' ? null : model,
    maxTurns: null,
    setup: laneSetupFor(platform.profile),
    preRun: null,
    postRun: null,
    resultFile: argString(args, 'resultFile') || 'pr-result.txt',
    artifactPath: null,
    timeoutMinutes: argCount(args, 'timeoutMinutes', 20, 1, 360),
    cancelInProgress: false,
    continueOnError: false,
    permissions: { contents: 'write', 'pull-requests': 'write' },
    matrix: null,
    crossRepoCheckout: false,
    prHeadCheckout: false,
    modelPasses: 1,
    labels: [],
    branchPattern: null,
    kitVersion: files.kitVersion,
  };

  const plan = await planScaffold(spec, {
    template: files.template,
    agentTemplate: files.agentTemplate,
    manifestText,
    manifestRel,
    existing: (rel) => io.read(rel),
    // No `audit`. See this function's comment.
  });

  return { spec, plan, manifestText, manifestRel, inventory };
}

/** The findings that stop a lane being written. `error` and `fail` both count. */
function fatalFindings(plan: ScaffoldPlan): string[] {
  return plan.audit
    .filter((finding) => finding.severity === 'error' || finding.severity === 'fail')
    .map((finding) => `${finding.rule}: ${finding.message}`);
}

/** The plan's own prose: shape, reasons, findings, and the variable it omits. */
function planLines(ctx: LanePlanContext): string[] {
  const lines: string[] = [
    `lane       : ${ctx.spec.id} (${ctx.spec.kind}, ${ctx.spec.verb})`,
    `shape      : ${ctx.plan.shape}`,
    `agent      : ${ctx.spec.agent}${ctx.spec.skill === null ? '' : ` · skill ${ctx.spec.skill}`}`,
    `platform   : ${ctx.spec.platform} · kit ai-runner v${ctx.spec.kitVersion}`,
    `trigger    : ${
      ctx.spec.cron === null ? 'workflow_dispatch only' : `cron "${ctx.spec.cron}" plus workflow_dispatch`
    }`,
  ];
  if (ctx.plan.reasons.length > 0) {
    lines.push(
      ctx.plan.shape === 'bespoke'
        ? 'this console will NOT generate this lane:'
        : 'why this shape rather than the simplest one:',
      ...ctx.plan.reasons.map((why) => `  - ${why}`),
    );
  }
  if (ctx.plan.audit.length > 0) {
    lines.push('', `preflight (${ctx.plan.audit.length}):`);
    for (const finding of ctx.plan.audit) {
      lines.push(`  [${finding.severity}] ${finding.rule}: ${finding.message}`);
    }
  }
  lines.push(
    '',
    ctx.plan.switchToCreateLater === null
      ? 'kill switch: NONE — which is why the preflight above refuses this lane. Every loop in this'
        + ' fleet is off until somebody sets its own *_ENABLED variable.'
      : `kill switch: ${ctx.plan.switchToCreateLater} is NOT created by any tool here. Writing files a`
        + ' person reviews and arming a loop to run are different powers; only the first is on offer.',
  );
  return lines;
}

// ---------------------------------------------------------------------------
// 15. zer0_lane_preview — read-only
// ---------------------------------------------------------------------------

/**
 * Exactly what `zer0_lane_scaffold` would write, rendered and returned.
 *
 * Same `planScaffold` as the write, so the preview and the write cannot be
 * previews of two different questions — the property that makes a
 * plan-then-confirm flow worth having. Writes nothing: `planScaffold` has no
 * filesystem of its own, only the `existing` reader handed to it.
 */
async function toolLanePreview(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  if (cfg.workspaceRoot === '') {
    return 'error: no workspace root — start the server in the repository the lane belongs to';
  }
  const ctx = await planLane(cfg, args);
  if ('refused' in ctx) {
    return ctx.refused;
  }
  const lines = planLines(ctx);

  if (ctx.plan.files.length === 0) {
    lines.push(
      '',
      'Nothing would be written. That is the answer, not a failure: a lane the shared runner',
      'cannot express is a workflow for a person to write and review.',
    );
    return lines.join('\n');
  }

  for (const file of ctx.plan.files) {
    lines.push(
      '',
      `--- begin ${file.rel}${file.exists ? ' (ALREADY EXISTS — writing needs force=true)' : ' (new file)'} ---`,
      file.contents.replace(/\n+$/, ''),
      `--- end ${file.rel} ---`,
    );
  }

  if (ctx.plan.manifest === null) {
    lines.push(
      '',
      `manifest: ${ctx.manifestRel} is absent, so no lane entry would be appended. The workflow, the`,
      'agent and the skill are still the whole of the lane.',
    );
  } else {
    lines.push(
      '',
      `--- begin ${ctx.plan.manifest.rel} (appended before its \`tokens:\` block) ---`,
      renderManifestLane(ctx.spec).replace(/\n+$/, ''),
      `--- end ${ctx.plan.manifest.rel} ---`,
    );
  }

  lines.push(
    '',
    'This tool wrote nothing and opened no socket. The findings above are the house preflight only:',
    "the editor additionally runs the fleet's own fifteen-rule workflow audit over the same files,",
    'which this process cannot reach by design.',
  );
  return lines.join('\n');
}

// ---------------------------------------------------------------------------
// 16. zer0_lane_scaffold — double-gated, and it creates no variable
// ---------------------------------------------------------------------------

/**
 * Write one lane's files into the repository this server is rooted in.
 *
 * **Gated three times, and each gate refuses on its own with its own prose.**
 * The environment flag (`ZER0_CMS_MCP_ALLOW_SCAFFOLD`, injected by the editor
 * from the settings layer, in a trusted workspace only) says whether this
 * process may write a lane at all. `confirm: true` says whether *this call*
 * meant to. `evaluateFleetGates('scaffold', …)` says whether this particular
 * lane may land here. `zer0_publish` is the shape being copied, deliberately.
 *
 * `force` overrides exactly one refusal — "a file is already there" — and
 * nothing else. Not the environment flag, not `confirm`, not a lane the manifest
 * already declares, not a variable another lane claims, not a lane the
 * generators refuse, not a failing preflight, and never a `factory--*` path or
 * anything outside the workspace root. That is `publishPreview`'s own posture:
 * the seam exists because a caller who has read the plan may overrule a
 * *finding*, and nothing reachable from a keystroke passes it — the editor's
 * `lane.scaffold` has no `force` at all.
 *
 * It creates **no repository variable**. The lane it writes is inert until a
 * person makes its `*_ENABLED` variable themselves, and this process could not
 * make one if it wanted to: it opens no socket.
 */
async function toolLaneScaffold(cfg: Zer0Config, args: ToolArgs): Promise<string> {
  // Gate one: the environment. Names the variable that has to change.
  if (!scaffoldEnabled(process.env)) {
    return (
      'scaffolding is disabled. This tool writes a workflow file, an agent role and a skill stub ' +
      `into the repository. To enable it, set ${SCAFFOLD_ENV_VAR}=1 in the server environment ` +
      '(the editor sets it from "zer0Cms.fleet.scaffoldAllow", in a trusted workspace only). ' +
      'Until then use zer0_lane_preview, which renders every byte and writes none of them.'
    );
  }
  // Gate two: the call. Names the alternative.
  if (args.confirm !== true) {
    return (
      'refused: pass confirm=true to write the lane. Run zer0_lane_preview first and read every ' +
      'line — this writes those exact files into the working tree for a person to commit.'
    );
  }
  if (cfg.workspaceRoot === '') {
    return 'error: no workspace root — start the server in the repository the lane belongs to';
  }

  const ctx = await planLane(cfg, args);
  if ('refused' in ctx) {
    return ctx.refused;
  }
  const force = argBool(args, 'force');

  // Gate three: the fleet gate, in its own order, in its own words.
  const input: FleetGateInput = {
    workspaceRoot: cfg.workspaceRoot,
    dispatchAllow: false,
    hasCredential: false,
    manifest: ctx.inventory.manifest.manifest,
    ...(ctx.inventory.manifest.reason === undefined
      ? {}
      : { manifestReason: ctx.inventory.manifest.reason }),
    laneId: ctx.spec.id,
    // One bit from the editor answers both settings-layer questions.
    // `ZER0_CMS_MCP_ALLOW_SCAFFOLD` is injected only when `zer0Cms.fleet.enabled`
    // is on for that folder *and* `zer0Cms.fleet.scaffoldAllow` is set there in a
    // person's own settings, so by the time control reaches here — gate one
    // having already refused otherwise, in better words than the gate's — both
    // are true. This is `loadServerConfig` folding the publish flag into
    // `governance.publishAllow`: one switch, not two that can disagree.
    enabled: true,
    scaffoldAllow: true,
    scaffold: scaffoldGateFacts(ctx.spec, ctx.plan, ctx.manifestText),
  };
  const blockers = evaluateFleetGates('scaffold', input).filter(
    // The one blocker `force` may override, and the only one.
    (blocker) => !(force && blocker.kind === 'workflowFileExists'),
  );
  if (blockers.length > 0) {
    return ['blocked:', ...blockers.map((blocker) => `  ${blocker.message}`)].join('\n');
  }

  // The house rules. A lane with no kill switch lands here, and this is the one
  // refusal the whole tool exists to make.
  const fatal = fatalFindings(ctx.plan);
  if (fatal.length > 0) {
    return ['blocked: the lane does not pass its own preflight:', ...fatal.map((f) => `  ${f}`)].join(
      '\n',
    );
  }
  if (ctx.plan.files.length === 0) {
    return 'blocked: the plan would write nothing';
  }

  for (const file of ctx.plan.files) {
    if (/(^|\/)factory--/.test(file.rel)) {
      return `refused: ${file.rel} is GitFactory's compiled output — this console does not own the compiler's files`;
    }
    if (!insideWorkspace(cfg.workspaceRoot, path.resolve(cfg.workspaceRoot, file.rel))) {
      return `refused: ${file.rel} resolves outside ${cfg.workspaceRoot}`;
    }
    if (file.exists && !force) {
      return `refused: ${file.rel} already exists — rename the lane, or pass force=true to overwrite it`;
    }
  }

  const written: string[] = [];
  for (const file of ctx.plan.files) {
    const abs = path.resolve(cfg.workspaceRoot, file.rel);
    try {
      await fs.mkdir(path.dirname(abs), { recursive: true });
      // Exclusive unless a caller asked for an overwrite: a file that appeared
      // between the plan and the write costs a refusal, never somebody's lane.
      await fs.writeFile(abs, file.contents, { encoding: 'utf8', ...(force ? {} : { flag: 'wx' }) });
    } catch (error) {
      return `error: ${file.rel} could not be written — ${reason(error)}. Already written: ${
        written.join(', ') || 'nothing'
      }`;
    }
    written.push(file.rel);
  }

  if (ctx.plan.manifest !== null) {
    const manifestAbs = absPath(cfg, ctx.plan.manifest.rel);
    try {
      // The manifest is rewritten rather than created, so its bytes are re-read
      // and compared with the ones the plan was built from. A manifest that
      // moved under us is a refusal, not a merge.
      const current = await fs.readFile(manifestAbs, 'utf8');
      if (current !== ctx.plan.manifest.before) {
        return `error: ${ctx.plan.manifest.rel} changed since the plan was built — ${written.join(', ')} were written; call again to append the lane entry`;
      }
      await fs.writeFile(manifestAbs, ctx.plan.manifest.after, 'utf8');
      written.push(ctx.plan.manifest.rel);
    } catch (error) {
      return `error: ${ctx.plan.manifest.rel} could not be updated — ${reason(error)}. The lane files were written.`;
    }
  }

  return [
    `wrote ${written.length} file(s) for lane "${ctx.spec.id}" (${ctx.plan.shape}):`,
    ...written.map((rel) => `  ${rel}`),
    '',
    ctx.plan.switchToCreateLater === null
      ? 'No kill switch was declared, so the lane is inert and unstoppable in equal measure — fix that before committing.'
      : `NOT created: the repository variable ${ctx.plan.switchToCreateLater}. The lane will not run until a` +
        ' person creates it. This tool opens no socket and could not have created it.',
    'Nothing was committed, pushed or merged. A person reviews these files and commits them.',
  ].join('\n');
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

/**
 * The fourteen fields a lane is described with, as JSON Schema. Shared by the
 * preview and the write, so a caller that can render a lane can write the same
 * one without re-learning the vocabulary.
 *
 * The twin of `LANE_FIELDS` in `src/commands/harness.ts`, which is the editor's
 * staged form over the same fourteen names in the same order. Two copies on
 * purpose: this process cannot import the command layer (it would drag `vscode`
 * into a bundle whose whole point is that it cannot) and the editor cannot
 * import this one. They move together — edit both in one commit.
 */
const LANE_PROPERTIES: Record<string, unknown> = {
  id: {
    type: 'string',
    description:
      'the lane id: becomes .github/workflows/<id>.yml, the concurrency group and the metering role',
  },
  kind: { type: 'string', description: "the manifest's own vocabulary, e.g. content, maintenance" },
  verb: { type: 'string', enum: [...LANE_VERBS], description: 'what the lane does, in one word' },
  description: { type: 'string', description: "one sentence; becomes the file's opening comment" },
  agent: { type: 'string', description: 'the role, resolved as .claude/agents/<name>.md; defaults to the id' },
  skill: { type: 'string', description: 'optional routine; a stub is written at .claude/skills/<name>/SKILL.md' },
  switch: {
    type: 'string',
    description:
      'the *_ENABLED repository variable the lane idles behind; derived from the id when omitted. Never created here.',
  },
  cron: {
    type: 'string',
    description:
      'five fields, and never minute :00. Required in practice: the preflight refuses a lane with no trigger at all.',
  },
  prompt: { type: 'string', description: 'what the agent is told to do; name the result file in it' },
  tools: { type: 'string', description: 'comma-separated, least privilege, e.g. "Read,Grep,Glob"' },
  resultFile: { type: 'string', description: 'the file the lane asserts is non-empty; default pr-result.txt' },
  dispatchBypassesSwitch: {
    type: 'boolean',
    description: 'default true, as the shared lane does. False needs the gate written out by hand.',
  },
  timeoutMinutes: { type: 'integer', minimum: 1, maximum: 360, description: 'default 20' },
  model: { type: 'string', description: 'omit to inherit whatever the repository already agrees on' },
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
    name: 'zer0_ingest',
    description:
      'Join a platform export of post statistics onto content paths through the ledger and ' +
      'store them in .cms/distribution/performance.json — the input the catering worklist ' +
      "ranks on. Aggregate counts only; nothing about who engaged is read or kept.",
    inputSchema: {
      type: 'object',
      properties: {
        path: {
          type: 'string',
          description:
            'JSON file of statistics keyed by post id, either bare or wrapped in "posts"',
        },
        write: { type: 'boolean', description: 'write the file (default true)' },
      },
      required: ['path'],
    },
    handler: toolIngest,
  },
  {
    name: 'zer0_portfolio',
    description:
      'The published track record: how much, how often, the streak, and which collections ' +
      'it came from. Computed from the ledger, so it is meaningful before any statistics exist.',
    inputSchema: { type: 'object', properties: {} },
    handler: toolPortfolio,
  },
  {
    name: 'zer0_media',
    description:
      'Which distributable pages have a preview image and which do not, with the ' +
      'zer0-image-generator command for each gap. Reuses what the site already produced; ' +
      'generates nothing.',
    inputSchema: {
      type: 'object',
      properties: {
        limit: { type: 'number', description: 'pages to check (default 50, max 500)' },
      },
    },
    handler: toolMedia,
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
  {
    name: 'zer0_fleet_status',
    description:
      "This repository's AI fleet as its local fleet.manifest.yml declares it: each lane's " +
      'id, kind, harness, workflow, triggers, switch variable, tokens and guardrails. Reads ' +
      'the file only — no network — so switch state is reported as unknown; the dashboard ' +
      'reads it behind a sign-in. Read-only.',
    inputSchema: { type: 'object', properties: {} },
    handler: toolFleetStatus,
  },
  {
    name: 'zer0_audit',
    description:
      "Audit every page's front matter against the site's own schema — or, when it declares " +
      "none, the platform profile's defaults — and report the findings grouped by rule, with " +
      'the change set that would repair each fixable one DESCRIBED but never applied. ' +
      'Read-only: writes nothing, spawns nothing, no network.',
    inputSchema: {
      type: 'object',
      properties: {
        rule: {
          type: 'string',
          description: 'restrict to one rule id, e.g. "missing-key" or "missing-key:date"',
        },
        severity: {
          type: 'string',
          enum: [...AUDIT_SEVERITIES],
          description: 'restrict to one severity',
        },
        path: {
          type: 'string',
          description: 'restrict to one workspace-relative file or directory prefix',
        },
        fixes: {
          type: 'boolean',
          description: 'describe the proposed change set for fixable findings (default true)',
        },
        limit: { type: 'integer', minimum: 1, maximum: 500, description: 'default 40' },
      },
    },
    handler: toolAudit,
  },
  {
    name: 'zer0_harness_inventory',
    description:
      "This repository's whole AI harness, read from its own files and joined: the roles under " +
      '.claude/agents/, the routines under .claude/skills/, every workflow with the way it reaches ' +
      'a model, the manifest lanes, the *_ENABLED switches, the token NAMES each lane spends, the ' +
      'usage ledger, and every place two of those files disagree. Local files only — no network, ' +
      'no spawn, nothing written, and no secret value is ever read.',
    inputSchema: {
      type: 'object',
      properties: {
        section: {
          type: 'string',
          enum: [...HARNESS_SECTIONS],
          description: 'narrow to one slice; default "all"',
        },
        limit: { type: 'integer', minimum: 1, maximum: 500, description: 'rows per slice, default 40' },
      },
    },
    handler: toolHarnessInventory,
  },
  {
    name: 'zer0_lane_preview',
    description:
      'Render exactly what generating a new AI lane would write — the workflow file, the agent ' +
      'role, the skill stub and the manifest entry — with nothing written. Same planner as ' +
      'zer0_lane_scaffold, so this cannot be a preview of a different question. Reports the shape ' +
      'the lane fits, why, the house preflight findings, and the *_ENABLED variable that no tool ' +
      'here creates. Read-only.',
    inputSchema: {
      type: 'object',
      properties: LANE_PROPERTIES,
      required: ['id'],
    },
    handler: toolLanePreview,
  },
  {
    name: 'zer0_lane_scaffold',
    description:
      "Write a new AI lane's files into this repository: a workflow, an agent role, a skill stub " +
      'and the manifest entry. DOUBLE-GATED — needs ZER0_CMS_MCP_ALLOW_SCAFFOLD in the server ' +
      'environment AND confirm=true in the call — and refuses a lane with no kill switch, a lane ' +
      'the manifest already declares, a file that is already there, or a lane the shared runner ' +
      'cannot express. It creates NO repository variable: the lane it writes is inert until a ' +
      'person makes its *_ENABLED variable themselves. Run zer0_lane_preview first.',
    inputSchema: {
      type: 'object',
      properties: {
        ...LANE_PROPERTIES,
        confirm: {
          type: 'boolean',
          description: 'required: true. Without it this tool refuses and writes nothing.',
        },
        force: {
          type: 'boolean',
          description:
            'overwrite a file that is already there. Overrides nothing else — not the environment ' +
            'gate, not confirm, not a duplicate lane id, not a failing preflight.',
        },
      },
      required: ['id', 'confirm'],
    },
    handler: toolLaneScaffold,
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
  'engine execution is disabled',
  'scaffolding is disabled',
];

export function isErrorText(text: string): boolean {
  const lowered = text.trimStart().toLowerCase();
  return ERROR_PREFIXES.some((prefix) => lowered.startsWith(prefix));
}
