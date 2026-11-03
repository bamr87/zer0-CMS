// The types of generate.mjs, which scripts/gen.mjs runs under plain Node and
// test/drift.test.ts imports.
export declare const SCHEMA: URL;
export declare const TARGET: URL;
export declare function generate(document?: URL | Record<string, unknown>): Promise<string>;
