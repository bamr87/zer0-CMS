# `src/webview/panel/fields/` — the eighteen field controls

Every control the Metadata section can draw. The panel host (`../metadata.ts`)
calls exactly one function from here; everything else in this directory is an
implementation detail of a single field type.

```
index.ts     registry, dispatcher, shared chrome, value helpers   (~470 LOC)
inputs.ts    string · number · boolean · draft · datetime · slug · list
pickers.ts   choice · tags · categories · taxonomy · contentRelationship
media.ts     image · file
groups.ts    fields · fieldCollection · divider · heading, and the `when` port
```

## The one entry point

```ts
import { createField } from './fields';

const widget = createField({ field, parents: [], value, state, msg, onChange });
if (widget === null) {
  continue;            // hidden, `when` is false, or the type has no factory
}
host.appendChild(widget.el);
```

`createField` (an alias for `createFieldWidget`) returns `FieldWidget | null`.
`null` means **render nothing**, and covers exactly three cases:

| case | logged? |
|---|---|
| `field.hidden === true` | no — it is a configuration choice, not a problem |
| a `when` clause that evaluates false | no |
| a `field.type` with no registered factory | yes, `warn` |

It never throws. Neither does the widget it returns: `setValue`, `setLoading`,
`setError`, `focus` and `dispose` are all wrapped, because one field with a bad
value must not take the snapshot render down with it.

## The contract

`FieldWidget` and `FieldContext` are defined in `../../shared/protocol.ts`, not
here — the panel and the widgets agree on them through the wire module so
neither imports the other's internals.

Callers must call `dispose()` before dropping a widget. Element-local listeners
die with their nodes, but three things outlive them and are released only by
`dispose()`: `document`-level outside-click handlers (every dropdown), the
`Messenger.onMessage` subscription (the tag pickers' focus command), and pending
debounce timers. `../metadata.ts` disposes the whole live list on every render.

## Shared chrome (`index.ts`)

`fieldShell(ctx, options)` builds everything that is not the control:

- `.field__title` — codicon, label, optional lighter-weight suffix
  (`" (Max.: 3)"`), and the required asterisk.
- The mutually exclusive message: `The <label> field is required` (in the error
  colour) **or** `field.description`. Required always wins.
- `.metadata_field__loading` — the blurred overlay, driven by `setLoading()`.
- `.metadata_field__error` — the message plus a **Retry** button.
- `.required` and `.is-warning` on the `.metadata_field` root, which is what the
  three-state input border in `media/panel.css` keys off.

`FIELD_FACTORIES` is a `Record<FieldType, FieldFactory>`, so adding a type to
`core/shared/types.ts` without a control here is a compile error.

## Decisions worth knowing before you edit

**The webview never gates anything.** A tag pill's `+` posts
`{type:'addTaxonomy', kind, value}`; the host decides whether to write it. No
control here reads or enforces a permission.

**Nested edits are leaf-addressed.** A field inside a `fields` group posts
`updateField(['seo','title'], value)`, not a rebuilt copy of the whole group
object. `FieldContext.parents` exists to be joined with the field name into that
path, and decision D7's line surgery then rewrites one line.

**Two things are restated from the core rather than imported.**
`core/content/fields.ts` reaches `core/content/placeholders.ts`, which imports
`node:child_process` — it cannot be bundled for a browser. So `labelOf`, the
emptiness test, the `<failed to process>` sentinel and `evaluateWhen` are
restated here. They are kept in step by review, not by the type system; if you
change one, change both. Everything else pure (`core/shared/dates.ts`,
`core/shared/text.ts`) *is* imported.

**Character budgets are derived, not configured.** `PanelState.seo` carries no
`titleLength`/`descriptionLength`, so `limitForField` reads the budget out of the
matching insights row's `recommendation` (`"60 chars"`) and falls back to 60/160.
Adding the two numbers to `SeoState` would make this exact; the fallback exists
so a project with SEO insights switched off still gets sensible counters.

**Media previews are best-effort.** `pickImage`/`pickFile` hand back a workspace
path, and a webview cannot load one without an `asWebviewUri` round trip that the
request vocabulary in PLAN §4.3 has no operation for. The preview sets the raw
value as the `src` and swaps in the fallback box on `error`, with the path shown
underneath. A `resolveMedia` request op would upgrade this in one place.

## Deliberate omissions

`json`, `block`, `dataFile`, `customField` and the `wysiwyg` string variant are
**not** field types in zer0-CMS (PLAN decision D6). Each one cost a runtime
dependency — a JSON-Schema form engine, a drag-sort library, a rich-text editor —
or, in `customField`'s case, injected workspace-authored markup into the panel.
Do not add them back without re-reading §3.1.

`draft` reads its shape from the field rather than from configuration: a `draft`
field that declares `choices` renders as a choice, everything else as a toggle.
`PanelState` carries no `draftField` block, and a host that configures
`draftField.type = "choice"` has to send the choices anyway.

## Testing

There is no DOM in the unit test lane, so these widgets are exercised by
bundling them against a small hand-rolled DOM and driving real events. The
properties that matter: all eighteen types build, an unknown type returns `null`
and logs, a throwing factory produces the Retry row instead of propagating, and
500 mount/dispose cycles leave zero `document` listeners and zero messenger
subscriptions behind.
