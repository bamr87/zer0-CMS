# Configuration

zer0-CMS is configured from two surfaces that resolve into one value object.

`zer0.json` describes the **project**: where content lives, what shape it has, what a slug looks like, which thresholds SEO is measured against. It is committed, it is read by the extension *and* by the bundled MCP server, and it is the same for everyone who clones the repo. VS Code settings under `zer0Cms.*` describe **your preferences on this machine**: whether the panel opens by itself, how big a dashboard page is, where your Python lives, whether publishing is allowed at all. There are 35 of them, and none of them describe the project.

Everything below is checked against the code as it is: the settings against `package.json`, the `zer0.json` keys against `schemas/zer0.schema.json`, and the behaviour against `src/core/shared/config.ts` (the resolver) and `src/config.ts` (the only VS Code translator).

---

## 1. The three layers

| # | Layer | Where | Who reads it |
|---|---|---|---|
| 1 | VS Code settings | `zer0Cms.*` in user, workspace or folder `settings.json` | the extension only |
| 2 | Project config | `zer0.json` at the workspace root | the extension, the bundled MCP server, anything else pointed at the repo |
| 3 | Built-in defaults | `defaultConfig()` in `src/core/shared/config.ts` | everything |

**Precedence is per key: settings beat the file, the file beats the defaults.** `resolveConfig(root, file, settings)` walks every key explicitly and takes the first layer that has a value — there is no deep merge, no `extends`, no split-config directory and no dynamic configuration module. The result is always complete: every key of `Zer0Config` is present, so no consumer downstream ever writes `?? someDefault` again.

### 1.1 A setting only counts if a human set it

This is the subtlety that makes three layers real rather than two.

Every one of the 35 settings declares a `default` in `package.json`. So `vscode.workspace.getConfiguration('zer0Cms').get('governance.publishAllow')` **never** returns `undefined` — it returns `false` for a workspace that has never heard of the setting. A settings layer built that way would always have a value for every key, and would therefore silently outrank `zer0.json` everywhere.

`src/config.ts` reads the settings layer with `inspect()` instead:

```ts
function explicit<T>(config: vscode.WorkspaceConfiguration, key: string): T | undefined {
  const found = config.inspect<T>(key);
  if (found === undefined) return undefined;
  if (found.workspaceFolderValue !== undefined) return found.workspaceFolderValue;
  if (found.workspaceValue !== undefined) return found.workspaceValue;
  return found.globalValue;         // the package.json default is deliberately ignored
}
```

A key is "set" only when it is written in a `settings.json` — folder scope first, then workspace, then user. The manifest default is skipped on purpose, because that is layer 3's job.

The consequence worth internalising: **writing a setting's own default value into `settings.json` is not the same as leaving it out.** `"zer0Cms.governance.publishAllow": false` is an explicit `false` that overrides a `zer0.json` saying `true`; deleting that line lets the file's `true` through. Only `zer0Cms.configFile` is `resource`-scoped (so a multi-root workspace can set it per folder) and only `zer0Cms.cms.pythonPath` is `machine-overridable`; the rest are window-scoped, so their folder values do not exist and `explicit()` falls through to workspace and user.

### 1.2 A worked example

Take `governance.publishAllow`, the master publish gate.

| `zer0.json` | `.vscode/settings.json` | Resolved | Why |
|---|---|---|---|
| *(absent)* | *(absent)* | `false` | layer 3 — the built-in default |
| `{"governance": {"publishAllow": true}}` | *(absent)* | `true` | layer 2 — nothing in settings is *set* |
| `{"governance": {"publishAllow": true}}` | `"zer0Cms.governance.publishAllow": false` | `false` | layer 1 — an explicit `false`, even though `false` is also the manifest default |
| `{"governance": {"publishAllow": false}}` | `"zer0Cms.governance.publishAllow": true` | `true` | layer 1 |
| `{"governance": {"publishAllow": "yes"}}` | *(absent)* | `false` | the file value is not a boolean, so it is dropped, and layer 3 answers |

The `Resolved` column is what every gate inside the editor reads. It is **not** what arms the bundled MCP server: that reads the settings column alone, so row 2 gives an editor that can publish and an agent that cannot. See §6.

The same three-layer walk applies to all 35 settings, and only to them. `contentFolders`, `contentTypes`, `fieldGroups`, `taxonomy`, `draftField`, `frontMatter`, `content.filePrefix`, `slug`, `placeholders`, and the six `seo` keys other than `enabled` have no settings twin at all — they are layer 2 or layer 3, never layer 1.

### 1.3 Three merge rules that surprise people

**Arrays and free-form objects replace wholesale.** There is no item-level merging: a `dashboard.cardFields` in settings replaces the `zer0.json` object entirely rather than patching it, and a `contentTypes` array is taken from exactly one layer. (Front Matter merged these, and "where did this content type come from?" became unanswerable.)

**An empty list falls through to the next layer.** Four keys whose default is non-empty use `pickList` instead of `pick`: `content.supportedFileTypes`, `governance.acceptStatuses`, `cms.contentDirs` and `panel.sections`. For these, `[]` is treated as "not configured", so `"acceptStatuses": []` does *not* block every publish — it inherits `["pending", "approved"]`. If you want to require the in-editor approval step, write `["approved"]`.

**The file layer is coerced, not trusted.** `zer0.json` is untrusted JSON, so every value is type-checked as it is read: a field with an unknown `type`, a content type with no `name`, a content folder with no `path`, a taxonomy entry with no `id`, or a wrong-typed leaf is **dropped**, not admitted. A dropped entry is silent in the resolved config — the JSON schema in `schemas/zer0.schema.json` is what tells you about it while you type, which is why the schema association matters.

### 1.4 When configuration is re-read

Nothing is cached. `currentConfig()` re-reads the settings and re-parses `zer0.json` on every call, so flipping a setting or saving the file takes effect on the next command, the next panel render and the next publish gate — no window reload. A `zer0.json` that fails to parse degrades to `{}` plus a warning in the output channel, because the panel must still render while you are halfway through typing a comma.

---

## 2. Where `zer0.json` lives

The file is looked up in this order, and the first one that exists on disk wins:

1. the value of `zer0Cms.configFile` (default `zer0.json`),
2. `zer0.json`,
3. `.zer0/config.json`.

If none exists, the configured name is where **zer0-CMS: Initialize project** will create one. The two conventional names are also the extension's `workspaceContains` activation events and the `fileMatch` list of the JSON schema contribution, so a workspace holding either gets validation, completion and hover documentation for free.

Three things about the file's dialect are worth knowing before you decide to comment it:

