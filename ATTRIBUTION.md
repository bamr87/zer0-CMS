# Attribution

zer0-CMS began, in 2026, as a fork of [Front Matter CMS](https://github.com/estruyf/vscode-front-matter) by **Elio Struyf**, taken at upstream **v10.10.1**.

It is no longer a fork.
The extension was rewritten from scratch: vanilla TypeScript instead of React, esbuild instead of webpack, its own `zer0Cms.*` command namespace, its own `zer0.json` project file, and no runtime dependencies.
It does not track upstream and cannot merge from it.

## What still derives from Front Matter

The rewrite deliberately reproduces Front Matter's **interaction design**, because it is good and because the people using zer0-CMS already know it:

- the sidebar-panel layout — metadata fields for the active file, SEO insights, actions, recently-modified;
- the dashboard shell — contents grid/list, filters, sorting, grouping, pagination;
- the field-type vocabulary (`string`, `number`, `choice`, `tags`, `categories`, `datetime`, `image`, `fields`, …);
- some CSS metrics and the shape of several `contributes` entries.

Those are the portions the upstream copyright notice in [`LICENSE`](LICENSE) covers.
Both projects are MIT, and the original notice is retained as MIT requires.

## What is not from Front Matter

- The governance layer — the draft queue, brand guard, human approval recorded in the file, and the idempotency ledger — comes from [BASH-CMS](https://github.com/bamr87/bash-cms), also by this author.
- The `.cms/` contract reader, the distribution/catering lanes, and the optional Claude agent are zer0-CMS's own.
- Every line of the current `src/` tree was written for this project.

## Thanks

Front Matter CMS is a mature, generous piece of work, and years of its design thinking are visible in this extension's UI.
If zer0-CMS is useful to you, please also support the project it learned from: <https://github.com/sponsors/estruyf>.
