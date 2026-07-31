# `docs/` — the long-form documentation

Two documents live here, and they answer different questions. Everything shorter than these is in the root [`README.md`](../README.md); everything about *changing* the code is in [`CONTRIBUTING.md`](../CONTRIBUTING.md) and [`CLAUDE.md`](../CLAUDE.md).

| Document | Answers |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Where the internal boundary is, why `src/core` cannot import `vscode`, what the five bundles are, how the webview contract works, and what the ledger guarantees. |
| [`CONFIG.md`](CONFIG.md) | Every configuration key: the three layers and their precedence, all of `zer0.json`, all 35 `zer0Cms.*` settings, the placeholder tokens, and which layer a given decision belongs in. |

## The rule these two follow

Both documents describe **the code as it is**, not as a plan intended it. When they disagree with the source, the source is right and the document is a bug — so a change to configuration, to the JSON schema, or to the layer boundary is not finished until the matching document moves with it.

Two places make that concrete for `CONFIG.md`: every `zer0Cms.*` id it names exists in `package.json`'s `contributes.configuration`, and every `zer0.json` key it names exists in [`../schemas/zer0.schema.json`](../schemas/zer0.schema.json). Adding a setting means editing three files — the manifest, the settings layer in `src/config.ts`, and `CONFIG.md`. Adding a `zer0.json` key means editing four — the schema, `src/core/shared/types.ts`, `src/core/shared/config.ts`, and `CONFIG.md`.

## Writing conventions

Markdown here is **one paragraph per line** — no soft wrapping. CI enforces it; run `python3 tools/unwrap-prose.py --write` after editing, or `--check` to see what would change.

## Nearby documentation

The per-directory `README.md` files are the other half of the documentation and are usually the faster answer: [`src/core/`](../src/core/README.md), [`src/core/shared/`](../src/core/shared/README.md), [`src/core/content/`](../src/core/content/README.md), [`src/core/governance/`](../src/core/governance/README.md), [`src/core/contract/`](../src/core/contract/README.md), [`src/core/catering/`](../src/core/catering/README.md), [`src/mcp/`](../src/mcp/README.md), [`src/panel/`](../src/panel/README.md), [`src/dashboard/`](../src/dashboard/README.md), [`src/webview/panel/fields/`](../src/webview/panel/fields/README.md), and [`rails/`](../rails/README.md) for the ABC content engine, which is a separate product in the same repository.
