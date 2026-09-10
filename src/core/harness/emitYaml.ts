/**
 * A small, deterministic YAML emitter — the manifest half of lane generation,
 * ported so that the MCP server can render a lane preview.
 *
 * `@bamr87/fleet-engines` already exports exactly this function
 * (`harness/manifest-yaml.ts`, re-exported here as `engineYamlDump`), and the
 * console uses the package's copy wherever the package is available. This is a
 * port rather than a call for one reason: `dist/mcp-server.js` is built with an
 * empty bare-import allow-list, so a module the MCP graph reaches may not import
 * the package at all (decision D14). `zer0_lane_preview` renders a manifest
 * entry, therefore the emitter behind it has to be engines-free — and forty
 * lines of block-style YAML is a cheaper thing to keep honest than a second
 * bundle exception.
 *
 * **One deliberate divergence from the package's emitter: nested sequences are
 * indentless.** The package renders a list under a mapping key one level deeper
 * (`triggers:` then four spaces before `- kind:`). Every `fleet.manifest.yml`
 * committed in this fleet was written by `wtd fleet adopt`, whose PyYAML puts the
 * dash at the *same* column as its key — and this emitter's output is inserted
 * into one of those documents by `appendLaneToManifest`. A lane whose sub-lists
 * indent differently from every other lane's in the same file is exactly the diff
 * noise line surgery exists to avoid, so the emitter matches the document rather
 * than the sibling emitter. Everything else — block style, the quoting predicate,
 * insertion-order keys — is the package's.
 *
 * (The quoting predicate is kept verbatim even where PyYAML would differ: a cron
 * expression contains `*`, so it comes out `cron: "17 9 * * *"` where `wtd` wrote
 * `cron: 17 9 * * *`. Same string to every reader, one pair of quotes more.)
 *
 * What it deliberately does not do: flow collections, anchors, multi-line
 * scalars, or key sorting. Keys come out in insertion order, which is what makes
 * two runs over the same value produce the same bytes.
 */

/**
 * Emit `value` as block-style YAML at `indent` levels of two spaces.
 *
 * Total: every input produces text, including `undefined` (`null`) and an empty
 * list (`[]`). Never throws, because a generator that throws mid-render leaves a
 * person with half a file and no explanation.
 */
/**
 * Deliberately not called `yamlDump`: `@bamr87/fleet-engines` exports a function
 * by that name, and the core barrel is asserted never to re-export a package
 * export's name — two functions called the same thing, one bundled and one not,
 * is a confusion nobody would enjoy debugging. The seam aliases the package's as
 * `engineYamlDump`; this is the engines-free port the MCP process can call.
 */
export function emitYaml(value: unknown, indent = 0): string {
  const pad = '  '.repeat(indent);

  if (Array.isArray(value)) {
    if (value.length === 0) {
      return `${pad}[]\n`;
    }
    return value
      .map((item) => {
        if (item !== null && typeof item === 'object') {
          // The nested body is rendered one level deeper and its FIRST line is
          // dedented onto the `- `, which is two characters wide — so every
          // following line already sits at the right column.
          const body = emitYaml(item, indent + 1).replace(/^\s*/, '');
          return `${pad}- ${body}`;
        }
        return `${pad}- ${yamlScalar(item)}\n`;
      })
      .join('');
  }

  if (value !== null && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => {
        if (nested !== null && typeof nested === 'object') {
          if (Array.isArray(nested) && nested.length === 0) {
            return `${pad}${key}: []\n`;
          }
          // A list stays at its key's own column (see the header note); a nested
          // mapping goes one level deeper, as it must.
          const inner = Array.isArray(nested) ? indent : indent + 1;
          return `${pad}${key}:\n${emitYaml(nested, inner)}`;
        }
        return `${pad}${key}: ${yamlScalar(nested)}\n`;
      })
      .join('');
  }

  return `${pad}${yamlScalar(value)}\n`;
}

/**
 * One scalar, quoted only when it has to be.
 *
 * The predicate is the package's: a plain string of word-ish characters passes
 * through, anything else becomes a JSON string (which is legal YAML), and the
 * six words YAML would read as booleans or null are always quoted. A cron
 * expression contains `*`, so it comes out quoted — the same value, one more
 * pair of quotes than `wtd fleet adopt`'s Python writes, and valid either way.
 */
export function yamlScalar(value: unknown): string {
  if (value === null || value === undefined) {
    return 'null';
  }
  if (typeof value === 'boolean' || typeof value === 'number') {
    return String(value);
  }
  const text = String(value);
  const plain =
    /^[A-Za-z0-9_./@-][A-Za-z0-9_./@ -]*$/.test(text) && !/^(true|false|null|yes|no)$/i.test(text);
  return plain ? text : JSON.stringify(text);
}
