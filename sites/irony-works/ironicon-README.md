# Ironicon

### The perpetual encyclopedia of irony

> Expectation, reversed. Recursively.

**Ironicon** is a self-growing Obsidian vault that catalogs irony in all its forms — past, present, and pending — tended by an AI engine and published to the web with the [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme. It is a seed, not a site: clone it, plant it, and the germination cycle takes over.

An encyclopedia of irony compiled by a machine that cannot be embarrassed is either the death of the form or its final proof. This repository exists to find out.

---

## The Premise

Irony is not a mood. It is a **structure**: an expectation, articulated or assumed, and a reversal that comments on it. Rain on a wedding day is weather. A meteorologist rained out of her own wedding is closer. A meteorologist rained out of the wedding she scheduled using her own forecast — that's an entry.

Because irony has structure, it can be **verified**. Every entry in this vault is required to state its `expectation` and its `reversal` as frontmatter fields. If a candidate cannot articulate both, it is not irony — it is merely unfortunate, and it goes to the [compost](vault/compost/the-merely-unfortunate.md).

The vault is rendered by a theme named **zer0-mistakes** — a fitting frame for a catalog of humanity's most productive mistakes. The engine's own contradictions are documented in the [Hall of Mirrors](vault/mirrors/), because an encyclopedia of irony that exempted itself would fail its own gate.

## Anatomy of an Entry

```yaml
---
title: The Kodak Moment
form: [situational, historical]     # see vault/forms/
status: canon                       # seed → sapling → canon → petrified
veracity: attested                  # attested | contested | legend | speculative
era: contemporary
expectation: >
  Kodak, synonymous with photography, would own whatever photography became.
reversal: >
  Kodak invented the digital camera in 1975, shelved it to protect film,
  and was bankrupted by it in 2012.
planted: 2026-08-06
alanis: 9/10                        # gate score, threshold 7
sources: [ ... ]
---
```

The `expectation`/`reversal` pair is the load-bearing wall. It makes irony machine-checkable, deduplicable, and traversable — you can query the vault for every entry where an institution was undone by its own invention, and the graph will hand you a genre.

The `veracity` field exists because the better an irony, the harder it must be verified. Perfect anecdotes are how legends launder themselves into encyclopedias (see [[nobels-obituary]], filed under `legend` on purpose).

## How It Grows

```
 idea ──SCOUT──▶ draft ──SCRIBE──▶ ╔═════════════╗
                                   ║ ALANIS GATE ║──fail──▶ compost/
                                   ╚══════╤══════╝          (the merely
                                     pass │                  unfortunate)
                                          ▼
                            nursery/ (pull request)
                                          │
                              human merge = selection
                                          ▼
                       canon ◀──GARDENER tends: links,
                                prunes, promotes, revisits
                                futures/ as they mature
```

A scheduled **germination cycle** (`.github/workflows/germinate.yml`) runs the engine: the Scout proposes candidates from a rotating domain list, the Scribe drafts them against the templates, the Alanis Gate scores them, and survivors arrive as a pull request into `vault/nursery/`. Merging is the selection pressure. Nothing enters canon without a human hand — the machine proposes, the reader disposes.

Rejected candidates are not deleted. They are logged in the compost ledger with their verdict (`MERELY-UNFORTUNATE`, `COINCIDENCE`, `HYPOCRISY`, `BAD-LUCK`), because the negative space of irony is itself instructive.

## The Alanis Gate

Quality control is named for the most famous failure of the genre: a 1996 hit single titled after irony that lists almost none — and thereby becomes the most ironic thing about itself. The gate's rubric ([engine/prompts/alanis-gate.md](engine/prompts/alanis-gate.md)) scores five axes: genuine reversal, meaningful commentary, hindsight inevitability, specificity, and non-substitutability (it must not reduce to bad luck, coincidence, or hypocrisy). Threshold: 7/10.

The song itself passes the gate. Its scenarios do not.

## The Vault

| Folder | Contents |
|---|---|
| `vault/forms/` | The taxonomy — one note per form of irony (verbal, situational, dramatic, Socratic, cosmic, structural, historical, meta/post) |
| `vault/works/` | Annotated works: the canon of ironic literature, Sophocles to Bainbridge |
| `vault/figures/` | The ironists themselves |
| `vault/instances/` | Documented ironies of history and the present |
| `vault/mirrors/` | The Hall of Mirrors — this machine's own ironies |
| `vault/futures/` | Open positions: expectations on record, reversals pending |
| `vault/nursery/` | AI drafts awaiting review |
| `vault/compost/` | The Merely Unfortunate — rejected with verdicts |
| `vault/templates/` | Obsidian templates enforcing the schema |

Open `vault/` as an Obsidian vault. The graph view is the arboretum: forms are the trunk, everything else branches by wikilink.

## Quickstart

1. **Clone and open.** Point Obsidian at `vault/`. Start at [[Home]].
2. **Add the key.** Repo → Settings → Secrets → `ANTHROPIC_API_KEY`. The engine defaults to `claude-sonnet-4-6` via the [Claude API](https://docs.claude.com/en/api/overview); swap the harness block in `engine/seed.config.yml` to route through lifehacker.dev instead.
3. **Enable Actions + Pages.** Germination runs weekly (or on dispatch, with a `count` input). Publishing builds the vault through zer0-mistakes on every push to `main`.
4. **Merge what deserves to live.** That's the whole job.

## Governance (hard guardrails)

The engine may write **only** to `vault/nursery/` and the compost ledger. It may never modify canon entries, its own prompts, the workflows, or this file. Promotion, pruning of canon, and rule changes are human-only. These constraints are enforced in the scripts by path whitelist, not by politeness.

## Publishing

`_config.yml` uses `remote_theme: bamr87/zer0-mistakes`. The publish workflow first runs `engine/scripts/transplant.mjs`, which converts `[[wikilinks]]` to permalinks and moves entries into a Jekyll collection, then builds and deploys Pages. The vault stays the source of truth; the site is a pressing.

## License

Engine: MIT. Vault content: CC BY-SA 4.0. Attribution for the founding intent belongs to [the founding prompt](vault/the-founding-prompt.md), preserved verbatim as the seed's seed.