- `package.json` associates `zer0.json` with the `jsonc` language, and the extension parses it with a JSONC reader — comments and trailing commas are tolerated.
- The **bundled MCP server reads it the same way**, through the same `readJsonc`. The two lanes agree, so a config the editor accepts is a config the server accepts; a file that fails to parse in either is treated as "no config", falling back to the built-in defaults without complaint.
- Any command that writes the file — **Register content folder**, **Generate content type from file**, **Add missing fields**, and adding a freeform tag or category from the panel — rewrites it with `JSON.stringify(json, null, 2)`. **Comments do not survive that.**

`configFile` itself has no `zer0.json` key: it names the file, so it cannot live inside it. (The resolver would read a `configFile` key from the file layer, but the extension always pins that slot to the file it actually loaded, and the JSON schema rejects the key outright.)

A minimal starting point. **Initialize project** writes the same two keys and nothing else — one content folder at `pages/`, and the built-in `default` content type with its seven fields — and it does not write the optional `$schema` line:

```jsonc
{
  "$schema": "./schemas/zer0.schema.json",
  "contentFolders": [{ "title": "Pages", "path": "[[workspace]]/pages" }],
  "contentTypes": [{ "name": "default", "fields": [{ "name": "title", "type": "string" }] }]
}
```

### 2.1 Root keys at a glance

| `zer0.json` key | VS Code twin | What it decides |
|---|---|---|
| `$schema` | — | optional; points at the schema so an editor without the extension still validates |
| `contentFolders` | — | which directories hold editable content |
| `contentTypes` | — | the field schema the panel renders |
| `fieldGroups` | — | reusable field sets, spliced in by `fieldCollection` |
| `taxonomy` | — | known tags, categories and custom taxonomies |
| `draftField` | — | which front-matter key marks a draft |
| `frontMatter` | — | the dialect written back to disk |
| `content` | 5 of 6 keys | file types, public folder, filename prefix, casing, modified stamping |
| `seo` | `enabled` only | which SEO rows appear and what they are measured against |
| `slug` | — | the URL a page gets from its title |
| `placeholders` | — | custom `{{token}}`s |
| `snippets` | — | **reserved** — accepted by the schema, never consumed |
| `date` | both keys | the date pattern and time zone |
| `governance` | all 7 keys | the publishing gate |
| `cms` | all 5 keys | the `.cms/` contract and the Python engine |
| `agent` | all 4 keys | the optional AI layer |
| `validation` | `enabled` | required-field diagnostics |
| `panel` | all 3 keys | which panel sections exist, in what order |
| `dashboard` | all 5 keys | the dashboard's initial state |
| `logging` | `level` | output-channel verbosity — **but see §3.19** |

---

## 3. `zer0.json` key reference

### 3.1 `contentFolders`

The directories zer0-CMS indexes, lists in the dashboard, and offers when creating content. Nothing outside a registered folder is content.

| Property | Type | Meaning |
|---|---|---|
| `path` | string, **required** | Where the folder is. `[[workspace]]` expands to the workspace root; `*` / `?` / `**` register every matching directory; `{{year}}`-style date tokens are resolved against `date.format` and `date.timezone`. |
| `title` | string | The label in the tree and the dashboard. Defaults to the directory's basename; a wildcard entry gets `Title (relative/path)` per match. |
| `contentTypes` | string[] | The types offered when creating here. Omit to allow all. A folder that binds **exactly one** type also uses it to resolve the type of files already inside it. |
| `excludeSubdir` | boolean | Index only files sitting directly in the folder. |
| `excludePaths` | string[] | Glob patterns skipped during indexing. |
| `disableCreation` | boolean | Hide this folder from "Create content". |
| `filePrefix` | string \| null | Overrides `content.filePrefix` here. `null` or `""` means "no prefix", which is how a folder switches off a workspace-wide one. |

```json
"contentFolders": [
  { "title": "Posts", "path": "[[workspace]]/pages/_posts", "contentTypes": ["post"] },
  { "title": "Docs", "path": "[[workspace]]/pages/docs", "excludePaths": ["**/_drafts/**"] },
  { "title": "Yearly", "path": "[[workspace]]/pages/*/posts" }
]
```

A folder that does not exist yet is still listed — creating it is a decision the shell offers, not one the config makes. Duplicate paths (two entries expanding onto the same directory) collapse, first declaration winning. A file is matched to its folder by longest path-boundary prefix, so `pages/_posts/tech` wins over `pages/_posts` for a file inside both.

### 3.2 `contentTypes`

A content type is a named list of fields. It decides what the Metadata section renders, which fields are required, and what a new file of that type starts life containing.

| Property | Type | Meaning |
|---|---|---|
| `name` | string, **required** | The type's id. Stamped into new files as `type: <name>` unless it is `default`. |
| `fields` | Field[], **required** | See §3.3. |
| `fileType` | string | Extension for new files. Overrides `content.defaultFileType`. |
| `slugTemplate` | string \| null | Overrides `slug.template` for this type. `null` means "no opinion" — the workspace template still applies. |
| `pageBundle` | boolean | Create `<slug>/index.md` instead of `<slug>.md`. |
| `defaultFileName` | string | The bundle's entry filename (default `index`). |
| `template` | string | A workspace file used as the body and front-matter seed for new content. |
| `filePrefix` | string \| null | Overrides the folder's and the workspace's prefix. |
| `clearEmpty` | boolean | Omit keys whose value would be empty instead of writing them. |

**How a file's type is resolved**, in order: the file's own `type:` key when it names a registered type → the owning content folder when it binds exactly one type → the sole registered type when the workspace declares only one → the type literally named `default` → the built-in schema (title, description, date, preview, draft, tags, categories). A workspace with no `contentTypes` at all is a working CMS, not an error.

**How a new file is filled**, per field, in declaration order: a value from the content type's `template` wins, then the field's `default` (with placeholders expanded), then the type's empty value (§3.3). Fields whose `when` clause is false are not written at all — a field the author cannot see is a field they cannot fix. Keys the template carries that no field declares survive, appended in the template's order.

```json
"contentTypes": [
  {
    "name": "post",
    "fileType": "md",
    "slugTemplate": "{{year}}/{{seoTitle}}",
    "filePrefix": "{{date|yyyy-MM-dd}}",
    "clearEmpty": true,
    "fields": [
      { "name": "title", "type": "string", "single": true, "required": true },
      { "name": "description", "type": "string", "required": true },
      { "name": "date", "type": "datetime", "default": "{{now}}", "isPublishDate": true },
      { "name": "lastmod", "type": "datetime", "isModifiedDate": true },
      { "name": "preview", "type": "image", "isPreviewImage": true },
      { "name": "draft", "type": "draft" },
      { "name": "tags", "type": "tags", "taxonomyLimit": 5 },
      { "name": "categories", "type": "categories", "singleValueAsString": true }
    ]
  }
]
```

