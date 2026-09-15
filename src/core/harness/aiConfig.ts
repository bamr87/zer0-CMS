/**
 * `_data/ai.yml` — the one place a site says which model its automation runs on.
 *
 * Every consumer of the fleet's `ai-runner` kit carries this file, and its
 * header says the same sentence in every repository: *the ONE place AI is
 * configured*. The hub's `run.sh` reads exactly one key from it (`model`) and
 * resolves the model as `--model` > `AI_MODEL` > this file > a built-in
 * default. The API-fallback path reads `fallback_model` and `max_tokens`.
 *
 * The reason this console reads it at all is decision D-F: an editor that
 * defaults to a different model than the repository's own CI is a console that
 * quietly disagrees with the thing it is a console *for*. So the path is a
 * setting (`zer0Cms.cms.aiConfigPath`, default `_data/ai.yml`) rather than a
 * literal — a site that keeps it elsewhere is still readable — and everything
 * the file said that we do not model is kept in `extra` rather than dropped,
 * because `illustrator_model:` and `xai_image_model:` are real answers to real
 * questions this module simply is not the one asking.
 *
 * Auth is never in this file, in any repository, and nothing here looks for it.
 */

import { asString, parseYamlSubset, type FmValue } from '../content/frontmatter';
import type { AiConfig } from '../shared/types';
import type { HarnessIo } from './agents';

/** The kit's conventional location, and the default of `zer0Cms.cms.aiConfigPath`. */
export const AI_CONFIG_PATH = '_data/ai.yml';

/** The keys this module models. Everything else lands in `extra`. */
const MODELLED = new Set(['provider', 'model', 'fallback_model', 'max_tokens']);

function scalar(value: FmValue | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (Array.isArray(value) || typeof value === 'object') {
    return null;
  }
  const text = asString(value).trim();
  return text.length > 0 ? text : null;
}

/**
 * Parse `_data/ai.yml`. Never throws; a file this parser cannot read yields a
 * record whose fields are all `null`, which reads as "the file did not say" —
 * the same tristate the fleet manifest parser keeps, and for the same reason.
 */
export function parseAiConfig(filePath: string, text: string): AiConfig {
  const data = parseYamlSubset(text);
  const maxTokensRaw = scalar(data['max_tokens']);
  const maxTokens = maxTokensRaw === null ? null : Number.parseInt(maxTokensRaw, 10);
  const extra: Record<string, string> = {};
  for (const [key, value] of Object.entries(data)) {
    if (MODELLED.has(key)) {
      continue;
    }
    const flat = scalar(value);
    if (flat !== null) {
      extra[key] = flat;
    }
  }
  return {
    path: filePath,
    provider: scalar(data['provider']),
    model: scalar(data['model']),
    fallbackModel: scalar(data['fallback_model']),
    maxTokens: maxTokens === null || Number.isNaN(maxTokens) ? null : maxTokens,
    extra,
  };
}

/**
 * Read a site's AI configuration, or `null` when it has none — which is the
 * normal state for a repository that runs no AI lanes, and never an error.
 */
export async function readAiConfig(
  io: HarnessIo,
  rel: string = AI_CONFIG_PATH,
): Promise<AiConfig | null> {
  const text = await io.read(rel);
  return text === undefined ? null : parseAiConfig(rel, text);
}
