// A site's Voice tab (ADR 0010 V0): the map of who reads which layer, with the
// reader no layer reaches named; each layer a section with where it lives and
// where it is changed; the counts the guard applies (a skipped rule is not
// one); a layer a book switched off; AIEO's context hidden from a non-editor;
// which assistants could ask for the voice; a channel's limits; a text tested
// under the resolution (Ctrl+Enter too), its findings in a live region and
// gone when the scope changes; the scope surviving a change of tab; and the
// page picker searching on the platform. The platform is a fake behind the
// real client.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { SiteView, Voice } from '../src';
import { fakePlatform, renderUi } from '../../../test/harness';

const READERS = [
  { key: 'guard', name: 'Suggestion guard', label: 'the brand guard on an agent’s suggestion, at propose and at accept' },
  { key: 'review', name: 'Brand review', label: 'the brand review task in the Editorial workflow' },
  { key: 'eval', name: 'Evals', label: 'the brand_clean check of an agent’s evals' },
  { key: 'distribution', name: 'Post guard', label: 'the brand guard on a distribution post' },
  { key: 'brand_rules', name: 'brand.rules', label: 'agents and assistants that call the brand.rules tool' },
  { key: 'aieo', name: 'AIEO agents', label: 'AIEO’s agents' },
  { key: 'book', name: 'Book tasks', label: 'a book task’s context (draft, continue, revise, check)' },
  { key: 'ai_panel', name: 'AI panel', label: 'the editor’s AI panel: an assistant run on a page is told its own instructions only' },
];

const ban = (name: string, overrides: Record<string, unknown> = {}) => ({ name, pattern: `\\b${name}\\b`, flags: 'i', level: 'error', valid: true, why: '', ...overrides });

const layer = (key: string, overrides: Record<string, unknown> = {}) => ({
  key,
  label: key,
  scope: 'site',
  source: `${key} store`,
  edit: `${key} screen`,
  readers: ['guard', 'brand_rules'],
  guidance: [],
  bans: [],
  limits: {},
  active: true,
  lifted_by: '',
  hidden: false,
  ...overrides,
});

const resolved = (overrides: Record<string, unknown> = {}) => ({
  page: null,
  channel: null,
  layers: [
    layer('builtin', {
      label: 'Built-in bans',
      scope: 'platform',
      edit: '',
      bans: [ban('cutting-edge'), ban('game-changer', { level: 'warning' }), ban('exclamation mark', { level: 'warning', valid: false, why: 'not checked on a page' })],
    }),
    layer('site', { label: 'Site settings', guidance: [{ label: 'Brand voice', text: 'Plain and calm.' }], bans: [ban('broken', { pattern: '(', valid: false, why: 'not a regular expression' })] }),
    layer('aieo', { label: 'AIEO brand context', readers: ['aieo'], hidden: true }),
  ],
  digest: 'abcdef0123456789',
  told: { style_guides: ['Plain and calm.'], banned: ['cutting-edge', 'broken'] },
  assistants: [
    { id: '00000000-0000-4000-8000-000000000001', name: 'Article rewriter', reads_voice: false },
    { id: '00000000-0000-4000-8000-000000000002', name: 'House writer', reads_voice: true },
  ],
  readers: READERS,
  ...overrides,
});

const CHANNEL = { id: 'c0c0c0c0-0000-4000-8000-000000000001', site: 3, site_name: 'bash-365', kind: 'linkedin', kind_label: 'LinkedIn', name: 'Company page' };
const PAGES = [
  { id: 41, title: 'Nightly backups', type_label: 'Article' },
  { id: 42, title: 'ERP Survivor', type_label: 'Article' },
];
const routes = (extra: Record<string, Parameters<typeof fakePlatform>[0][string]> = {}) => ({
  'GET /api/v2/content/pages/': () => ({ count: PAGES.length, next: null, previous: null, results: PAGES }),
  'GET /api/v2/distribution/channels/': () => ({ count: 1, next: null, previous: null, results: [CHANNEL] }),
  ...extra,
});

