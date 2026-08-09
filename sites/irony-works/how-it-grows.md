---
layout: default
title: How It Grows
permalink: /how-it-grows/
preview: /assets/images/previews/default.svg
description: >
  A scheduled machine proposes candidate ironies, an adversarial gate scores
  them on five axes, and survivors arrive as a pull request. Merging is the
  selection pressure — nothing reaches canon without a human hand.
---

The vault grows on a cycle. The machine proposes; the reader disposes.

```
 idea ──SCOUT──▶ candidate ──▶ ╔═════════════╗
                               ║ ALANIS GATE ║──fail──▶ compost/
                               ╚══════╤══════╝          (the merely
                                 pass │                  unfortunate)
                                      ▼
                           SCRIBE ──▶ nursery/ (pull request)
                                      │
                          human merge = selection
                                      ▼
                                    canon
```

## The five roles

**Scout** proposes candidates for the cycle's domain — history of science,
literature and language, technology, politics, commerce, or the vault itself.
It is rewarded for one true irony and penalised for five plausible ones.

**The [Alanis Gate]({{ '/entries/alanis-gate/' | relative_url }})** scores each
candidate 0–2 on five axes — reversal, commentary, inevitability, specificity,
and non-substitutability — and rejects anything that reduces to bad luck,
coincidence, hypocrisy, or plain tragedy. Threshold is 7 of 10.

**Scribe** drafts the survivors against the entry schema, with sources, and
downgrades `veracity` when the evidence is thin rather than sharpening the
story to match the telling.

**Linker** weaves new entries into the graph, and **Gardener** tends it —
deduplicating, chasing orphans, and revisiting
[futures]({{ '/futures/' | relative_url }}) as they mature.

## What the gate throws away

The rejects are kept. Every failed candidate is logged in the
[compost ledger]({{ '/compost/' | relative_url }}) with its verdict:
`MERELY-UNFORTUNATE`, `BAD-LUCK`, `COINCIDENCE`, `HYPOCRISY`, or
`NOT-EVEN-WRONG`. The negative space of a definition teaches as much as the
definition — and history occasionally files an appeal.

## Veracity, because good stories lie

Every entry carries a rating: `attested`, `contested`, `legend`, or
`speculative`. The better an anecdote, the more likely history has sharpened
it. A pipeline that harvests great stories without a veracity axis will
launder legends into an encyclopedia at machine speed, so the vault flags
uncertainty as first-class metadata rather than quietly inheriting it.

## The guardrails are code, not etiquette

The engine may write to exactly two places: the
[nursery]({{ '/nursery/' | relative_url }}) and the compost ledger. It cannot
modify canon, its own prompts, the workflows, or the configuration — the
restriction is a path whitelist enforced by a function that throws, not a
sentence in a prompt asking nicely.

Promotion to canon happens one way: a human merges the pull request. That is
the whole governance model, and it is the reason this site can be grown by a
machine without becoming a landfill.

<p class="mt-4">
  <a class="btn btn-primary" href="{{ '/entries/' | relative_url }}">Browse every entry</a>
  <a class="btn btn-outline-secondary" href="{{ '/nursery/' | relative_url }}">See what's pending</a>
</p>