### 3.3 Fields — the 18 types

Every field carries these, whatever its type:

| Property | Type | Meaning |
|---|---|---|
| `name` | string, **required** | The front-matter key it edits. |
| `type` | one of the 18 below, **required** | An unrecognised type drops the whole field. |
| `title` | string | The label. Defaults to a humanised `name`. |
| `description` | string | Help text under the control — shown unless the required message replaces it. |
| `default` | string \| number \| boolean \| string[] | Used on creation. String values are placeholder-expanded. |
| `required` | boolean | Empty ⇒ a Problems-panel diagnostic and a red control (see `validation.enabled`). |
| `hidden` | boolean | Render nothing. The key is still written on creation. |
| `editable` | boolean | Only the `slug` control honours it: `false` disables its input. |
| `when` | object | Conditional visibility — see §3.4. |

The 18 types, their controls, their type-specific properties, and the value a new file gets when nothing else supplies one:

| Type | Control | Type-specific properties | Empty value |
|---|---|---|---|
| `string` | textarea, or a single-line input with `single` | `single`, `encodeEmoji` | `""` |
| `number` | number input | `numberOptions`: `isDecimal`, `min`, `max`, `step` | `0` |
| `boolean` | toggle | — | `false` |
| `datetime` | native date / datetime-local plus a **now** button | `isPublishDate`, `isModifiedDate`, `dateFormat` | `null` |
| `image` | picker with preview | `multiple`, `isPreviewImage` | `""`, or `[]` with `multiple` |
| `file` | file picker | `fileExtensions` (**required by the schema**), `multiple` | `""`, or `[]` with `multiple` |
| `choice` | dropdown | `choices`, `multiple` | `""`, or `[]` with `multiple` |
| `tags` | taxonomy picker over `taxonomy.tags` | `taxonomyLimit`, `singleValueAsString` | `[]` |
| `categories` | taxonomy picker over `taxonomy.categories` | `taxonomyLimit`, `singleValueAsString` | `[]` |
| `taxonomy` | taxonomy picker over one `taxonomy.custom[]` entry | `taxonomyId`, `taxonomyLimit`, `singleValueAsString` | `[]` |
| `draft` | toggle, or a choice when the field declares `choices` | — (reads `draftField` for its empty value) | `true`, or `false` when `draftField.invert`, or the first `draftField.choices` entry |
| `list` | add / edit / delete list of strings | — | `[]` |
| `slug` | input plus a generate button that offers the slug the title would produce | `editable` | `""` |
| `fields` | a nested group of fields | `fields` | `{}` |
| `fieldCollection` | nothing — replaced by its group before render | `fieldGroup` (**required by the schema**) | *(no key written)* |
| `divider` | a horizontal rule | — | *(no key written)* |
| `heading` | a sub-heading, plus `description` as a paragraph | — | *(no key written)* |
| `contentRelationship` | combobox over other pages | `contentTypeName` (**required by the schema**), `contentTypeValue` (`path` \| `slug`), `sameContentLocale`, `multiple` | `""`, or `[]` with `multiple` |

Notes that only show up when you use them:

- `single` on `string` swaps the textarea for a one-line input; `encodeEmoji` writes emoji as `\uXXXX` escapes — and, when the field is the SEO title field, does so before the title is used for the filename, so the two agree.
- `isPublishDate` marks the field the dashboard sorts "published" by. `isModifiedDate` marks the field `content.autoUpdateModifiedDate` (and the **Set last-modified date** command) stamps; with no such field, it falls back to whichever of `lastmod`, `last_modified_at`, `lastModified`, `modified`, `updated` the file already carries, and stamps nothing if there is none — it will not invent a date key a site never asked for. `dateFormat` overrides `date.format` for that one field.
- `isPreviewImage` names the image the dashboard card uses. Without one, the index falls back to `image`, `preview`, `thumbnail`, `cover`, `featured_image`, `banner`, in that order.
- `choices` accepts bare strings or `{ "id": "...", "title": "..." }` pairs.
- `taxonomyLimit` shows `(Max.: n)` beside the label and stops accepting values past it. `singleValueAsString` writes a lone selection as `tags: alpha` rather than a one-item list.
- `multiple` is described by the schema for `list` too, but the list control always stores an array, so it has no effect there.
- `fieldCollection` never survives into the resolved config: it is replaced by its group's fields, in the group's order, at load time. A collection naming an unknown or self-referential group expands to nothing.
- `divider` and `heading` are presentation only — they name no front-matter key and are skipped when a new file is filled in.
- `contentRelationship`'s `contentTypeName` is required by the schema and is what the picker asks the host to filter by; the host's search handler currently reads a different payload key, so today the list is every indexed page (capped at 50) rather than only pages of that type. `sameContentLocale` is accepted by the schema and not implemented.

### 3.4 `when` — conditional fields

```json
{ "name": "unsplashId", "type": "string",
  "when": { "fieldRef": "imageSource", "operator": "eq", "value": "unsplash" } }
```

| Property | Meaning |
|---|---|
| `fieldRef` | The sibling field whose value is compared. Resolved against the same field list — the content type's fields, or the enclosing `fields` group. |
| `operator` | One of the ten below. |
| `value` | Any JSON value. |
| `caseSensitive` | Defaults to `true`. `false` lowercases both sides, including the members of a list. |

| Operator | True when |
|---|---|
| `eq` | strictly equal |
| `neq` | not strictly equal |
| `contains` | a string contains the value, or a list has it as a member |
| `notContains` | the negation of `contains` |
| `startsWith` | a string starts with the value |
| `endsWith` | a string ends with the value |
| `gt` `gte` `lt` `lte` | both operands are numbers and the comparison holds |

Three rules govern evaluation. **An incomparable pair is visible**: `startsWith` against a number, or `gt` against a string, returns `true`, because a config whose types drifted should show too much rather than silently hide a required field. **A hidden parent hides its children**: a field conditioned on a field that is itself hidden by its own `when` is hidden too, regardless of its own comparison, and a cycle of `when` clauses terminates instead of recursing. **A missing value falls back to the referenced field's `default`**, so a clause still evaluates sensibly against a file that has never been saved.

Front Matter's four declared-but-unimplemented operators (`minimum`, `maximum`, `exlusiveMinimum`, `exclusiveMaximum`) are not part of the type or the schema — an operator that silently means "visible" is a config that lies to its author.

