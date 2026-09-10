/**
 * `readHarnessInventory` — one repository's whole AI harness, read from the
 * files on disk and joined.
 *
 * This is the module the Harness tab, the `zer0_harness_inventory` MCP tool and
 * the lane generator's pre-flight all call. It reads seven kinds of artefact —
 * the manifest, the workflows, the agents, the skills, `_data/ai.yml`, the
 * shared guardrails doc, and the usage ledger — and hands back one value whose
 * `joins` say what belongs to what and whose `findings` say where they disagree.
 *
 * ## Injected I/O, and only two methods
 *
 * `HarnessIo` (declared in `agents.ts`) is `list` and `read`, both
 * repository-relative. Anything that needs more than "what is in this directory"
 * and "what does this file say" is doing something a pure reader should not be
 * doing. The same code therefore serves the extension host, the bundled MCP
 * server, and a test over a fixture directory — and none of them can make it
 * write, spawn, or open a socket.
 *
 * `root` is echoed back and never joined onto anything: every path this function
 * speaks is repository-relative, exactly as the manifest's `implementation`
 * field and the engines' workflow paths use them.
 *
 * ## An empty manifest from a non-empty file is a finding, not an absence
 *
 * Four of the seven committed `fleet.manifest.yml` files in this fleet are not
 * valid YAML: `wtd fleet adopt` wraps a quoted scalar at column 80 and continues
 * it at column 0, outside the block's indentation. The `yaml` package throws on
 * that, and `@bamr87/fleet-engines`' parser answers with an **empty** manifest
 * reporting **zero** skipped lanes — so a caller cannot even tell it failed.
 *
 * This repository's own tolerant reader (`src/core/fleet/manifest.ts`) parses all
 * seven, which is why it is the one used here. But the posture matters beyond
 * the parser: a manifest file that exists and yields no lanes is reported as
 * `{ manifest: null, reason }`, and the reason is carried through. "This
 * repository has no lanes" and "this repository's manifest would not parse" are
 * different sentences and the console must never say the first when it means the
 * second.
 */

import { parseFleetManifest, type ParsedFleetManifest } from '../fleet/manifest';
import type { HarnessInventory } from '../shared/types';
import { AGENTS_DIR, readAgents, type HarnessIo } from './agents';
import { AI_CONFIG_PATH, readAiConfig } from './aiConfig';
import {
  agentNameFindings,
  joinHarness,
  manifestDriftFindings,
  orphanSkillFindings,
  sortFindings,
} from './joins';
import { LEDGER_PATH, LEDGER_SUMMARY_PATH, readLedger } from './ledger';
import { SHARED_SKILL_DIR, SKILLS_DIR, readSkills } from './skills';
import { WORKFLOWS_DIR, readWorkflows } from './workflows';

/** The guardrails every agent in the fleet cites for reading untrusted text. */
export const QUARANTINE_PATH = `${SKILLS_DIR}/${SHARED_SKILL_DIR}/quarantine.md`;

/** Where each artefact lives. Every one is a setting somewhere, never a literal. */
export interface HarnessInventoryOptions {
  /** Workspace-relative path of `fleet.manifest.yml`. */
  manifestPath: string;
  /** Workspace-relative path of `_data/ai.yml` (`zer0Cms.cms.aiConfigPath`). */
  aiConfigPath: string;
  agentsDir?: string;
  skillsDir?: string;
  workflowsDir?: string;
  ledgerPath?: string;
  ledgerSummaryPath?: string;
  /** Epoch milliseconds for `readAt`. Injected so a test is deterministic. */
  now?: number;
}

/** The defaults, so a caller with nothing to say can pass `{}`-ish. */
export const DEFAULT_INVENTORY_OPTIONS: HarnessInventoryOptions = {
  manifestPath: 'fleet.manifest.yml',
  aiConfigPath: AI_CONFIG_PATH,
  agentsDir: AGENTS_DIR,
  skillsDir: SKILLS_DIR,
  workflowsDir: WORKFLOWS_DIR,
  ledgerPath: LEDGER_PATH,
  ledgerSummaryPath: LEDGER_SUMMARY_PATH,
};

/**
 * Read the manifest, distinguishing "no file" from "a file that would not
 * parse". `readFleetManifest` reads from disk with `fs`; this reader goes
 * through the injected I/O instead so the MCP server and a fixture test use the
 * same path the editor does.
 */
