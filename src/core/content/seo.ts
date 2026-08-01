/**
 * Article metrics and keyword analysis — the numbers behind the panel's "SEO
 * Status" section.
 *
 * Front Matter computed these from an mdast tree (`mdast-util-from-markdown` +
 * `unist-util-visit`). Two packages, a syntax tree and a visitor, to answer
 * "how many headings, how many words". This module answers the same questions
 * with a single left-to-right line scan and a handful of inline regexes, which
 * is what the zero-dependency rule (D3) buys: no parser to keep in step with a
 * markdown spec, and a metric pass that is cheap enough to run on every
 * keystroke of the active file.
 *
 * The line scan is deliberately CommonMark-*shaped* rather than
 * CommonMark-*compliant*. What it models, because a metric changes if it does
 * not: fenced code (skipped whole — code is not prose), ATX and setext
 * headings, list items as separate blocks, blockquote markers, inline code
 * (removed — mdast calls it `inlineCode`, not `text`, so FM never counted it),
 * image alt text (removed for the same reason), link text (kept). What it does
 * not model: four-space-indented code blocks (indistinguishable from list
 * continuation lines without a full block parser), reference-style link
 * definitions, and HTML blocks beyond "a line that starts with a tag". A line
 * holding nothing but an image counts as an image and not as a paragraph,
 * which is the one place the paragraph count deliberately reads lower than
 * mdast's: "paragraphs" is a prose-structure metric here.
 *
 * Everything here is pure: strings in, numbers out, no filesystem, no config
 * mutation, and no `Date`. The thresholds live in `Zer0Config.seo` and are the
 * FM defaults — 60/75/160 characters and 1,760 words — with FM's rule that a
 * threshold of `<= 0` switches its row off entirely.
 */

import type { ContentType, Field, Zer0Config } from '../shared/types';
import { asList, asString, type FrontMatter } from './frontmatter';

// ---------------------------------------------------------------------------
// Article details
// ---------------------------------------------------------------------------

export interface ArticleDetails {
  headings: number;
  /** The plain text of each heading, in document order. */
  headingsText: string[];
  paragraphs: number;
  images: number;
  internalLinks: number;
  externalLinks: number;
  wordCount: number;
  /** The body with `{{…}}` shortcodes removed — what every keyword check reads. */
  content: string;
  firstParagraph: string;
  /** Whole minutes at `WORDS_PER_MINUTE`. Not an FM metric; see the README. */
  readingTime: number;
}

/** Reading speed used for `ArticleDetails.readingTime`. */
export const WORDS_PER_MINUTE = 200;

/**
 * Hugo/Jekyll shortcodes, removed before anything is counted — exactly FM's
 * regex. `.` does not match a newline here, so a shortcode split across lines
 * is left alone rather than swallowing the paragraphs between its halves.
 */
const SHORTCODE_RE = /({{(.*?)}})/g;

/** Strip `{{…}}` shortcodes. Exposed because the panel shows the same body. */
export function stripShortcodes(text: string): string {
  return text.replace(SHORTCODE_RE, '');
}

const ATX_HEADING_RE = /^ {0,3}(#{1,6})(?:\s+(.*?))?\s*$/;
const SETEXT_RE = /^ {0,3}(?:=+|-+)\s*$/;
const FENCE_RE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
const LIST_ITEM_RE = /^\s*(?:[-*+]|\d+[.)])\s+/;
const BLOCKQUOTE_RE = /^\s*>\s?/;
const THEMATIC_BREAK_RE = /^ {0,3}(?:\*\s*){3,}$|^ {0,3}(?:_\s*){3,}$/;
const HTML_BLOCK_RE = /^\s*<[a-zA-Z/!?]/;