### 3.5 `fieldGroups`

Reusable field sets, spliced in wherever a `fieldCollection` field names their `id`.

```json
"fieldGroups": [
  {
    "id": "seoBlock",
    "labelField": "seoTitle",
    "fields": [
      { "name": "seoTitle", "type": "string", "single": true },
      { "name": "seoDescription", "type": "string" }
    ]
  }
],
"contentTypes": [
  { "name": "page", "fields": [
    { "name": "title", "type": "string" },
    { "name": "seo", "type": "fieldCollection", "fieldGroup": "seoBlock" }
  ] }
]
```

`labelField` names the field whose value labels each entry in the UI. Expansion is non-mutating and idempotent, and it happens everywhere content types are read, so nothing downstream ever sees a `fieldCollection`.

### 3.6 `taxonomy`

The known values the `tags`, `categories` and `taxonomy` field types offer.

```json
"taxonomy": {
  "tags": ["automation", "jekyll"],
  "categories": ["engineering", "notes"],
  "custom": [{ "id": "audience", "options": ["beginner", "operator"] }]
}
```

A `taxonomy`-typed field points at a custom entry with `taxonomyId: "audience"`. When `zer0Cms.panel.freeformTaxonomy` is on (it is by default), typing a value the list does not have creates it — and **writes it back into `zer0.json`**, sorted, under the matching key. That write is the read-modify-write described in §2, so it re-emits the file without comments.

### 3.7 `draftField`

Which front-matter key marks a draft, and how its value is read. This is what makes the governance gate work on a site whose flag is `published: true` or `status: in progress` rather than `draft: true`.

| Property | Default | Meaning |
|---|---|---|
| `name` | `"draft"` | The front-matter key. |
| `type` | `"boolean"` | `"boolean"` or `"choice"`. |
| `choices` | — | Allowed values when `type` is `"choice"`. The first is what a new file gets. |
| `invert` | — | Set when the field marks *published* rather than draft. |

```json
"draftField": { "name": "status", "type": "choice", "choices": ["draft", "in progress", "published"] }
```

```json
"draftField": { "name": "published", "type": "boolean", "invert": true }
```

The built-in publish target writes this key when it publishes: with `type: "boolean"` it writes `false`, or `true` when `invert` is set. With `type: "choice"` it writes nothing, because only you know which of your statuses means "live".

### 3.8 `frontMatter`

How front matter is **written**. Reading always auto-detects the format from the fence, and an existing file keeps its own dialect — the format below is what *new* files get and what a full re-serialization falls back to.

| Property | Default | Meaning |
|---|---|---|
| `format` | `"yaml"` | `"yaml"`, `"toml"` or `"json"`. |
| `indentArrays` | `true` | `true` indents block-sequence items under their key; `false` aligns them with it. |
| `quoteStringValues` | `false` | `true` double-quotes every string, even ones that need no quotes. |
| `commaSeparatedFields` | `[]` | Keys written on one line as `a, b, c` instead of a block sequence. |

```json
"frontMatter": { "format": "yaml", "indentArrays": false, "commaSeparatedFields": ["tags", "categories"] }
```

Most edits never reach the serializer at all: a change from the panel is applied by line surgery, rewriting only the lines of the keys that changed, so comments, key order and hand-formatting come out byte-identical. These options govern new keys, new files, and the documented full-emit fallback.

### 3.9 `content`

| Property | Default | VS Code twin | Meaning |
|---|---|---|---|
| `defaultFileType` | `"md"` | `zer0Cms.content.defaultFileType` | Extension for new content, unless the content type sets `fileType`. |
| `supportedFileTypes` | `["md", "mdx", "markdown"]` | `zer0Cms.content.supportedFileTypes` | What counts as content when indexing. An empty list falls through (§1.3). |
| `publicFolder` | `""` | `zer0Cms.content.publicFolder` | The folder served at the site root. Media paths are stored relative to it, and site-rooted paths (`/img/x.png`) are resolved through it. |
| `filePrefix` | `""` | — | Filename prefix template for new content, e.g. `{{date\|yyyy-MM-dd}}`. Overridden by a folder's or a content type's `filePrefix`. |
| `preserveCasing` | `false` | `zer0Cms.content.preserveCasing` | Keep the original casing when generating a filename, and when sanitizing an explicit publish slug. A slug *generated* from a title is always lowercased by the slugify pipeline. |
| `autoUpdateModifiedDate` | `false` | `zer0Cms.content.autoUpdateModifiedDate` | Stamp the `isModifiedDate` field on every save. |

The literal legacy prefix `yyyy-MM-dd` is rewritten to `{{date|yyyy-MM-dd}}` for you; without that, a date-shaped prefix would be taken as a literal filename.

### 3.10 `seo`

Thresholds, not rules: SEO here reports, it never blocks a save or a publish.

| Property | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Show the SEO section. Also the only key here with a settings twin (`zer0Cms.seo.enabled`). |
| `titleField` | `"title"` | The front-matter key holding the title. Used far beyond SEO: the dashboard, the publish plan and `{{title}}` all read it. |
| `titleLength` | `60` | Character budget for the title. |
| `descriptionField` | `"description"` | The description key. |
| `descriptionLength` | `160` | Character budget for the description. |
| `slugLength` | `75` | Character budget for the slug. |
| `contentLength` | `1760` | Recommended article length **in words**. Reported as an informational row; never marked valid or invalid. |

**Any length set to `0` or less switches that row off**, and removes the character counter from the matching field in the panel — it is not "a budget of zero characters". Keyword checks read the `keywords` front-matter key, which is fixed and not configurable.

```json
"seo": { "titleField": "seoTitle", "titleLength": 70, "descriptionLength": 155, "contentLength": 0 }
```

### 3.11 `slug`

| Property | Default | Meaning |
|---|---|---|
| `template` | `null` | The slug's shape. `null` (or an empty string) means "slugify the title". |
| `prefix` | `""` | Prepended to the slug when it is written into front matter. |
| `suffix` | `""` | Appended likewise. |
| `alignFilename` | `false` | Rename the file to match the generated slug. |
| `stopWords` | `"minimal"` | Which words a title loses on its way to a slug. `"minimal"`, `"smart"`, `"none"`, or a literal array that replaces the list outright. |

#### `slug.stopWords`

| Value | Drops |
|---|---|
| `"minimal"` *(default)* | `a an the and or of to in on for with at by from` — the closed class of function words, and nothing else. |
| `"smart"` | Front Matter's ~570-word SMART list, verbatim. |
| `"none"` | Nothing. Every word survives into the slug. |
| `["…"]` | Exactly the words you list, case-folded and trimmed. `[]` is legal and means the same as `"none"`. |

