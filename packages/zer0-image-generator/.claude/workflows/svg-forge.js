export const meta = {
  name: 'svg-forge',
  description: 'Draft, critique, and refine an SVG from a text brief using the tools/svg style library',
  whenToUse: 'When asked to produce a polished SVG image from a brief: parallel style-diverse drafts, svg-critic scoring, winner refined over rounds, strict-lint finalize',
  phases: [
    { title: 'Direct', detail: 'pick styles + library references for each draft' },
    { title: 'Draft', detail: 'parallel drafts, each self-looped through lint + render' },
    { title: 'Critique', detail: 'svg-critic scores each draft as it lands' },
    { title: 'Refine', detail: 'winner improved one variable per round' },
    { title: 'Finalize', detail: 'strict lint, optional svgo, hand-off' },
  ],
}

let A = args
if (typeof A === 'string') {
  try { A = JSON.parse(A) } catch (e) { throw new Error('svg-forge args arrived as a non-JSON string') }
}
// The package root, relative to the session's working directory. No machine
// path is baked in: pass args.root when the session does not start there
// (e.g. 'packages/zer0-image-generator' from the zer0-CMS monorepo root).
const ROOT = (A && A.root) || '.'
// The production loop's engine. Finalize runs its SHAPE step (`--shape`) so
// the dev forge and the grow tick's illustration loop gate on ONE code path.
const ENGINE = `${ROOT}/lib/zer0_image_generator/preview_generator.py`
const brief = A && A.brief
if (!brief) throw new Error('svg-forge needs args.brief (a one-paragraph art brief)')
const OUT = (A && A.out) || '.sweep/forge/final.svg'
const N = (A && A.drafts) || 3
const ROUNDS = (A && A.rounds) || 2
const FORCED_STYLE = (A && A.style) || null

const DIRECTIONS_SCHEMA = {
  type: 'object', required: ['directions'],
  properties: {
    directions: { type: 'array', items: { type: 'object',
      required: ['style_card', 'palette_hint', 'references', 'notes'],
      properties: {
        style_card: { type: 'string', description: 'repo-relative path of the style card to follow' },
        palette_hint: { type: 'string' },
        references: { type: 'array', items: { type: 'string' }, description: 'repo-relative exemplar files worth reading first' },
        notes: { type: 'string', description: 'composition direction specific to this draft' },
      } } },
  },
}

const DRAFT_SCHEMA = {
  type: 'object', required: ['file'],
  properties: { file: { type: 'string' }, notes: { type: 'string' } },
}

// Same shape as CRITIQUE_SCHEMA in the engine (lib/zer0_image_generator/
// svg/critique.schema.json) — the production loop's critic returns exactly
// this; test/test_illustration_loop.py pins the required keys equal.
const CRITIQUE_SCHEMA = {
  type: 'object', required: ['works', 'fails', 'next_change', 'overall', 'thumbnail_holds'],
  properties: {
    works: { type: 'string' },
    fails: { type: 'array', items: { type: 'string' } },
    next_change: { type: 'string', description: 'exactly one actionable edit' },
    overall: { type: 'number', description: '0-10, be stingy: 8+ means shippable as-is' },
    thumbnail_holds: { type: 'boolean', description: 'silhouette still reads at 120px' },
  },
}

const FINAL_SCHEMA = {
  type: 'object', required: ['out', 'size_kb', 'strict_clean'],
  properties: { out: { type: 'string' }, size_kb: { type: 'number' }, strict_clean: { type: 'boolean' }, notes: { type: 'string' } },
}

phase('Direct')
const styleLine = FORCED_STYLE
  ? `The caller REQUIRES style card ${FORCED_STYLE} for every draft — vary composition, not style.`
  : `Pick a DIFFERENT style card for each draft so the drafts explore the space; only reuse a style if fewer than ${N} cards fit the brief.`
const direction = await agent(
  `You are art-directing ${N} parallel drafts of one SVG piece.
Brief: ${brief}
Work from ${ROOT}. Read tools/svg/library/README.md, the style cards in tools/svg/library/styles/, and skim tools/svg/library/MANIFEST.json for exemplars whose tags fit the brief.
If the brief names a concrete subject, also check FreeSVG's CC0 catalog for existing base art: run python3 tools/svg/freesvg.py status — when credentials are set, search "<subject>" (cache-first, so repeats are free), fetch the 1-2 most promising ids, and include the printed local cache paths in that draft's references, noting they are CC0 and may be adapted. When credentials are missing, skip this silently.
${styleLine}
For each draft return: style_card (path), palette_hint (concrete tokens or palette name), references (1-3 exemplar files from the library or docs/samples worth reading before drawing), notes (one paragraph of composition direction — subject placement, value structure, the one deliberate symmetry break).
Return exactly ${N} directions.`,
  { label: 'direct', phase: 'Direct', schema: DIRECTIONS_SCHEMA },
)
if (!direction) throw new Error('direction agent failed')
const directions = direction.directions.slice(0, N)

