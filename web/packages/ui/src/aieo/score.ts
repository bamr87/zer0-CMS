// Reading AIEO's scoring result (content/aieo/scoring.py) — an audit's
// `result`, a quick score's `result` — defensively: it is data the platform
// stores as JSON, typed by the API only as an object, so every field is
// checked before a screen shows it.

export const DIMENSIONS = ['aieo', 'seo', 'readability', 'humanity', 'cro'] as const;
export type Dimension = (typeof DIMENSIONS)[number];
export const DIMENSION_LABELS: Record<Dimension, string> = {
  aieo: 'Citability (AIEO)',
  seo: 'SEO',
  readability: 'Readability',
  humanity: 'Humanity',
  cro: 'Conversion (CRO)',
};

export interface PatternScore {
  name: string;
  score: number;
  max: number;
  detected: boolean;
  evidence: string[];
  recommendation: string;
}

export interface Gap {
  category: string;
  severity: string;
  description: string;
}

export interface Action {
  title: string;
  impact: string;
  effort: string;
  description: string;
}

export interface Improvement {
  section: string;
  current: string;
  improved: string;
}

export interface Scored {
  score: number;
  grade: string;
  method: string;
  wordCount: number;
  dimensions: Record<Dimension, number | null>;
  patterns: PatternScore[];
  gaps: Gap[];
  penalties: number;
  assessment: string;
  summary: string;
  actions: Action[];
  improvements: Improvement[];
  fallback: string;
  visual: string;
}

const record = (value: unknown): Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
const text = (value: unknown) => (typeof value === 'string' ? value : '');
const num = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const texts = (value: unknown) => list(value).filter((v): v is string => typeof v === 'string');

export const label = (name: string) => name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

/** The parts of a scoring result a screen shows, with `score` and `grade` from the row when it has them. */
export function readScore(result: unknown, row: { score?: number | null; grade?: string; scoring_method?: string } = {}): Scored {
  const r = record(result);
  const dims = record(r.dimensions);
  const patterns = Object.entries(record(r.pattern_scores)).map(([name, value]) => {
    const p = record(value);
    return { name, score: num(p.score), max: num(p.max), detected: p.detected === true, evidence: texts(p.evidence), recommendation: text(p.recommendation) };
  });
  return {
    score: row.score ?? num(r.score),
    grade: row.grade || text(r.grade),
    method: row.scoring_method || text(r.scoring_method),
    wordCount: num(r.word_count),
    dimensions: Object.fromEntries(DIMENSIONS.map((d) => [d, typeof dims[d] === 'number' ? (dims[d] as number) : null])) as Record<Dimension, number | null>,
    patterns: patterns.sort((a, b) => b.max - a.max || a.name.localeCompare(b.name)),
    gaps: list(r.gaps).map((g) => {
      const gap = record(g);
      return { category: text(gap.category), severity: text(gap.severity), description: text(gap.description) };
    }),
    penalties: num(r.anti_pattern_penalties),
    assessment: text(r.overall_assessment),
    summary: text(r.executive_summary),
    actions: list(r.priority_actions).map((a) => {
      const action = record(a);
      return { title: text(action.title), impact: text(action.impact), effort: text(action.effort), description: text(action.description) };
    }),
    improvements: list(r.sample_improvements).map((i) => {
      const item = record(i);
      return { section: text(item.section), current: text(item.current), improved: text(item.improved) };
    }),
    fallback: text(r.fallback),
    visual: text(r.visual),
  };
}

/** A site audit's pages and link map. */
export interface SitePage {
  url: string;
  title: string;
  foundBy: string;
  score: number | null;
  grade: string;
  error: string;
}

export function readPages(pages: unknown): SitePage[] {
  return list(pages).map((p) => {
    const page = record(p);
    return {
      url: text(page.url),
      title: text(page.title),
      foundBy: text(page.found_by),
      score: typeof page.score === 'number' ? page.score : null,
      grade: text(page.grade),
      error: text(page.error),
    };
  });
}

export function readLinkMap(result: unknown): { hubs: { url: string; inbound: number }[]; orphans: string[] } {
  const map = record(record(record(result).site).link_map);
  return {
    hubs: list(map.hubs).map((h) => ({ url: text(record(h).url), inbound: num(record(h).inbound) })),
    orphans: texts(map.orphans),
  };
}

export const gradeColor = (grade: string) =>
  grade.startsWith('A') ? 'teal' : grade === 'B' ? 'blue' : grade === 'C' ? 'yellow' : grade === 'D' ? 'orange' : 'red';