describe('the Voice tab', () => {
  it('maps who reads which layer, names the reader no layer reaches, and counts what the guard applies', async () => {
    const { api } = fakePlatform(routes({ 'GET /api/v2/sites/3/voice/resolved/': () => resolved() }));
    renderUi(<Voice siteId={3} />, { api });
    const map = await screen.findByRole('table', { name: 'Who reads which layer' });
    expect(within(within(map).getByRole('row', { name: /^Built-in bans/ })).getAllByText('reads it')).toHaveLength(2);
    expect(within(within(map).getByRole('row', { name: /^AIEO brand context/ })).getAllByText('reads it')).toHaveLength(1);
    expect(screen.getByText(/^Never reached here:/)).toHaveTextContent('AI panel');
    expect(screen.getByText('3 layers · 1 ban in force · 1 warning · 2 skipped')).toBeInTheDocument();
    expect(screen.getByText(/1 of the 2 assistants you may run here list that tool \(House writer\)/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copy the digest abcdef0123456789' })).toHaveTextContent('digest abcdef012345');
  });

  it('shows each layer as a section with where it lives, where it is changed, and its bans as the guard reads them', async () => {
    const { api } = fakePlatform(routes({ 'GET /api/v2/sites/3/voice/resolved/': () => resolved() }));
    renderUi(<Voice siteId={3} />, { api });
    const site = await screen.findByRole('region', { name: 'Site settings' });
    expect(within(site).getByText('Plain and calm.')).toBeInTheDocument();
    expect(within(site).getByText(/site store · change it in site screen/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Built-in bans' })).getByText(/it is code: no screen changes it/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'AIEO brand context' })).getByText('Only the site’s editors see what it says.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '1 ban, 1 warning, 1 skipped' })).toBeInTheDocument();
    await userEvent.click(within(site).getByRole('button', { name: '1 skipped' }));
    expect(await within(site).findByText('not a regular expression')).toBeInTheDocument();
  });

  it('marks a layer its book switched off and resolves a post to a channel with its limits', async () => {
    const asked: (string | null)[] = [];
    const { api } = fakePlatform(
      routes({
        'GET /api/v2/sites/3/voice/resolved/': ({ url }) => {
          asked.push(url.searchParams.get('channel'));
          if (!url.searchParams.get('channel')) return resolved({ layers: [layer('builtin', { label: 'Built-in bans', active: false, lifted_by: 'book' })] });
          return resolved({
            channel: { id: CHANNEL.id, name: CHANNEL.name, kind: 'linkedin' },
            layers: [layer('builtin', { label: 'Built-in bans' }), layer('channel', { label: 'Channel: Company page', scope: 'channel', readers: ['distribution'], limits: { max_length: 3000, fold: 140, max_escaped_length: 3000 } })],
          });
        },
      }),
    );
    renderUi(<Voice siteId={3} />, { api });
    expect(await screen.findByText('switched off by its book')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Built-in bans' })).getByText('Nothing is set here yet.')).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: 'Built-in bans (off here)' })).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('For a post to a channel', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Company page (LinkedIn)' }));
    expect(await screen.findByText(/At most 3,000 characters, counted once escaped for LinkedIn; the hook must land before the fold at 140 characters/)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The voice of the site, posted to Company page' })).toBeInTheDocument();
    expect(asked).toContain(CHANNEL.id);
  });

  it('tests a text with Ctrl+Enter, announces the verdict, and puts it away when the scope changes', async () => {
    let sent: Record<string, unknown> = {};
    const { api } = fakePlatform(
      routes({
        'GET /api/v2/sites/3/voice/resolved/': () => resolved(),
        'POST /api/v2/sites/3/voice/test/': ({ body }) => {
          sent = body as Record<string, unknown>;
          return {
            findings: [
              { level: 'error', message: 'banned phrase "cutting-edge" (cutting-edge)' },
              { level: 'warning', message: 'reads as filler: game-changer' },
            ],
            digest: 'abcdef0123456789',
          };
        },
      }),
    );
    renderUi(<Voice siteId={3} />, { api });
    const form = await screen.findByRole('form', { name: 'Test a text' });
    expect(within(form).getByRole('button', { name: 'Test it' })).toBeDisabled();
    await userEvent.type(within(form).getByRole('textbox', { name: 'Text' }), 'A cutting-edge game-changer.{Control>}{Enter}{/Control}');
    const status = within(form).getByRole('status');
    expect(await within(status).findByText('1 error — the guard would refuse it')).toBeInTheDocument();
    expect(within(status).getByText('reads as filler: game-changer')).toBeInTheDocument();
    expect(sent).toEqual({ text: 'A cutting-edge game-changer.' });
    await userEvent.click(screen.getByLabelText('For a post to a channel', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Company page (LinkedIn)' }));
    await waitFor(() => expect(within(status).queryByLabelText('Findings')).not.toBeInTheDocument());
  });

  it('searches the platform for a page as the person types', async () => {
    const searched: (string | null)[] = [];
    const extra = { id: 140, title: 'The hundred and first page', type_label: 'Article' };
    const { api } = fakePlatform(
      routes({
        'GET /api/v2/content/pages/': ({ url }) => {
          searched.push(url.searchParams.get('q'));
          const q = (url.searchParams.get('q') ?? '').toLowerCase();
          const results = q ? [...PAGES, extra].filter((p) => p.title.toLowerCase().includes(q)) : PAGES;
          return { count: results.length, next: null, previous: null, results };
        },
        'GET /api/v2/sites/3/voice/resolved/': ({ url }) => resolved(url.searchParams.get('page') ? { page: { id: 140, title: extra.title, type: 'ArticlePage' } } : {}),
      }),
    );
    renderUi(<Voice siteId={3} />, { api });
    await userEvent.type(await screen.findByLabelText('For a page', { selector: 'input' }), 'hundred');
    await userEvent.click(await screen.findByRole('option', { name: 'The hundred and first page (Article)' }));
    expect(searched).toContain('hundred');
    expect(await screen.findByRole('heading', { name: 'The voice for “The hundred and first page”' })).toBeInTheDocument();
  });

  it('is a tab of the site’s page whose page and channel survive a change of tab', async () => {
    const { api } = fakePlatform(
      routes({
        'GET /api/v2/sites/3/': () => ({ id: 3, name: 'bash-365', hostname: 'bash-365.localhost', port: 80, is_default: false, root_page_id: 9, managed: null, can_manage: false, pages: { total: 1, live: 1, drafts: 0 }, files: 0, jobs: [] }),
        'GET /api/v2/sites/3/settings/': () => ({ navigation: [], banned_patterns: [], design_tokens: {} }),
        'GET /api/v2/sites/3/voice/resolved/': () => resolved(),
      }),
    );
    renderUi(<SiteView siteId={3} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Voice' }));
    await screen.findByRole('region', { name: 'Built-in bans' });
    await userEvent.click(screen.getByLabelText('For a post to a channel', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Company page (LinkedIn)' }));
    await userEvent.click(screen.getByRole('tab', { name: 'Settings' }));
    await userEvent.click(screen.getByRole('tab', { name: 'Voice' }));
    expect(await screen.findByLabelText('For a post to a channel', { selector: 'input' })).toHaveValue('Company page (LinkedIn)');
  });
});
