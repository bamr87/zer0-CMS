/**
 * Appending one lane to `fleet.manifest.yml` — by line surgery, not by
 * re-emitting the document.
 *
 * The manifest is a hand-edited file with a hand-written header comment, a
 * `summary:` somebody wrote a sentence for, and a `provenance:` that records
 * whether `wtd fleet adopt` derived it or a person declared it. Parsing that
 * into an object and dumping it back would reformat every line it touched and
 * drop every comment — and a tool whose edits are unreadable is a tool people
 * stop letting near their files. This is the same discipline as the front-matter
 * editor (`updateFrontMatterKeys`): rewrite the lines that change, leave every
 * other byte exactly as it was.
 *
 * So the whole operation is: find the end of the `lanes:` block, insert the
 * rendered lane there, and return the new text. Everything else — comments,
 * spacing, key order, the `tokens:` block and who uses what — is untouched.
 *
 * The refusals are as much of the contract as the insertion:
 *
 *  - **A duplicate id is refused, never appended.** Two lanes with one id is the
 *    collision that reddens a whole repository's CI (`lint_artifacts` gates on
 *    it in lifehacker.dev, and a merge of two branches that each added the same
 *    id is exactly how it happens). Refusing is the only safe answer, because
 *    the console cannot know which of the two the person meant.
 *  - **A manifest with no `lanes:` key is refused.** That is not a fleet
 *    manifest, and guessing where lanes would go in an unknown document is how a
 *    generator corrupts a file.
 *
 * Pure: text in, text out, no `fs`, no engines.
 */

/** Either the new document, or why nothing was changed. */
export type ManifestAppend = { text: string } | { refused: string };

/** The id on the first line of a rendered lane (`- id: content-factory`). */
export function laneIdOf(laneYaml: string): string | null {
  const first = laneYaml.split('\n')[0] ?? '';
  const match = /^-\s+id:\s*(.+?)\s*$/.exec(stripCr(first));
  const raw = match?.[1];
  if (raw === undefined || raw === '') {
    return null;
  }
  return unquote(raw);
}

/** Every lane id a manifest already declares, in document order. */
export function laneIdsIn(text: string): string[] {
  const lines = text.split('\n').map(stripCr);
  const start = lines.findIndex((line) => /^lanes:\s*$/.test(line));
  if (start < 0) {
    return [];
  }
  const ids: string[] = [];
  for (let i = start + 1; i < lines.length; i += 1) {
    const line = lines[i] ?? '';
    if (isTopLevelKey(line)) {
      break;
    }
    const match = /^-\s+id:\s*(.+?)\s*$/.exec(line);
    if (match?.[1] !== undefined) {
      ids.push(unquote(match[1]));
    }
  }
  return ids;
}

/**
 * Insert `laneYaml` at the end of the manifest's `lanes:` block — in practice,
 * immediately before `tokens:`, which is the key that follows it in every
 * manifest this fleet has written.
 *
 * The insertion point is computed rather than assumed: it is the first
 * column-zero key after `lanes:`, whatever that key happens to be, and the end
 * of the document when there is none. Trailing blank lines inside the block stay
 * below the new lane, so a manifest that separated its sections keeps its
 * spacing.
 */
export function appendLaneToManifest(text: string, laneYaml: string): ManifestAppend {
  const id = laneIdOf(laneYaml);
  if (id === null) {
    return { refused: 'the rendered lane does not begin with `- id: <lane>`' };
  }

  const lines = text.split('\n');
  const start = lines.findIndex((line) => /^lanes:\s*$/.test(stripCr(line)));
  if (start < 0) {
    return { refused: 'this file declares no `lanes:` key, so it is not a fleet/v1 manifest' };
  }

  const existing = laneIdsIn(text);
  if (existing.includes(id)) {
    return {
      refused: `the manifest already declares a lane called \`${id}\` — two lanes on one id collide the moment the branches merge`,
    };
  }

  // Where the block ends: the next column-zero key, else the end of the file.
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i += 1) {
    if (isTopLevelKey(stripCr(lines[i] ?? ''))) {
      end = i;
      break;
    }
  }
  // The blank lines and the comment block that sit immediately above the next
  // key belong to that key — `# The token contract.` is a heading for `tokens:`,
  // not a footnote on the last lane — so the new lane goes above them. A comment
  // that really did annotate the final lane ends up below the new one; that is
  // the trade, and it is the less surprising half of it.
  while (end > start + 1) {
    const previous = stripCr(lines[end - 1] ?? '').trim();
    if (previous === '' || previous.startsWith('#')) {
      end -= 1;
      continue;
    }
    break;
  }

  const block = laneYaml.replace(/\n+$/, '').split('\n');
  const out = [...lines.slice(0, end), ...block, ...lines.slice(end)];
  return { text: out.join('\n') };
}

/** `tokens:`, `lanes:`, `repo: x` — a key at column zero, not a list item. */
function isTopLevelKey(line: string): boolean {
  return /^[A-Za-z_][A-Za-z0-9_-]*\s*:/.test(line);
}

function stripCr(line: string): string {
  return line.endsWith('\r') ? line.slice(0, -1) : line;
}

/** `"content-factory"` and `content-factory` are the same id. */
function unquote(raw: string): string {
  const trimmed = raw.trim();
  if (
    trimmed.length >= 2 &&
    ((trimmed.startsWith('"') && trimmed.endsWith('"')) ||
      (trimmed.startsWith("'") && trimmed.endsWith("'")))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

/**
 * Every `*_ENABLED` variable a manifest's lanes already claim.
 *
 * Two lanes on one switch arm and disarm each other, which is why the scaffold
 * gate asks — and why this reads the committed manifest rather than trusting the
 * spec in front of it.
 */
export function switchesIn(text: string): string[] {
  const lines = text.split('\n').map(stripCr);
  const start = lines.findIndex((line) => /^lanes:\s*$/.test(line));
  if (start < 0) {
    return [];
  }
  const out: string[] = [];
  for (let i = start + 1; i < lines.length; i += 1) {
    const line = lines[i] ?? '';
    if (isTopLevelKey(line)) {
      break;
    }
    const match = /^\s+switch:\s*(.+?)\s*$/.exec(line);
    const value = match?.[1];
    if (value !== undefined && value !== '' && value !== 'null') {
      out.push(unquote(value));
    }
  }
  return out;
}