**Pick `"smart"` only to keep minting the URLs a Front Matter site already has.** That list was built for matching documents, not naming them, and it deletes words a title needs — `back`, `new`, `value`, `use`, `way`, `thing`, `vs`, and `without`:

| Title | `"smart"` | `"minimal"` |
|---|---|---|
| MCP for the back office | `mcp-office` | `mcp-back-office` |
| From prompts to pipelines: agentic AI in VS Code | `prompts-pipelines-agentic-ai-code` | `prompts-pipelines-agentic-ai-vs-code` |
| Migrating to QAD without losing data | `migrating-qad-losing-data` | `migrating-qad-without-losing-data` |

The third row is the reason the default changed: it is not a shorter URL, it is the opposite claim. Measured across a real 72-post site, `"smart"` cost a meaningful word in 31% of titles.

An unrecognised name (`"mininal"`) or a value of the wrong type falls back to the **default**, not to `"none"` — a typo should leave a site's permalinks alone rather than quietly re-slug every future page.

This only affects slugs *generated* from a title. A slug you write yourself is never stop-worded; it is transliterated and punctuation-collapsed and otherwise left as you typed it.

Note the shape: the workspace-level key is **`slug.template`**; `slugTemplate` is the per-content-type override (§3.2), and a content type's `null` means "inherit", not "disable at the workspace level".

A template is matched against four tokens in an **else-if chain** — the first one present wins and the rest are ignored, which is Front Matter's behaviour, preserved because a template is a permalink scheme and re-ordering it would silently re-slug every future page of a site with URLs already committed:

| Token | Value |
|---|---|
| `{{title}}` | the title lowercased with spaces turned into dashes — punctuation kept |
| `{{seoTitle}}` | the full slugify pipeline: transliterated, punctuation dropped, and the words `slug.stopWords` names dropped |
| `{{fileName}}` | the file's basename without its extension |
| `{{sluggedFileName}}` / `{{slugifiedFileName}}` | that basename, slugified |

Whatever the chain produced then goes through the time and front-matter tokens, so `blog/{{year}}/{{seoTitle}}` and `{{fm.category}}/{{seoTitle}}` both work.

`alignFilename` refuses two cases on purpose: a page-bundle `index` file (renaming it would move a directory, which is a decision a command has to ask about) and a name that is already correct. A leading `2026-07-31-` date prefix survives the rename.

### 3.12 `placeholders`

Custom `{{id}}` tokens, usable anywhere placeholders are processed (§4).

| Property | Meaning |
|---|---|
| `id` | The token is `{{id}}`. |
| `value` | A static replacement. |
| `script` | A workspace-relative script. Its **stdout** is the replacement, trimmed. |
| `command` | The interpreter for `script`. Defaults to `node`. |

```json
"placeholders": [
  { "id": "author", "value": "Amr" },
  { "id": "buildId", "script": "scripts/build-id.js", "command": "node" }
]
```

A script is run with `execFile` and an argv array — **no shell** — with three arguments: the workspace root, the file path (empty during creation of a file that has no path yet) and the title. It gets 5 seconds and 1 MB of stdout. A script that fails, times out or is missing resolves to `<failed to process>`, which every emptiness check reads as "no value", so a broken placeholder can never be written into your site as literal text. Output is used verbatim: it is not parsed as JSON and not split into a list.

Custom placeholders resolve *before* the time tokens, so a script may return text that still contains `{{now}}`.

### 3.13 `snippets`

**Reserved.** The schema accepts a `snippets` object so that a file carried over from Front Matter still validates, but nothing in zer0-CMS reads it. Content types carry field defaults and placeholders instead.

### 3.14 `date`

| Property | Default | Meaning |
|---|---|---|
| `format` | `"yyyy-MM-dd"` | The pattern used to format and parse front-matter dates. |
| `timezone` | `"UTC"` | IANA zone id, e.g. `America/New_York`. |

Pattern tokens: `yyyy yy MMMM MMM MM M dd d EEEE EEE HH H hh h mm m ss s SSS aaa a XXX`. Anything else is emitted literally, and text inside single quotes is always literal — `yyyy-MM-dd'T'HH:mm:ssXXX`. An unsupported token degrades to visible text rather than throwing inside a panel render, and an invalid time zone falls back to the host's own rather than breaking the panel.

Dates stay strings through the whole pipeline; nothing round-trips them through a JavaScript `Date` on the way back to disk.

### 3.15 `governance`

The publishing path: draft → brand guard → human approval → publish → ledger.

| Property | Default | VS Code twin | Meaning |
|---|---|---|---|
| `enabled` | `true` | `zer0Cms.governance.enabled` | Show the governance section and the draft queue. |
| `draftsFolder` | `".zer0/drafts"` | `zer0Cms.governance.draftsFolder` | Where the draft queue lives. |
| `ledgerPath` | `".zer0/ledger.json"` | `zer0Cms.governance.ledgerPath` | The idempotency ledger, keyed by canonical URL. |
| `acceptStatuses` | `["pending", "approved"]` | `zer0Cms.governance.acceptStatuses` | Draft statuses **publishing** accepts. Approving always requires `pending`. |
| `publishAllow` | `false` | `zer0Cms.governance.publishAllow` | The master switch. |
| `bannedPatternsFile` | `""` | `zer0Cms.governance.bannedPatternsFile` | Extra brand-guard patterns. |
| `target` | `"jekyll"` | `zer0Cms.governance.target` | Which publish target turns an approved draft into content. |

A draft's status is one of `pending`, `approved`, `published`. Set `acceptStatuses` to `["approved"]` to force the in-editor approval step; `[]` is not a way to block everything (§1.3) — turn `publishAllow` off instead, which blocks the panel, the dashboard, the command palette *and* the bundled MCP server at once.

`bannedPatternsFile` points at a JSON array that **adds** to the 13 built-in bans:

```json
[
  { "name": "internal codename", "pattern": "project\\s+kestrel", "flags": "i" },
  { "name": "old brand", "pattern": "zer0\\s*cms\\s*classic" }
]
```

`name` and `pattern` are required strings; `flags` defaults to `"i"` and has `g`/`y` stripped so a pattern cannot carry state between checks. Every failure mode — unset, missing file, malformed JSON, invalid regex — degrades to "no extra rules": a broken addition must never brick previewing, approving or publishing, and the built-in bans still run. Use **zer0-CMS: Run brand guard** if you want the load error reported instead of swallowed.