const critiquePrompt = (file) =>
  `Critique ${file} against the brief: "${brief}". Work from ${ROOT}. Follow your render procedure (1000px and 120px). Score stingily.`

const judged = await pipeline(
  directions,
  (d, _orig, i) => agent(
    `Produce ONE draft SVG for this brief: ${brief}
Work from ${ROOT}. Follow the style card ${d.style_card} exactly — its Signature rules are constraints, not suggestions. Palette: ${d.palette_hint}. Composition direction: ${d.notes}
First Read the style card and these references: ${d.references.join(', ')}
References under tools/svg/library/cache/freesvg/ are CC0 public-domain art — you may trace, simplify, or incorporate them directly, but restyle to the style card's constraints rather than pasting them verbatim.
Write the piece to .sweep/forge/draft-${i}.svg with role="img" and a <title> first child.
Then close the loop yourself at least twice: python3 tools/svg/svg-check.py <file> (fix every error), bash tools/svg/svg-render.sh <file> 800, Read the PNG, name the biggest flaw out loud, change one variable, re-render. Stop after the piece survives your own critique.
Return file (repo-relative) and notes (what you fixed during your loop).`,
    { label: `draft-${i}`, phase: 'Draft', schema: DRAFT_SCHEMA },
  ),
  (draft, d, i) => {
    if (!draft) return null
    return agent(critiquePrompt(draft.file), {
      label: `critique-${i}`, phase: 'Critique', agentType: 'svg-critic', schema: CRITIQUE_SCHEMA,
    }).then((c) => (c ? { draft, direction: d, critique: c, index: i } : null))
  },
)

const candidates = judged.filter(Boolean)
if (!candidates.length) throw new Error('no draft survived')
let best = candidates.reduce((a, b) => (b.critique.overall > a.critique.overall ? b : a))
log(`winner: draft-${best.index} (${best.direction.style_card}) at ${best.critique.overall}/10`)

phase('Refine')
let current = { file: best.draft.file, critique: best.critique }
const roundLog = []
for (let r = 1; r <= ROUNDS; r++) {
  if (current.critique.overall >= 9) { log(`round ${r}: score ${current.critique.overall}, stopping early`); break }
  const refined = await agent(
    `Refine an SVG one step. Work from ${ROOT}. Brief: ${brief}. Style card to keep obeying: ${best.direction.style_card}.
cp ${current.file} .sweep/forge/round-${r}.svg and edit ONLY the copy.
The art director's verdict on the current version — works: ${current.critique.works} | fails: ${current.critique.fails.join(' | ')} | required next change: ${current.critique.next_change}
Apply the required next change (one variable). Then lint (svg-check), render at 800, Read the PNG, and confirm the change actually improved what it was meant to improve — if it made things worse, adjust once more.
Return file (.sweep/forge/round-${r}.svg) and notes.`,
    { label: `refine-${r}`, phase: 'Refine', schema: DRAFT_SCHEMA },
  )
  if (!refined) { roundLog.push({ round: r, kept: false, note: 'refiner failed' }); continue }
  const rescore = await agent(critiquePrompt(refined.file), {
    label: `rescore-${r}`, phase: 'Refine', agentType: 'svg-critic', schema: CRITIQUE_SCHEMA,
  })
  if (rescore && rescore.overall >= current.critique.overall) {
    current = { file: refined.file, critique: rescore }
    roundLog.push({ round: r, kept: true, overall: rescore.overall })
  } else {
    roundLog.push({ round: r, kept: false, overall: rescore ? rescore.overall : null })
  }
}

phase('Finalize')
const fin = await agent(
  `Finalize an SVG for hand-off. Work from ${ROOT}.
Source: ${current.file} -> destination: ${OUT} (mkdir -p its directory).
1. cp ${current.file} ${OUT}, then run the production loop's SHAPE step on it: python3 ${ENGINE} --shape ${OUT}${FORCED_STYLE ? ` --style-card ${FORCED_STYLE.replace(/^.*\//, '').replace(/\.md$/, '')}` : ''}
   It sanitizes, converts every <text> to paths with the bundled fonts, rounds precision and runs the strict lint, rewriting the file in place and printing one JSON object. Exit 0 means strict-clean.
2. If it exits 1, fix ONLY the mechanical failures it lists in ${current.file} with minimal edits — do not re-art-direct — and repeat step 1.
3. If npx is available, try npx -y svgo on a COPY of ${OUT}; keep the optimized copy only if --shape still exits 0 on it and it renders identically at a glance (render both, Read both).
4. Render ${OUT} once more, and report size_kb and strict_clean (from the --shape JSON).`,
  { label: 'finalize', phase: 'Finalize', schema: FINAL_SCHEMA },
)

return {
  out: fin ? fin.out : current.file,
  strict_clean: fin ? fin.strict_clean : false,
  chosen_style: best.direction.style_card,
  draft_scores: candidates.map((c) => ({ draft: c.index, style: c.direction.style_card, overall: c.critique.overall })),
  rounds: roundLog,
  final_critique: current.critique,
}