const INLINE_CODE_RE = /`+[^`]*`+/g;
const IMAGE_RE = /!\[[^\]]*\]\(\s*([^)\s]*)[^)]*\)/g;
const LINK_RE = /(!?)\[([^\]]*)\]\(\s*([^)\s]*)[^)]*\)/g;
const REF_LINK_RE = /\[([^\]]*)\]\[[^\]]*\]/g;
const AUTOLINK_RE = /<([a-zA-Z][a-zA-Z0-9+.-]*:[^>\s]*)>/g;
const HTML_TAG_RE = /<\/?[a-zA-Z][^>]*>/g;
const EMPHASIS_RE = /[*~]+/g;

/**
 * Line-level markdown removed so what is left is the text a reader sees.
 *
 * Order matters: images before links (an image is a link with a `!`), inline
 * code before everything (its content is not prose), autolinks before HTML
 * tags (an autolink looks like a tag).
 */
function toPlainText(line: string): string {
  return stripTags(
    line
      .replace(INLINE_CODE_RE, ' ')
      .replace(IMAGE_RE, ' ')
      .replace(LINK_RE, '$2')
      .replace(REF_LINK_RE, '$1')
      .replace(AUTOLINK_RE, '$1'),
  )
    .replace(EMPHASIS_RE, '')
    .replace(/\\([\\`*_{}[\]()#+\-.!])/g, '$1')
    .trim();
}

/**
 * Remove HTML tags, repeatedly, until the text stops changing.
 *
 * One pass is not enough: removing the inner match of `<<div>div>` leaves
 * `<div>`, a tag that was not there before the pass and would survive it. The
 * text this produces becomes an SEO description, which a site templates into a
 * `<meta>` tag — so "mostly stripped" is not good enough, and a single
 * `.replace()` here was a real hole rather than a theoretical one.
 *
 * The loop terminates because every iteration that changes the string removes
 * at least two characters; the bound is belt-and-braces for a pathological line.
 */
function stripTags(text: string): string {
  let out = text;
  for (let i = 0; i < 100; i += 1) {
    const next = out.replace(HTML_TAG_RE, '');
    if (next === out) {
      return out;
    }
    out = next;
  }
  return out;
}

/**
 * FM's word count, kept bug-for-bug: `value.split(' ').length` over each run of
 * text, with no filter for empty parts. Two spaces between words therefore
 * count as three words. It is wrong, it is what every existing zer0-CMS
 * threshold was tuned against, and a "fix" would silently move the 1,760-word
 * target for every article in a repository.
 */
function countWords(text: string): number {
  return text === '' ? 0 : text.split(' ').length;
}

/** Is this href internal? FM's rule: not `http`-prefixed, or on our own site. */
function isInternalHref(href: string, baseUrl: string): boolean {
  const value = href.trim().toLowerCase();
  if (!value.startsWith('http')) {
    return true;
  }
  return baseUrl !== '' && value.includes(baseUrl);
}

interface LinkCounts {
  internal: number;
  external: number;
  images: number;
}

/** Count the images and links on one raw line, before it is plain-texted. */
function countLinks(line: string, baseUrl: string, into: LinkCounts): void {
  for (const match of line.matchAll(LINK_RE)) {
    const href = match[3] ?? '';
    if (match[1] === '!') {
      into.images += 1;
      continue;
    }
    if (isInternalHref(href, baseUrl)) {
      into.internal += 1;
    } else {
      into.external += 1;
    }
  }
  for (const match of line.matchAll(AUTOLINK_RE)) {
    if (isInternalHref(match[1] ?? '', baseUrl)) {
      into.internal += 1;
    } else {
      into.external += 1;
    }
  }
}

/** Does this line close the fence opened by `marker`? */
function closesFence(line: string, marker: string): boolean {
  const match = FENCE_RE.exec(line);
  if (match === null) {
    return false;
  }
  const fence = match[1] ?? '';
  const first = marker.charAt(0);
  return fence.charAt(0) === first && fence.length >= marker.length && (match[2] ?? '').trim() === '';
}

/**
 * Every metric the SEO section shows, from one pass over the body.
 *
 * `baseUrl` is the site's own origin (e.g. `https://example.com`); links that
 * contain it count as internal even though they are absolute, which is how a
 * site that writes full URLs to its own pages avoids being told it has no
 * internal linking. Omit it and the split is purely `http`-prefix based.
 */