`target` accepts the id of a registered `PublishTarget`. Exactly one ships — `jekyll`, which writes the file and records the ledger entry — and any other id fails loudly with `unknown publish target 'x' (known: jekyll)` rather than silently doing nothing.

### 3.16 `cms`

Where the `.cms/` contract lives and how to run the Python content engine that produces it. All five have settings twins, and the interpreter is the setting you will actually reach for.

| Property | Default | VS Code twin |
|---|---|---|
| `root` | `".cms"` | `zer0Cms.cms.root` |
| `python` | `"python3"` | **`zer0Cms.cms.pythonPath`** |
| `engineScript` | `"scripts/cms/cms.py"` | `zer0Cms.cms.engineScript` |
| `normalizerScript` | `"scripts/content/normalize-frontmatter.py"` | `zer0Cms.cms.normalizerScript` |
| `contentDirs` | `["pages/"]` | `zer0Cms.cms.contentDirs` |

The name differs on purpose across the two surfaces: the setting is `zer0Cms.cms.pythonPath` (which is what a person looks for in the Settings UI), the `zer0.json` key is `cms.python`. Everything else matches one-to-one.

A repository with no `.cms/` is a normal state, not an error — the extension falls back to a filesystem scan and reports less.

### 3.17 `agent`

The optional AI layer. Off unless you turn it on, and it needs the optional `@anthropic-ai/claude-agent-sdk` package plus a Claude credential.

| Property | Default | VS Code twin |
|---|---|---|
| `enabled` | `false` | `zer0Cms.agent.enabled` |
| `model` | `"claude-opus-5"` | `zer0Cms.agent.model` |
| `maxTurns` | `40` | `zer0Cms.agent.maxTurns` |
| `permissionMode` | `"default"` | `zer0Cms.agent.permissionMode` |

`permissionMode` is `default`, `acceptEdits` or `plan`. The settings layer validates it against those three; the `zer0.json` layer accepts any string and hands it to the SDK, which is deliberate — an unknown mode degrades to the SDK's own handling rather than a type error. `default` routes every mutating tool call through an approve/deny card showing the diff.

### 3.18 `validation`, `panel`, `dashboard`

| Key | Default | VS Code twin | Meaning |
|---|---|---|---|
| `validation.enabled` | `true` | `zer0Cms.validation.enabled` | Report empty required fields as diagnostics. Off means the panel, the Problems panel and the MCP status tool all stop reporting them, together. |
| `panel.openOnSupportedFile` | `false` | `zer0Cms.panel.openOnSupportedFile` | Reveal the panel when a supported file is opened. |
| `panel.freeformTaxonomy` | `true` | `zer0Cms.panel.freeformTaxonomy` | Allow creating taxonomy values from the panel (§3.6). |
| `panel.sections` | `["governance", "metadata", "seo", "actions", "recent", "other"]` | `zer0Cms.panel.sections` | Which sections exist, **in order**. |
| `dashboard.openOnStartup` | `false` | `zer0Cms.dashboard.openOnStartup` | Open the dashboard when the workspace loads. |
| `dashboard.defaultView` | `"grid"` | `zer0Cms.dashboard.defaultView` | `grid`, `list` or `structure`. |
| `dashboard.defaultSorting` | `"LastModifiedDesc"` | `zer0Cms.dashboard.defaultSorting` | One of the six sort ids in §5. |
| `dashboard.pageSize` | `16` | `zer0Cms.dashboard.pageSize` | Items per page; `0` disables pagination. Range 0–52. |
| `dashboard.cardFields` | `{"state": true, "date": true}` | `zer0Cms.dashboard.cardFields` | Which chips a card shows. |

`panel.sections` accepts seven ids: `governance`, `metadata`, `seo`, `actions`, `recent`, `settings`, `other`. **`settings` is valid but not in the default list** — add it to get the four global toggles inside the panel. Unknown ids are dropped rather than rendered as an empty section, and an empty array falls through to the default (§1.3).

`dashboard.cardFields` is an object of booleans, and only the two members above do anything — any other key is inert. It is replaced wholesale, not merged, so write both members when you set it.

### 3.19 `logging`

| Key | Default | VS Code twin |
|---|---|---|
| `logging.level` | `"info"` | `zer0Cms.logging.level` |

`error`, `warn`, `info` or `verbose`, controlling the "zer0-CMS" output channel. The threshold is read at the moment each line is written, so changing it takes effect on the next line rather than the next window.

**Set this one in VS Code settings.** The logger reads `zer0Cms.logging.level` directly rather than the resolved configuration, so a `logging.level` in `zer0.json` is parsed, validated and then never consulted by the output channel. An unrecognised value degrades to `info` — a typo in the setting must not silence the log line that would tell you about the typo.

---

## 4. Placeholder tokens

`{{…}}` tokens are resolved in field `default` values on creation, in filename prefixes (`content.filePrefix`, a folder's, a content type's), in content-folder paths (date vocabulary only), and in slug templates (time and front-matter vocabulary only).

| Token | Resolves to |
|---|---|
| `{{now}}` | now, formatted with `date.format` — a raw ISO timestamp when that format is empty |
| `{{year}}` `{{month}}` `{{day}}` | `yyyy` `MM` `dd` in `date.timezone` |
| `{{hour12}}` `{{hour24}}` `{{minute}}` `{{second}}` `{{ampm}}` | `hh` `HH` `mm` `ss` `aaa` |
| `{{date\|<pattern>}}` | now, in an ad-hoc pattern — `{{date\|yyyy/MM}}` |
| `{{title}}` | the article's title field, else the title being entered |
| `{{slug}}` | the slug that title produces under the content type's template |
| `{{fm.<key>}}` | a front-matter value; a list renders as `a, b`. Looked up by literal key first, then as a dotted path |
| `{{fm.<key> \| format:'<pattern>'}}` | that value parsed as a date and re-formatted |
| `{{pathToken.<n>}}` | the n-th segment of the workspace-relative file path |
| `{{pathToken.relPath}}` | the file's directory relative to its content folder |
| `{{filePrefix.index}}` | the number of content files already in the target folder, plus one, zero-padded to 3 |
| `{{filePrefix.index\|zeros:<n>}}` | the same, padded to `<n>`; `zeros:0` leaves it unpadded |
| `{{<id>}}` | a `placeholders[]` entry (§3.12) |

Two rules govern the whole vocabulary. **An unresolvable token is left alone** — a missing front-matter key leaves `{{fm.author}}` sitting in the output rather than collapsing to an empty string, because a visible `{{` is a bug somebody fixes and a silently-missing path segment is a bug nobody notices until two files collide. And there is **one pipeline order**, everywhere: article → front matter → path → file index → custom → time → `{{date|…}}`.