async function readManifest(io: HarnessIo, rel: string): Promise<ParsedFleetManifest> {
  const text = await io.read(rel);
  return text === undefined ? { manifest: null, reason: `not found: ${rel}` } : parseFleetManifest(text);
}

/**
 * Everything a repository says about its own AI harness.
 *
 * Nothing here throws: a repository with no `.claude/`, no workflows, no
 * manifest and no ledger is a normal repository and yields an inventory of empty
 * lists, `null` ledger and one honest `reason`. That is exactly the state
 * bash-365.com is in — four real AI workflows and nothing declaring them — and
 * the most useful screen this console can put in front of somebody who has not
 * adopted a manifest yet.
 */
export async function readHarnessInventory(
  root: string,
  io: HarnessIo,
  opts: HarnessInventoryOptions,
): Promise<HarnessInventory> {
  const agentsDir = opts.agentsDir ?? AGENTS_DIR;
  const skillsDir = opts.skillsDir ?? SKILLS_DIR;
  const workflowsDir = opts.workflowsDir ?? WORKFLOWS_DIR;

  const [manifest, workflows, agents, skillsRead, aiConfig, ledger, skillDirs, quarantine] =
    await Promise.all([
      readManifest(io, opts.manifestPath),
      readWorkflows(io, workflowsDir),
      readAgents(io, agentsDir),
      readSkills(io, skillsDir),
      readAiConfig(io, opts.aiConfigPath),
      readLedger(io, opts.ledgerPath ?? LEDGER_PATH, opts.ledgerSummaryPath ?? LEDGER_SUMMARY_PATH),
      io.list(skillsDir),
      io.read(`${skillsDir}/${SHARED_SKILL_DIR}/quarantine.md`),
    ]);

  // The workflow text is read a second time only because the drift comparison
  // re-derives a lane from the same bytes, and the token-chain and metering
  // rules read command lines the record does not carry. Keeping the sources in
  // one map here means `scanWorkflow` stays a projection rather than growing a
  // `raw` field nothing else wants.
  const sources: Record<string, string> = {};
  for (const workflow of workflows) {
    const text = await io.read(workflow.path);
    if (text !== undefined) {
      sources[workflow.path] = text;
    }
  }

  const joined = joinHarness({
    manifest: manifest.manifest,
    workflows,
    agents,
    skills: skillsRead.skills,
    ledger,
    hasSkillsDir: skillDirs.length > 0,
    sources,
  });

  const findings = sortFindings([
    ...joined.findings,
    ...agentNameFindings(agents),
    ...manifestDriftFindings(manifest.manifest, workflows, sources),
    ...orphanSkillFindings(skillsRead.skills, workflows, agents, sources),
  ]);

  return {
    root,
    readAt: new Date(opts.now ?? Date.now()).toISOString(),
    manifest,
    workflows,
    agents,
    skills: skillsRead.skills,
    aiConfig,
    guardrailsDoc:
      quarantine === undefined
        ? null
        : { path: QUARANTINE_PATH, kit: kitStampOf(quarantine) },
    ledger,
    joins: joined.joins,
    findings,
    skillCount: skillsRead.counts,
  };
}

/** `<!-- kit: agent-context v0.4.0 -->` → `agent-context v0.4.0`. */
function kitStampOf(text: string): string | null {
  const match = /<!--\s*kit:\s*([^\n>]+?)\s*-->/.exec(text);
  return match?.[1] ?? null;
}

/**
 * A one-line count of what the inventory found, for a status bar or a log. It
 * names what is absent as absent rather than as zero — `no manifest` is a
 * different sentence from `0 lanes`.
 */
export function describeHarnessInventory(inventory: HarnessInventory): string {
  const lanes =
    inventory.manifest.manifest === null
      ? `no manifest (${inventory.manifest.reason})`
      : `${inventory.manifest.manifest.lanes.length} lanes`;
  const errors = inventory.findings.filter((f) => f.severity === 'error').length;
  const warnings = inventory.findings.filter((f) => f.severity === 'warning').length;
  return (
    `${lanes} · ${inventory.workflows.length} workflows · ${inventory.agents.length} agents · ` +
    `${inventory.skills.length} skills · ${inventory.ledger === null ? 'unmetered' : 'metered'} · ` +
    `${errors} errors, ${warnings} warnings`
  );
}
