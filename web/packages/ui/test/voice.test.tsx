// A site's Voice tab (ADR 0010 V0): every layer that holds, with where it lives,
// where it is changed and who reads it; a layer a book switched off; AIEO's
// context hidden from a non-editor; which assistants could ask for the voice;
// a channel's limits when a post is resolved; and the guard's findings on a
// text under the resolution. The platform is a fake behind the real client.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { SiteView, Voice } from '../src';
import { fakePlatform, renderUi } from '../../../test/harness';

const READERS = [
  { key: 'guard', label: 'the brand guard on an agent’s suggestion, at propose and at accept' },
  { key: 'review', label: 'the brand review task in the Editorial workflow' },
  { key: 'eval', label: 'the brand_clean check of an agent’s evals' },
  { key: 'distribution', label: 'the brand guard on a distribution post' },
  { key: 'brand_rules', label: 'agents and assistants that call the brand.rules tool' },
  { key: 'aieo', label: 'AIEO’s agents' },
  { key: 'book', label: 'a book task’s context (draft, continue, revise, check)' },
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
    layer('builtin', { label: 'Built-in bans', scope: 'platform', bans: [ban('cutting-edge'), ban('game-changer', { level: 'warning' })] }),
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
const routes = (extra: Record<string, Parameters<typeof fakePlatform>[0][string]> = {}) => ({
  'GET /api/v2/content/pages/': () => ({ count: 1, next: null, previous: null, results: [{ id: 41, title: 'Nightly backups', type_label: 'Article' }] }),
  'GET /api/v2/distribution/channels/': () => ({ count: 1, next: null, previous: null, results: [CHANNEL] }),
  ...extra,
});

describe('the Voice tab', () => {
  it('shows every layer with where it lives, who reads it and which assistants could ask for it', async () => {
    const { api } = fakePlatform(routes({ 'GET /api/v2/sites/3/voice/resolved/': () => resolved() }));
    renderUi(<Voice siteId={3} />, { api });
    const site = await screen.findByLabelText('Site settings');
    expect(within(site).getByText('Plain and calm.')).toBeInTheDocument();
    expect(within(site).getByText(/site store · change it in site screen/)).toBeInTheDocument();
    expect(within(site).getByText('agents and assistants that call the brand.rules tool')).toBeInTheDocument();
    expect(screen.getByText(/1 of the 2 assistants you may run here list that tool \(House writer\)/)).toBeInTheDocument();
    expect(within(screen.getByLabelText('AIEO brand context')).getByText('Only the site’s editors see what it says.')).toBeInTheDocument();
    expect(screen.getByTitle('abcdef0123456789')).toHaveTextContent('digest abcdef012345');
    await userEvent.click(within(site).getByRole('button', { name: /1 ban/ }));
    expect(await within(site).findByText('skipped: not a regular expression')).toBeInTheDocument();
  });

  it('marks the built-in bans its book switched off and resolves a post to a channel with its limits', async () => {
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
    await userEvent.click(screen.getByLabelText('For a post to a channel', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Company page (LinkedIn)' }));
    expect(await screen.findByText(/At most 3,000 characters, counted once escaped for LinkedIn; the hook must land before the fold at 140 characters/)).toBeInTheDocument();
    expect(screen.getByText(/posted to Company page/)).toBeInTheDocument();
    expect(asked).toContain(CHANNEL.id);
  });

  it('tests a text under the resolution and says whether the guard would refuse it', async () => {
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
    const button = within(form).getByRole('button', { name: 'Test it' });
    expect(button).toBeDisabled();
    await userEvent.type(within(form).getByRole('textbox', { name: 'Text' }), 'A cutting-edge game-changer.');
    await userEvent.click(button);
    expect(await within(form).findByText('1 error — the guard would refuse it')).toBeInTheDocument();
    expect(within(form).getByText('reads as filler: game-changer')).toBeInTheDocument();
    expect(sent).toEqual({ text: 'A cutting-edge game-changer.' });
  });

  it('is a tab of the site’s page', async () => {
    const { api } = fakePlatform(
      routes({
        'GET /api/v2/sites/3/': () => ({ id: 3, name: 'bash-365', hostname: 'bash-365.localhost', port: 80, is_default: false, root_page_id: 9, managed: null, can_manage: false, pages: { total: 1, live: 1, drafts: 0 }, files: 0, jobs: [] }),
        'GET /api/v2/sites/3/voice/resolved/': () => resolved(),
      }),
    );
    renderUi(<SiteView siteId={3} />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Voice' }));
    await waitFor(() => expect(screen.getByLabelText('Built-in bans')).toBeInTheDocument());
  });
});