`[[workspace]]` is not one of these. It is a path token, expanded by the config resolver in any configured path (content folders, scripts, drafts folder, ledger, templates), and `contentFolders` keeps the spelling you typed so a round-trip back into `zer0.json` writes `[[workspace]]/pages`, not an absolute path.

Inside a **slug template** `{{title}}` means something narrower than it does elsewhere — the else-if chain in §3.11 resolves it first, as "lowercased with spaces turned into dashes". `{{seoTitle}}`, `{{fileName}}`, `{{sluggedFileName}}` and `{{slugifiedFileName}}` exist only there.

A content type's `template` seeds front-matter *values*, which are placeholder-expanded; the template's body is copied verbatim.

---

## 5. VS Code settings

All 35, exactly as `package.json` contributes them. None of these describe the project — that is what the split in §6 is about.

### Project file

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.configFile` | `"zer0.json"` | Workspace-relative path of the project config file. The only setting with `resource` scope, so a multi-root workspace can point each folder at its own. |

### Panel

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.panel.openOnSupportedFile` | `false` | Reveal the panel when a supported content file is opened. |
| `zer0Cms.panel.freeformTaxonomy` | `true` | Allow tags and categories not yet in the taxonomy to be created from the panel — which writes them into `zer0.json`. |
| `zer0Cms.panel.sections` | `["governance", "metadata", "seo", "actions", "recent", "other"]` | Which panel sections to render, in order. Allowed ids: `governance`, `metadata`, `seo`, `actions`, `recent`, `settings`, `other`. |

### Dashboard

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.dashboard.openOnStartup` | `false` | Open the dashboard when the workspace loads. |
| `zer0Cms.dashboard.defaultView` | `"grid"` | Initial layout of the Contents view: `grid`, `list`, `structure`. |
| `zer0Cms.dashboard.defaultSorting` | `"LastModifiedDesc"` | Initial sort: `LastModifiedDesc`, `LastModifiedAsc`, `FileNameAsc`, `FileNameDesc`, `PublishedDesc`, `PublishedAsc`. |
| `zer0Cms.dashboard.pageSize` | `16` | Items per page (0–52). `0` disables pagination. |
| `zer0Cms.dashboard.cardFields` | `{"state": true, "date": true}` | Which optional chips a content card shows. |

### Content

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.content.autoUpdateModifiedDate` | `false` | Stamp the content type's `isModifiedDate` field on every save. |
| `zer0Cms.content.preserveCasing` | `false` | Keep the original casing when generating a filename, and when sanitizing an explicit publish slug. |
| `zer0Cms.content.defaultFileType` | `"md"` | Extension used for newly created content. |
| `zer0Cms.content.supportedFileTypes` | `["md", "mdx", "markdown"]` | File extensions treated as content. |
| `zer0Cms.content.publicFolder` | `""` | Workspace-relative folder served at the site root — used to resolve image paths. |

### Dates

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.date.format` | `"yyyy-MM-dd"` | Date format for front-matter date fields. |
| `zer0Cms.date.timezone` | `"UTC"` | IANA time zone used when formatting and parsing. |

### SEO and validation

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.seo.enabled` | `true` | Show the SEO insights section in the panel. The thresholds themselves live in `zer0.json`. |
| `zer0Cms.validation.enabled` | `true` | Report missing required fields as diagnostics in the Problems panel. |

### Governance

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.governance.enabled` | `true` | Enable the governed draft queue. |
| `zer0Cms.governance.draftsFolder` | `".zer0/drafts"` | Workspace-relative folder holding the queue. |
| `zer0Cms.governance.ledgerPath` | `".zer0/ledger.json"` | Workspace-relative path of the idempotency ledger. |
| `zer0Cms.governance.acceptStatuses` | `["pending", "approved"]` | Draft statuses the publish path accepts. Restrict to `["approved"]` to require the in-editor approval step. |
| `zer0Cms.governance.publishAllow` | `false` | Master switch. While off, publishing is blocked in the panel, the dashboard, the command palette **and** the bundled MCP server. Arming the MCP server reads *this setting only* — `zer0.json` can enable publishing for the editor's own gates but never for an agent. |
| `zer0Cms.governance.bannedPatternsFile` | `""` | Optional workspace-relative JSON file of extra brand-guard patterns. |
| `zer0Cms.governance.target` | `"jekyll"` | Publish target that turns an approved draft into published content. |

### Content engine

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.cms.root` | `".cms"` | Workspace-relative root of the `.cms/` contract. |
| `zer0Cms.cms.pythonPath` | `"python3"` | Python interpreter used to run the engine. `machine-overridable`, so a machine value can be overridden per workspace. |
| `zer0Cms.cms.engineScript` | `"scripts/cms/cms.py"` | Workspace-relative path of the engine script. |
| `zer0Cms.cms.normalizerScript` | `"scripts/content/normalize-frontmatter.py"` | Workspace-relative path of the mechanical front-matter normalizer. |
| `zer0Cms.cms.contentDirs` | `["pages/"]` | Directories the engine scans. |