export function getArticleDetails(body: string, baseUrl?: string): ArticleDetails {
  const content = stripShortcodes(body);
  const base = (baseUrl ?? '').trim().toLowerCase();

  const headingsText: string[] = [];
  const counts: LinkCounts = { internal: 0, external: 0, images: 0 };
  let paragraphs = 0;
  let wordCount = 0;
  let firstParagraph = '';

  // The paragraph currently being accumulated, as plain-text lines. A setext
  // underline turns it into a heading instead, which is why it is not counted
  // until it is flushed.
  let block: string[] = [];

  const flush = (asHeading: boolean): void => {
    if (block.length === 0) {
      return;
    }
    const text = block.join(' ').trim();
    if (asHeading) {
      headingsText.push(text);
    } else {
      paragraphs += 1;
      if (firstParagraph === '') {
        firstParagraph = text;
      }
    }
    block = [];
  };

  let fence = '';

  for (const rawLine of content.split(/\r?\n/)) {
    if (fence !== '') {
      if (closesFence(rawLine, fence)) {
        fence = '';
      }
      continue;
    }

    const fenceMatch = FENCE_RE.exec(rawLine);
    if (fenceMatch !== null) {
      flush(false);
      fence = fenceMatch[1] ?? '';
      continue;
    }

    if (rawLine.trim() === '') {
      flush(false);
      continue;
    }

    // A setext underline is only an underline when there is a paragraph above
    // it; on its own, `---` or `***` is a thematic break.
    if (block.length > 0 && SETEXT_RE.test(rawLine)) {
      flush(true);
      continue;
    }
    if (THEMATIC_BREAK_RE.test(rawLine) || SETEXT_RE.test(rawLine)) {
      flush(false);
      continue;
    }

    const line = rawLine.replace(BLOCKQUOTE_RE, '');

    const atx = ATX_HEADING_RE.exec(line);
    if (atx !== null) {
      flush(false);
      countLinks(line, base, counts);
      // Trailing `###` is closing punctuation, not text.
      const text = toPlainText((atx[2] ?? '').replace(/\s*#+\s*$/, ''));
      headingsText.push(text);
      wordCount += countWords(text);
      continue;
    }

    if (LIST_ITEM_RE.test(line)) {
      // mdast gives every list item its own paragraph; so does this.
      flush(false);
    } else if (block.length === 0 && HTML_BLOCK_RE.test(line)) {
      // An HTML block has no text children and contributes nothing but its
      // links, which mdast would not count either — but a `<figure><img>` that
      // vanished from the image count would be a surprise.
      countLinks(line, base, counts);
      continue;
    }

    countLinks(line, base, counts);
    const text = toPlainText(line.replace(LIST_ITEM_RE, ''));
    if (text === '') {
      continue;
    }
    wordCount += countWords(text);
    block.push(text);
  }

  flush(false);

  return {
    headings: headingsText.length,
    headingsText,
    paragraphs,
    images: counts.images,
    internalLinks: counts.internal,
    externalLinks: counts.external,
    wordCount,
    content,
    firstParagraph,
    readingTime: Math.ceil(wordCount / WORDS_PER_MINUTE),
  };
}

/** The zero value — for a file with no body, or before one has been read. */
export function emptyArticleDetails(): ArticleDetails {
  return {
    headings: 0,
    headingsText: [],
    paragraphs: 0,
    images: 0,
    internalLinks: 0,
    externalLinks: 0,
    wordCount: 0,
    content: '',
    firstParagraph: '',
    readingTime: 0,
  };
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------

export interface SeoRow {
  label: string;
  value: number;
  /** The target, already worded (`"60 chars"`). Absent for a bare metric. */
  recommendation?: string;
  /** Absent means "informational" — the row renders neither green nor amber. */
  isValid?: boolean;
}

/** The content type's own label for a field, falling back to the field name. */
function fieldLabel(ct: ContentType | undefined, name: string): string {
  const field = findFieldNamed(ct?.fields ?? [], name);
  return field?.title ?? name;
}

function findFieldNamed(fields: readonly Field[], name: string): Field | undefined {
  for (const field of fields) {
    if (field.name === name) {
      return field;
    }
    const nested = findFieldNamed(field.fields ?? [], name);
    if (nested !== undefined) {
      return nested;
    }
  }
  return undefined;
}

/**
 * The insights table, in render order: the three length checks, the article
 * length target, then the five raw counts.
 *
 * Two FM rules are load-bearing and easy to lose:
 *
 *  1. **A threshold of `<= 0` suppresses its row.** That is how a workspace
 *     switches off a check — setting `seo.titleLength` in `zer0.json` to `0`
 *     means "do not tell me about title length", not "titles must be empty".
 *     The thresholds are `zer0.json` keys; VS Code contributes only the
 *     `zer0Cms.seo.enabled` toggle.
 *  2. **Article length is never validated.** It is a target with no `isValid`,
 *     so it renders as an em dash rather than a pass or a fail. A 1,200-word
 *     article is not wrong; it is shorter than the goal.
 *
 * A row is also skipped when its field is empty — there is nothing useful to
 * say about the length of a title that has not been written yet.
 */
export function seoInsights(
  cfg: Zer0Config,
  data: FrontMatter,
  ct: ContentType | undefined,
  details: ArticleDetails,
): SeoRow[] {
  const rows: SeoRow[] = [];

  const title = asString(data[cfg.seo.titleField]);
  if (title !== '' && cfg.seo.titleLength > 0) {
    rows.push({
      label: fieldLabel(ct, cfg.seo.titleField),
      value: title.length,
      recommendation: `${cfg.seo.titleLength} chars`,
      isValid: title.length <= cfg.seo.titleLength,
    });
  }

  const slug = asString(data.slug);
  if (slug !== '' && cfg.seo.slugLength > 0) {
    rows.push({
      label: 'slug',
      value: slug.length,
      recommendation: `${cfg.seo.slugLength} chars`,
      isValid: slug.length <= cfg.seo.slugLength,
    });
  }

  const description = asString(data[cfg.seo.descriptionField]);
  if (description !== '' && cfg.seo.descriptionLength > 0) {
    rows.push({
      label: fieldLabel(ct, cfg.seo.descriptionField),
      value: description.length,
      recommendation: `${cfg.seo.descriptionLength} chars`,
      isValid: description.length <= cfg.seo.descriptionLength,
    });
  }

  if (cfg.seo.contentLength > 0 && details.wordCount > 0) {
    // Deliberately no `isValid`: a recommendation, never a gate.
    rows.push({
      label: 'Article length',
      value: details.wordCount,
      recommendation: `${cfg.seo.contentLength} words`,
    });
  }

  rows.push({ label: 'Headings', value: details.headings });
  rows.push({ label: 'Paragraphs', value: details.paragraphs });
  rows.push({ label: 'Internal links', value: details.internalLinks });
  rows.push({ label: 'External links', value: details.externalLinks });
  rows.push({ label: 'Images', value: details.images });

  return rows;
}

// ---------------------------------------------------------------------------
// Keywords
// ---------------------------------------------------------------------------

export interface KeywordCheck {
  name: string;
  passed: boolean;
}

export interface KeywordInfo {
  keyword: string;
  checks: KeywordCheck[];
  passed: number;
  total: 6;
  /** Percent of the word count, or `null` when there is nothing to divide by. */
  density: number | null;
}

/** The six places a keyword is looked for, in the order the tooltip lists them. */
export const KEYWORD_CHECK_NAMES: readonly string[] = [
  'Title',
  'Description',
  'Slug',
  'Content',
  'Headings',
  'First paragraph',
];

/** Every `KeywordInfo.total`. Six checks, no more, no fewer. */
export const KEYWORD_CHECK_TOTAL = 6;

/**
 * The band the panel paints green. Below is thin, above reads as stuffing.
 *
 * `src/webview/panel/seo.ts` declares its own copy — this module reaches
 * `node:fs` through its imports and cannot be bundled for a browser. Move one
 * bound and move the other, or the panel will paint a density green that the
 * core reports as unhealthy.
 */
export const DENSITY_MIN = 0.75;
export const DENSITY_MAX = 1.5;

/** Is this density inside the recommended band? `null` (unknown) is not. */
export function isHealthyDensity(density: number | null): boolean {
  return density !== null && density >= DENSITY_MIN && density < DENSITY_MAX;
}

/** The `keywords` front-matter field as a list; a bare string becomes one item. */
export function keywordsOf(data: FrontMatter): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of asList(data.keywords)) {
    const keyword = raw.trim();
    const key = keyword.toLowerCase();
    if (keyword !== '' && !seen.has(key)) {
      seen.add(key);
      out.push(keyword);
    }
  }
  return out;
}

const REGEX_SPECIALS = /[.*+?^${}()|[\]\\]/g;

function escapeRegex(value: string): string {
  return value.replace(REGEX_SPECIALS, '\\$&');
}

/**
 * FM's two-mode heading test: a keyword containing a space is a substring
 * match, a single word must appear as a whole word.
 *
 * The single-word case splits on whitespace and compares exactly, which means
 * `MCP` does not match the heading `Getting started with MCP.` — the trailing
 * period is part of the token. That is FM's behaviour, kept on purpose: the
 * check is a presence heuristic, and a rule people can predict beats a rule
 * that is 3% more generous and unexplainable.
 */
function headingMatches(heading: string, keyword: string): boolean {
  const text = heading.toLowerCase();
  if (keyword.includes(' ')) {
    return text.includes(keyword);
  }
  return text.split(/\s+/).includes(keyword);
}

/**
 * The six presence checks and the density for one keyword.
 *
 * An empty keyword fails everything and has no density — `''.includes('')` is
 * `true`, so without the guard a blank entry in `keywords` would report a
 * perfect 6/6.
 *
 * The density regex is FM's, with one change: the keyword is escaped before it
 * goes into the pattern. FM interpolated it raw, so a keyword containing `(`
 * threw `SyntaxError` out of the panel's render.
 */
export function keywordAnalysis(
  keyword: string,
  data: FrontMatter,
  details: ArticleDetails,
  cfg: Zer0Config,
): KeywordInfo {
  const kw = keyword.trim().toLowerCase();

  const title = asString(data[cfg.seo.titleField]).toLowerCase();
  const description = asString(data[cfg.seo.descriptionField]).toLowerCase();
  const slug = asString(data.slug).toLowerCase();
  const content = details.content.toLowerCase();

  const results: boolean[] =
    kw === ''
      ? [false, false, false, false, false, false]
      : [
          title.includes(kw),
          description.includes(kw),
          slug.includes(kw) || slug.includes(kw.split(' ').join('-')),
          content.includes(kw),
          details.headingsText.some((heading) => headingMatches(heading, kw)),
          details.firstParagraph.toLowerCase().includes(kw),
        ];

  const checks: KeywordCheck[] = KEYWORD_CHECK_NAMES.map((name, index) => ({
    name,
    passed: results[index] === true,
  }));

  return {
    keyword,
    checks,
    passed: checks.filter((check) => check.passed).length,
    total: KEYWORD_CHECK_TOTAL,
    density: keywordDensity(kw, details),
  };
}

/**
 * Occurrences per hundred words. The pattern anchors on a word boundary made
 * of whitespace or the start/end of the text, which is why a keyword inside a
 * hyphenated compound does not count.
 */
export function keywordDensity(keyword: string, details: ArticleDetails): number | null {
  const kw = keyword.trim();
  if (kw === '' || details.wordCount === 0) {
    return null;
  }
  const escaped = escapeRegex(kw);
  const pattern = new RegExp(`(^${escaped}(?=\\s|$))|(\\s${escaped}(?=\\s|$))`, 'ig');
  const matches = details.content.match(pattern);
  return ((matches === null ? 0 : matches.length) / details.wordCount) * 100;
}
