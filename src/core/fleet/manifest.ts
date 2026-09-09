/**
 * `fleet.manifest.yml` — this repository's AI fleet, in the shared `fleet/v1`
 * vocabulary (bamr87/wtd `docs/FLEET-SPEC.md`), read and coerced into the
 * `FleetManifest` shape declared in `shared/types.ts`.
 *
 * The manifest is untrusted input in exactly the sense `zer0.json` and the
 * `.cms/` index are: it is written by a tool (`wtd fleet adopt`), edited by
 * hand, and committed. So every field is coerced rather than cast, the way
 * `contract/contract.ts` does it — an unknown harness becomes `none`, an
 * unknown trigger kind is dropped, a missing list is `[]`, a guardrail the
 * manifest did not mention is `null` rather than `false`. A malformed manifest
 * yields a well-typed value, never a `TypeError` three modules away from the
 * bad byte.
 *
 * The one thing that is refused rather than coerced is the spec version.
 * A file with no `spec_version`, or one this reader does not speak, is
 * reported as `{ manifest: null, reason }` — the Fleet console must say "this
 * is not a manifest I understand" rather than render an empty table and let
 * somebody dispatch against it.
 *
 * Parsing goes through `parseYamlSubset`, the same hand-rolled reader front
 * matter uses (decision D3: zero runtime dependencies). The manifest's wrapped
 * `summary:` is why that parser learned to fold plain-scalar continuations.
 */

import * as fs from 'node:fs/promises';
import * as path from 'node:path';

import { parseYamlSubset } from '../content/frontmatter';
import {
  FLEET_HARNESSES,
  FLEET_TRIGGER_KINDS,
  type FleetGuardrails,
  type FleetHarness,
  type FleetLane,
  type FleetManifest,
  type FleetProvenance,
  type FleetToken,
  type FleetTrigger,
  type FleetTriggerKind,
} from '../shared/types';

/** The one spec version this reader speaks. */
export const FLEET_SPEC_VERSION = 'fleet/v1';

/** Conventional name of the manifest at a repository root. */
export const FLEET_MANIFEST_FILE = 'fleet.manifest.yml';

/** A parsed manifest, or the reason there is none. Exactly one of the two. */
export type ParsedFleetManifest =
  | { manifest: FleetManifest; reason?: undefined }
  | { manifest: null; reason: string };

// ---------------------------------------------------------------------------
// Coercion — the boundary where manifest YAML becomes typed domain values
// ---------------------------------------------------------------------------

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asText(value: unknown): string {
  return value === undefined || value === null ? '' : String(value).trim();
}

function asTextOrNull(value: unknown): string | null {
  const text = asText(value);
  return text === '' ? null : text;
}

/** `null` is meaningful for a guardrail: "the manifest did not say". */
function asBoolOrNull(value: unknown): boolean | null {
  if (typeof value === 'boolean') {
    return value;
  }
  if (value === undefined || value === null) {
    return null;
  }
  const text = asText(value).toLowerCase();
  return text === 'true' ? true : text === 'false' ? false : null;
}

function asBool(value: unknown, fallback: boolean): boolean {
  return asBoolOrNull(value) ?? fallback;
}

function asMember<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  const text = asText(value);
  return (allowed as readonly string[]).includes(text) ? (text as T) : fallback;
}

/**
 * A list of names. Entries may be bare strings or objects carrying `name` /
 * `id` — the spec allows `agents:` and `skills:` either way. Anything else is
 * dropped, and a lone scalar reads as a one-element list.
 */
function asNameList(value: unknown): string[] {
  const items = Array.isArray(value) ? value : value === undefined || value === null ? [] : [value];
  const names: string[] = [];
  for (const item of items) {
    const record = asRecord(item);
    const name = record === undefined ? asText(item) : asText(record.name ?? record.id);
    if (name !== '') {
      names.push(name);
    }
  }
  return names;
}

function coerceTrigger(raw: unknown): FleetTrigger | undefined {
  const entry = asRecord(raw);
  if (entry === undefined) {
    return undefined;
  }
  const kind = asText(entry.kind);
  if (!(FLEET_TRIGGER_KINDS as readonly string[]).includes(kind)) {
    // A trigger kind the spec does not name is not "something like an event";
    // it is unknown, and a lane must not be reported dispatchable on the
    // strength of it.
    return undefined;
  }
  return {
    kind: kind as FleetTriggerKind,
    cron: kind === 'schedule' ? asTextOrNull(entry.cron) : null,
    events: kind === 'event' ? asNameList(entry.events) : [],
  };
}

function coerceTriggers(raw: unknown): FleetTrigger[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map(coerceTrigger).filter((t): t is FleetTrigger => t !== undefined);
}

function coerceGuardrails(raw: unknown): FleetGuardrails {
  const entry = asRecord(raw) ?? {};
  return {
    neverMerges: asBoolOrNull(entry.never_merges),
    opensPullRequests: asBoolOrNull(entry.opens_pull_requests),
    writesDirectlyToDefaultBranch: asBoolOrNull(entry.writes_directly_to_default_branch),
    writablePaths: asNameList(entry.writable_paths),
  };
}

