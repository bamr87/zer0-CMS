// @vitest-environment node
// The generated client's drift check as a test: src/schema.d.ts must be what
// openapi-typescript (the exact-pinned version) makes of the committed OpenAPI
// document, generated in memory by the same function `npm run gen` and
// `npm run check:api` run (scripts/generate.mjs). A hand edit to the types, or
// a document that changed without `npm run gen`, fails here.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { generate, SCHEMA, TARGET } from '../scripts/generate.mjs';

describe('the generated client', () => {
  it('is what openapi-typescript makes of schemas/openapi/openapi.json', async () => {
    expect(await generate()).toBe(readFileSync(TARGET, 'utf8'));
  }, 60_000);

  it('would not match a document that changed without regeneration', async () => {
    const document = JSON.parse(readFileSync(SCHEMA, 'utf8')) as { paths: Record<string, unknown> };
    const [entry, ...rest] = Object.entries(document.paths);
    const first = entry?.[0];
    expect(first).toBeDefined();
    const stale = await generate({ ...document, paths: Object.fromEntries(rest) });
    expect(stale).not.toBe(readFileSync(TARGET, 'utf8'));
    expect(stale).not.toContain(`"${first}": {`);
  }, 60_000);
});
