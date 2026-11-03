#!/usr/bin/env node
// Generates src/schema.d.ts — the platform API's types — from the committed
// OpenAPI document (schemas/openapi/openapi.json) with openapi-typescript.
// `--check` writes nothing and fails when the committed types differ from a
// fresh generation, so a schema change cannot land without its client.
// Both modes, and test/drift.test.ts, run the same generation
// (scripts/generate.mjs), so they can never disagree about the output.
import { readFileSync, writeFileSync } from 'node:fs';
import { generate, TARGET } from './generate.mjs';

const fresh = await generate();

if (process.argv.includes('--check')) {
  if (readFileSync(TARGET, 'utf8') !== fresh) {
    console.error('web/packages/api/src/schema.d.ts is stale: run `npm run gen` in web/ and commit the result');
    process.exit(1);
  }
  console.log('@zer0/api types match schemas/openapi/openapi.json');
} else {
  writeFileSync(TARGET, fresh);
  console.log('wrote web/packages/api/src/schema.d.ts');
}
