---
name: check-lifecycle
description: "Gate every growth tick of this self-growing knowledge base: decide whether the next run should grow, replant (spawn a successor repo), or consolidate the lineage. Use at the start of each /grow tick, after a tick completes to reconcile the counter, or whenever lifecycle state may have drifted from seed.md §8. Concept-agnostic — reads policy and state from lifecycle.yml and tick history from seed.md. Writes lifecycle.yml only."
---

# Check Lifecycle

Decide which **phase** the next run of this repository should execute: `grow`, `replant`, or
`consolidate`. This skill is the gate at the start of every tick and the reconciler at the end of
one. It never grows content, spawns repos, or consolidates anything itself — it only reads state,
repairs the counter, and reports a decision.

## Inputs

- [lifecycle.yml](../../../lifecycle.yml) — policy knobs (`replant_after_ticks`,
  `consolidate_at_members`, succession/consolidation rules) and current state.
- [seed.md](../../../seed.md) §8 Evolution Log — the source of truth for tick history.

## Procedure

1. **Read** `lifecycle.yml`. If it does not exist, create it from the template documented in
   [LIFECYCLE.md](../../../LIFECYCLE.md), inferring `lineage` from the seed's Identity section and
   `generation_ticks` from step 2.
2. **Count generation ticks** from seed.md §8: the number of growth-tick entries (entries titled
   `Tick N: …`) appended **after** the most recent `Genesis` or `Replant` entry. Reconcile
   `state.generation_ticks` to this count — §8 wins over the YAML on any disagreement.
3. **Decide the phase**, in priority order:
   - `consolidate` — if `state.lineage` (excluding `state.origin`) has ≥ `consolidate_at_members`
     entries, this repo is the **newest** lineage member, and `state.status` is not already
     `consolidated`.
   - `replant` — if `state.generation_ticks` ≥ `replant_after_ticks` and `state.status` is
     `growing`.
   - `grow` — otherwise. Also `grow` if status is `mature`/`consolidated` only when the caller
     explicitly forces it; by default a mature repo reports `dormant` (no action).
4. **Write back** the reconciled `state.generation_ticks` (and nothing else — phase transitions are
   written by the `replant` / `consolidate` prompts, not by this skill).

## Output Format

A single decision block:

```
## Lifecycle Decision

**Phase**: grow | replant | consolidate | dormant
**Generation ticks**: <n> / <replant_after_ticks>
**Lineage size**: <m> / <consolidate_at_members>
**Reason**: <one line>
**Next**: <run a normal tick | run the replant prompt | run the consolidate prompt | nothing — repo is mature/consolidated>
```