/** A lane with no `id` is not a lane; everything else is defaulted. */
function coerceLane(raw: unknown): FleetLane | undefined {
  const entry = asRecord(raw);
  if (entry === undefined) {
    return undefined;
  }
  const id = asText(entry.id);
  if (id === '') {
    return undefined;
  }
  return {
    id,
    kind: asText(entry.kind) || 'other',
    harness: asMember<FleetHarness>(entry.harness, FLEET_HARNESSES, 'none'),
    implementation: asText(entry.implementation),
    description: asText(entry.description) || id,
    triggers: coerceTriggers(entry.triggers),
    switch: asTextOrNull(entry.switch),
    usesTokens: asNameList(entry.uses_tokens),
    guardrails: coerceGuardrails(entry.guardrails),
  };
}

function coerceLanes(raw: unknown): FleetLane[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map(coerceLane).filter((lane): lane is FleetLane => lane !== undefined);
}

function coerceToken(raw: unknown): FleetToken | undefined {
  const entry = asRecord(raw);
  if (entry === undefined) {
    return undefined;
  }
  const name = asText(entry.name);
  if (name === '') {
    return undefined;
  }
  return {
    name,
    scope: asText(entry.scope),
    required: asBool(entry.required, false),
    purpose: asText(entry.purpose),
    usedBy: asNameList(entry.used_by),
  };
}

function coerceTokens(raw: unknown): FleetToken[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map(coerceToken).filter((token): token is FleetToken => token !== undefined);
}

/**
 * Coerce an already-parsed document. Refuses only a missing or foreign
 * `spec_version`; everything else degrades field by field.
 */
export function coerceFleetManifest(raw: unknown): ParsedFleetManifest {
  const doc = asRecord(raw);
  if (doc === undefined) {
    return { manifest: null, reason: 'the manifest is not a YAML mapping' };
  }
  const specVersion = asText(doc.spec_version);
  if (specVersion === '') {
    return { manifest: null, reason: 'the manifest declares no spec_version' };
  }
  if (specVersion !== FLEET_SPEC_VERSION) {
    return {
      manifest: null,
      reason: `spec_version "${specVersion}" is not ${FLEET_SPEC_VERSION}`,
    };
  }
  return {
    manifest: {
      specVersion,
      repo: asText(doc.repo),
      provenance: asMember<FleetProvenance>(doc.provenance, ['declared', 'derived'], 'unknown'),
      summary: asText(doc.summary),
      lanes: coerceLanes(doc.lanes),
      tokens: coerceTokens(doc.tokens),
      metering: asRecord(doc.metering) ?? {},
      agents: asNameList(doc.agents),
      skills: asNameList(doc.skills),
    },
  };
}

/** Parse manifest text. Never throws: the YAML reader is tolerant by design. */
export function parseFleetManifest(text: string): ParsedFleetManifest {
  return coerceFleetManifest(parseYamlSubset(text));
}

/**
 * Read and parse a manifest from disk. A missing file is reported, not thrown
 * — a repository without a fleet is a normal state, exactly like a repository
 * without a `.cms/` (decision D9).
 */
export async function readFleetManifest(filePath: string): Promise<ParsedFleetManifest> {
  let text: string;
  try {
    text = await fs.readFile(filePath, 'utf8');
  } catch {
    return { manifest: null, reason: `not found: ${path.basename(filePath)}` };
  }
  return parseFleetManifest(text);
}

// ---------------------------------------------------------------------------
// Reading a manifest
// ---------------------------------------------------------------------------

export function laneById(manifest: FleetManifest, id: string): FleetLane | undefined {
  const wanted = id.trim();
  return manifest.lanes.find((lane) => lane.id === wanted);
}

/** `true` when the lane declares a `workflow_dispatch` trigger. */
export function isDispatchable(lane: FleetLane): boolean {
  return lane.implementation !== '' && lane.triggers.some((t) => t.kind === 'dispatch');
}

/**
 * The workflow file name GitHub's API addresses a workflow by — the basename
 * of `implementation`. Empty when the lane names no workflow.
 */
export function workflowFileOf(lane: FleetLane): string {
  return lane.implementation === '' ? '' : path.posix.basename(lane.implementation);
}

/** `schedule 0 6 * * 1 · dispatch · event pull_request` — or `(none)`. */
export function describeTriggers(triggers: readonly FleetTrigger[]): string {
  if (triggers.length === 0) {
    return '(none)';
  }
  return triggers
    .map((t) => {
      if (t.kind === 'schedule') {
        return t.cron === null ? 'schedule' : `schedule ${t.cron}`;
      }
      if (t.kind === 'event') {
        return t.events.length === 0 ? 'event' : `event ${t.events.join(', ')}`;
      }
      return 'dispatch';
    })
    .join(' · ');
}

/** The guardrails as one line, naming only what the manifest actually said. */
export function describeGuardrails(guardrails: FleetGuardrails): string {
  const parts: string[] = [];
  if (guardrails.neverMerges !== null) {
    parts.push(guardrails.neverMerges ? 'never merges' : 'MAY MERGE');
  }
  if (guardrails.opensPullRequests !== null) {
    parts.push(guardrails.opensPullRequests ? 'opens pull requests' : 'opens no pull requests');
  }
  if (guardrails.writesDirectlyToDefaultBranch !== null) {
    parts.push(
      guardrails.writesDirectlyToDefaultBranch
        ? 'WRITES TO THE DEFAULT BRANCH'
        : 'never writes to the default branch',
    );
  }
  if (guardrails.writablePaths.length > 0) {
    parts.push(`writes only under ${guardrails.writablePaths.join(', ')}`);
  }
  return parts.length === 0 ? '(no guardrails declared)' : parts.join('; ');
}