### AI agent

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.agent.enabled` | `false` | Enable the optional AI agent. Requires the `@anthropic-ai/claude-agent-sdk` optional dependency and a Claude credential. |
| `zer0Cms.agent.model` | `"claude-opus-5"` | Model the agent runs on. |
| `zer0Cms.agent.maxTurns` | `40` | Maximum agent turns per run (minimum 1). |
| `zer0Cms.agent.permissionMode` | `"default"` | `default`, `acceptEdits` or `plan`. `default` routes every mutating tool through an approve/deny gate. |

### Logging

| Setting | Default | What it does |
|---|---|---|
| `zer0Cms.logging.level` | `"info"` | Verbosity of the zer0-CMS output channel: `error`, `warn`, `info`, `verbose`. |

### Settings the UI writes for you

Nine of these are also editable from a webview, and every one of them is written to **workspace** scope (`.vscode/settings.json`), never to your user settings:

- The dashboard's General tab: `dashboard.openOnStartup`, `dashboard.defaultView`, `dashboard.defaultSorting`, `dashboard.pageSize`, `dashboard.cardFields.state`, `dashboard.cardFields.date`, `content.autoUpdateModifiedDate`, `panel.openOnSupportedFile`, `seo.enabled`, `agent.enabled`.
- The panel's **Global settings** section (add `settings` to `panel.sections` to see it): `content.autoUpdateModifiedDate`, `panel.openOnSupportedFile`, `seo.enabled`, `agent.enabled`.

Nothing else is writable from a webview. The message posts a key and a value, and the host looks that key up in a fixed table before it writes anything — a webview names a preference, it never carries a path into the settings store.

---

## 6. Which layer should this go in?

Ask who else needs the answer.

**Put it in `zer0.json` when it describes the project.** Content folders, content types and their fields, field groups, taxonomy, the draft field, the front-matter dialect, the slug template, SEO thresholds and placeholders have no settings twin at all — they are the same for every person who clones the repo, they belong in review, and they are the half that other tools read. The bundled MCP server resolves its configuration from `zer0.json` and the defaults **only** — no VS Code setting reaches it, bar the publish flag it is handed as an environment variable (below) — so anything a model, a CI lane or a `node dist/mcp-server.js` needs has to be in the file.

**Put it in VS Code settings when it describes you or your machine.** `cms.pythonPath` is the clearest case — your interpreter is not your team's. So are `panel.openOnSupportedFile`, `dashboard.pageSize`, `logging.level`, and anything you want to try without dirtying the working tree.

**Put it in *both* when you want a project default a person can override.** This is what the layering is for: `zer0.json` sets `"governance": {"acceptStatuses": ["approved"]}` as the project's stance, and someone working through a backlog locally can relax it in their own settings without committing anything. It works in the other direction too — a project can ship `"dashboard": {"defaultView": "structure"}` and anyone who prefers the grid overrides it for themselves.

**Two keys are settings-only in practice.** `zer0Cms.configFile` names the file, so it cannot live in it. `logging.level` is read straight from the settings by the output channel (§3.19).

**Two things belong in neither.** The MCP server's publish gate is an environment variable, `ZER0_CMS_MCP_ALLOW_PUBLISH=1`, plus `confirm: true` on the call. Inside that process the resolved `governance.publishAllow` is pinned to the variable, whatever `zer0.json` says — so a config file claiming `true` cannot let a hand-run server publish, and the core gate and the MCP gate cannot disagree. When VS Code launches the server it passes the flag exactly when `governance.enabled` is on (that one is read from the merged configuration, because a `zer0.json` turning governance *off* is a restriction and honouring a restriction from the project file is always safe) **and** `zer0Cms.governance.publishAllow` is set to `true` in the **settings** layer — user, workspace or folder scope. A `zer0.json` cannot arm it. That is the one place where the file layer deliberately loses: past this variable, `zer0_publish`'s only other gate is `confirm: true`, which a model supplies to itself, so a repository that ships `{"governance":{"publishAllow":true}}` would otherwise be enough to publish with no human act in the chain. The in-editor gates keep reading the merged value; they are behind a modal. The flag is re-resolved every time the server starts. `ZER0_CMS_CONFIG` names the config file for that process, the way `zer0Cms.configFile` does for the editor. And the Claude credential the optional agent needs lives in VS Code's secret storage — never in a setting, never in `zer0.json`.

---

## 7. A full example

```jsonc
{
  "$schema": "./schemas/zer0.schema.json",

  "contentFolders": [
    { "title": "Posts", "path": "[[workspace]]/pages/_posts", "contentTypes": ["post"] },
    { "title": "Docs", "path": "[[workspace]]/pages/docs", "contentTypes": ["doc"], "filePrefix": null }
  ],

  "contentTypes": [
    {
      "name": "post",
      "slugTemplate": "{{year}}/{{seoTitle}}",
      "filePrefix": "{{date|yyyy-MM-dd}}",
      "fields": [
        { "name": "title", "type": "string", "single": true, "required": true },
        { "name": "description", "type": "string", "required": true },
        { "name": "date", "type": "datetime", "default": "{{now}}", "isPublishDate": true },
        { "name": "lastmod", "type": "datetime", "isModifiedDate": true },
        { "name": "preview", "type": "image", "isPreviewImage": true },
        { "name": "draft", "type": "draft" },
        { "name": "tags", "type": "tags", "taxonomyLimit": 5 },
        { "name": "categories", "type": "categories" },
        { "name": "audience", "type": "taxonomy", "taxonomyId": "audience" },
        { "type": "divider", "name": "sep1" },
        { "type": "heading", "name": "seoHeading", "title": "Search", "description": "Optional overrides." },
        { "name": "seo", "type": "fieldCollection", "fieldGroup": "seoBlock" },
        {
          "name": "unsplashId", "type": "string",
          "when": { "fieldRef": "imageSource", "operator": "eq", "value": "unsplash" }
        }
      ]
    },
    { "name": "doc", "fields": [
      { "name": "title", "type": "string", "required": true },
      { "name": "related", "type": "contentRelationship", "contentTypeName": "post", "contentTypeValue": "slug" }
    ] }
  ],

  "fieldGroups": [
    { "id": "seoBlock", "labelField": "seoTitle", "fields": [
      { "name": "seoTitle", "type": "string", "single": true },
      { "name": "seoDescription", "type": "string" }
    ] }
  ],

  "taxonomy": {
    "tags": ["automation", "jekyll"],
    "categories": ["engineering"],
    "custom": [{ "id": "audience", "options": ["beginner", "operator"] }]
  },

  "draftField": { "name": "draft", "type": "boolean" },
  "frontMatter": { "format": "yaml", "indentArrays": false, "commaSeparatedFields": ["tags"] },
  "content": { "defaultFileType": "md", "publicFolder": "assets", "filePrefix": "" },
  "seo": { "titleLength": 60, "descriptionLength": 160, "slugLength": 75, "contentLength": 1200 },
  "slug": { "template": "{{seoTitle}}", "alignFilename": true },
  "placeholders": [{ "id": "author", "value": "Amr" }],
  "date": { "format": "yyyy-MM-dd", "timezone": "America/Phoenix" },
  "governance": { "acceptStatuses": ["approved"], "bannedPatternsFile": ".zer0/banned.json" },
  "cms": { "root": ".cms", "contentDirs": ["pages/"] },
  "validation": { "enabled": true }
}
```

The matching `.vscode/settings.json`, holding only what is about this machine:

```json
{
  "zer0Cms.cms.pythonPath": "${workspaceFolder}/.venv/bin/python",
  "zer0Cms.panel.openOnSupportedFile": true,
  "zer0Cms.dashboard.pageSize": 24,
  "zer0Cms.logging.level": "verbose"
}
```

---

## See also

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the layer boundary these two surfaces resolve behind.
- [`../schemas/zer0.schema.json`](../schemas/zer0.schema.json) — the authoritative shape of `zer0.json`, and what validates it as you type.
- [`../src/core/shared/config.ts`](../src/core/shared/config.ts) — the resolver, including every default.
- [`../src/config.ts`](../src/config.ts) — the settings layer and the `inspect()` rule.
