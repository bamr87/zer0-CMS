// The Distribution workspace: the queue lists posts and opens one; a post's
// panel saves its text, approves, publishes after asking (sending `force` only
// when the person ticks it, and showing the platform's blockers when it
// refuses) and records a post found at the target; Distribute — from the
// editor or a story — drafts a post and leads to the queue; a channel takes a
// credential once and never shows it, connects LinkedIn through its consent
// screen, arms, and downloads and imports its ledger file; the ledger marks an
// attempt that may have landed; statistics list the most seen first with
// totals.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { Distribute, Distribution } from '../src';
import { ChannelPanel } from '../src/distribution/Channels';
import { Ledger, Statistics } from '../src/distribution/Ledger';
import { PostPanel } from '../src/distribution/PostPanel';
import { fakePlatform, renderUi, Reply } from '../../../test/harness';

const API = '/api/v2/distribution';
const listOf = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results });

function channel(overrides: Record<string, unknown> = {}) {
  return {
    id: 'c1',
    site: 1,
    site_name: 'Demo site',
    kind: 'linkedin',
    kind_label: 'LinkedIn',
    name: 'The page',
    settings: { author: 'urn:li:organization:5' },
    newsletter: null,
    newsletter_name: '',
    has_credential: true,
    secret_fields: ['access_token', 'refresh_token'],
    connecting: false,
    account: 'Demo Co',
    scopes: [],
    connected_at: '2026-10-20T09:00:00Z',
    expires_at: null,
    refresh_expires_at: null,
    checked_at: null,
    last_check: {},
    last_error: '',
    auto_draft: false,
    armed: false,
    deployment_armed: true,
    can_manage: true,
    created_at: '2026-10-20T09:00:00Z',
    updated_at: '2026-10-20T09:00:00Z',
    ...overrides,
  };
}

function post(overrides: Record<string, unknown> = {}) {
  return {
    id: 'p1',
    channel: 'c1',
    channel_name: 'The page',
    channel_kind: 'linkedin',
    page: 5,
    page_title: 'Nightly backups',
    story: null,
    kind: 'article',
    title: 'Nightly backups',
    description: 'Why we copy the site every night.',
    commentary: 'We copy the site every night.',
    link: 'https://example.test/nightly-backups/',
    status: 'draft',
    guard: [{ level: 'info', message: 'fold at 140 chars: "We copy the site every night."' }],
    origin: 'person',
    external_id: '',
    external_url: '',
    error: '',
    notes: [],
    reason: '',
    created_by: 'editor',
    approved_by: null,
    approved_at: null,
    attempted_at: null,
    published_at: null,
    can_publish: true,
    created_at: '2026-10-20T09:00:00Z',
    updated_at: '2026-10-20T09:00:00Z',
    blockers: [{ kind: 'status_not_accepted', message: 'the post is draft: a person approves it first' }],
    payload: { author: 'urn:li:organization:5', commentary: 'We copy the site every night.' },
    ...overrides,
  };
}

function entry(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    channel: 'c1',
    channel_name: 'The page',
    channel_kind: 'linkedin',
    key: 'https://example.test/a/',
    urn: 'urn:li:share:1',
    state: 'published',
    kind: 'article',
    posted_at: '2026-10-20T09:00:00Z',
    attempted_at: null,
    error: '',
    source_file: '',
    post: 'p1',
    page: 5,
    latest: null,
    ...overrides,
  };
}

const stats = (impressions: number) => ({
  day: '2026-10-21',
  impressions,
  clicks: 1,
  reactions: 2,
  comments: 0,
  shares: 1,
  engagements: 3,
  fetched_at: '2026-10-21T04:23:00Z',
});

describe('the queue', () => {
  it('lists the posts with their status and guard and opens one', async () => {
    const platform = fakePlatform({
      [`GET ${API}/posts/`]: () => listOf([post(), post({ id: 'p2', title: 'Restores', status: 'failed', guard: [{ level: 'error', message: 'banned' }] })]),
      [`GET ${API}/channels/`]: () => listOf([channel()]),
    });
    const { go } = renderUi(<Distribution siteId={1} />, { api: platform.api });
    const table = await screen.findByRole('table', { name: 'The queue' });
    expect(within(table).getByText('Failed')).toBeInTheDocument();
    expect(within(table).getByText('1 error(s)')).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('button', { name: 'Restores' }));
    expect(go).toHaveBeenCalledWith({ to: 'distribution-post', id: 'p2' });
    expect(platform.calls.find((c) => c.path === `${API}/posts/`)?.query.get('site')).toBe('1');
  });
});

describe('a post', () => {
  it('approves, asks before publishing, shows the platform’s refusal and forces only when ticked', async () => {
    let status = 'draft';
    let publishes = 0;
    const platform = fakePlatform({
      [`GET ${API}/posts/p1/`]: () =>
        post({
          status,
          blockers:
            status === 'draft'
              ? [{ kind: 'status_not_accepted', message: 'approve it first' }]
              : [{ kind: 'publish_unconfirmed', message: 'an earlier attempt may have published this' }],
        }),
      [`POST ${API}/posts/p1/approve/`]: () => {
        status = 'approved';
        return post({ status });
      },
      [`POST ${API}/posts/p1/publish/`]: ({ body }) => {
        publishes += 1;
        if (!(body as { force: boolean }).force)
          return new Reply(409, {
            error: { code: 'distribution.blocked', message: 'publish_unconfirmed: an earlier attempt may have published this', status: 409, details: [] },
          });
        status = 'publishing';
        return new Reply(202, post({ status }));
      },
    });
    renderUi(<PostPanel postId="p1" />, { api: platform.api });
    expect(await screen.findByText('approve it first')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Publish…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Publish this post?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Publish now' }));
    expect(await within(dialog).findByText(/an earlier attempt may have published this/)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /Force it past/ }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Publish now' }));
    await waitFor(() => expect(publishes).toBe(2));
    expect(platform.calls.filter((c) => c.path === `${API}/posts/p1/publish/`).map((c) => c.body)).toEqual([{ force: false }, { force: true }]);
    expect(await screen.findByText('The worker is publishing it…')).toBeInTheDocument();
  });

  it('saves only the text that changed — a failed post’s goes back to draft — and records a post found after a failure', async () => {
    const platform = fakePlatform({
      [`GET ${API}/posts/p1/`]: () => post({ status: 'failed', error: 'HTTP 503: down — it may have published' }),
      [`PATCH ${API}/posts/p1/`]: () => post({ status: 'draft' }),
      [`POST ${API}/posts/p1/record/`]: () => post({ status: 'published', external_id: 'urn:li:share:42' }),
    });
    renderUi(<PostPanel postId="p1" />, { api: platform.api });
    expect(await screen.findByText(/HTTP 503: down/)).toBeInTheDocument();
    const text = screen.getByLabelText('Text');
    await userEvent.clear(text);
    await userEvent.type(text, 'Every night, a copy.');
    expect(screen.getByText(/Saving a changed text sends the post back to draft/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Publish…' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Save the text' }));
    await waitFor(() => expect(platform.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ commentary: 'Every night, a copy.' }));
    await userEvent.type(screen.getByLabelText(/Record it/), 'urn:li:share:42');
    await userEvent.click(screen.getByRole('button', { name: 'Record' }));
    await waitFor(() => expect(platform.calls.find((c) => c.path.endsWith('/record/'))?.body).toEqual({ urn: 'urn:li:share:42' }));
  });
});

describe('what a post says about where it went', () => {
  it('shows a post’s notes, such as where its site ledger entry went', async () => {
    const note = "written to the site's ledger file (.github/linkedin-log.json): commit it";
    const platform = fakePlatform({ [`GET ${API}/posts/p1/`]: () => post({ status: 'published', notes: [note], blockers: [] }) });
    renderUi(<PostPanel postId="p1" />, { api: platform.api });
    expect(within(await screen.findByLabelText('Notes')).getByText(note)).toBeInTheDocument();
  });

  it('says the newsroom is sending its issue while it waits', async () => {
    const platform = fakePlatform({
      [`GET ${API}/posts/p1/`]: () => post({ status: 'publishing', channel_kind: 'email', attempted_at: '2026-10-28T09:00:00Z', blockers: [] }),
    });
    renderUi(<PostPanel postId="p1" />, { api: platform.api });
    expect(await screen.findByText('The newsroom is sending the newsletter issue…')).toBeInTheDocument();
  });
});

describe('Distribute', () => {
  it('drafts a post of the page for a channel and leads to the queue', async () => {
    const platform = fakePlatform({
      [`GET ${API}/channels/`]: () => listOf([channel()]),
      [`POST ${API}/posts/`]: () =>
        new Reply(201, post({ guard: [{ level: 'error', message: 'banned phrase "world-class" (world-class)' }] })),
    });
    const { go } = renderUi(<Distribute pageId={5} siteId={1} />, { api: platform.api });
    await userEvent.click(screen.getByRole('button', { name: 'Distribute' }));
    await userEvent.click(await screen.findByLabelText('Channel', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: /The page — LinkedIn/ }));
    await userEvent.type(screen.getByLabelText('Text'), 'Our world-class backups.');
    await userEvent.click(screen.getByRole('button', { name: 'Draft the post' }));
    expect(await screen.findByText(/banned phrase "world-class"/)).toBeInTheDocument();
    expect(platform.calls.find((c) => c.method === 'POST')?.body).toEqual({
      channel: 'c1',
      kind: 'article',
      page: 5,
      commentary: 'Our world-class backups.',
    });
    expect(platform.calls.find((c) => c.path === `${API}/channels/`)?.query.get('site')).toBe('1');
    await userEvent.click(screen.getByRole('button', { name: 'Open it in the queue' }));
    expect(go).toHaveBeenCalledWith({ to: 'distribution-post', id: 'p1' });
  });

  it('drafts a story for a newsletter without asking for a page', async () => {
    const platform = fakePlatform({
      [`GET ${API}/channels/`]: () => listOf([channel({ id: 'c9', kind: 'email', kind_label: 'Email newsletter', name: 'Weekly' })]),
      [`POST ${API}/posts/`]: () => new Reply(201, post({ id: 'p9', channel_name: 'Weekly', channel_kind: 'email' })),
    });
    renderUi(<Distribute storyId="s1" />, { api: platform.api });
    await userEvent.click(screen.getByRole('button', { name: 'Distribute' }));
    await userEvent.click(await screen.findByLabelText('Channel', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: /Weekly/ }));
    expect(screen.queryByLabelText('Page', { selector: 'input' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Draft the post' }));
    await waitFor(() => expect(platform.calls.find((c) => c.method === 'POST')?.body).toEqual({ channel: 'c9', kind: 'article', story: 's1' }));
  });
});

describe('a channel', () => {
  it('takes a credential once and never shows it, and arms on a person’s word', async () => {
    const platform = fakePlatform({
      [`GET ${API}/channels/c2/`]: () =>
        channel({ id: 'c2', kind: 'wordpress', kind_label: 'WordPress', has_credential: false, secret_fields: ['application_password'], settings: { url: 'https://blog.example.com', username: 'ed' } }),
      [`PATCH ${API}/channels/c2/`]: () => channel({ id: 'c2', kind: 'wordpress', has_credential: true, secret_fields: ['application_password'] }),
      [`GET ${API}/channels/c2/ledger-file/`]: () => ({ filename: 'wordpress-c2.json', content: '{}\n' }),
    });
    renderUi(<ChannelPanel channelId="c2" />, { api: platform.api });
    await userEvent.type(await screen.findByLabelText('Application password'), 'abcd efgh');
    await userEvent.click(screen.getByRole('button', { name: 'Set the credential' }));
    await waitFor(() => expect(platform.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ credentials: { application_password: 'abcd efgh' } }));
    await userEvent.click(await screen.findByRole('switch', { name: /Armed/ }));
    await waitFor(() => expect(platform.calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toContainEqual({ armed: true }));
    expect(screen.queryByDisplayValue('abcd efgh')).toBeNull();
  });

  it('connects LinkedIn through its consent screen and holds the ledger file', async () => {
    const consent = 'https://www.linkedin.com/oauth/v2/authorization?response_type=code&state=s&code_challenge=x';
    const ledger = '{\n  "https://example.test/a/": {\n    "urn": "urn:li:share:1"\n  }\n}\n';
    const platform = fakePlatform({
      [`GET ${API}/channels/c1/`]: () => channel({ has_credential: false }),
      [`POST ${API}/channels/c1/connect/`]: () => ({ url: consent }),
      [`GET ${API}/channels/c1/ledger-file/`]: () => ({ filename: 'linkedin-c1.json', content: ledger }),
      [`POST ${API}/channels/c1/ledger-file/`]: () => ({ added: 2, kept: 0, skipped: 1 }),
    });
    const { container } = renderUi(<ChannelPanel channelId="c1" />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Connect with LinkedIn' }));
    expect(await screen.findByRole('link', { name: 'Continue to LinkedIn' })).toHaveAttribute('href', consent);
    const download = await screen.findByRole('link', { name: 'Download the ledger file' });
    expect(download).toHaveAttribute('href', `data:application/json;charset=utf-8,${encodeURIComponent(ledger)}`);
    expect(download).toHaveAttribute('download', 'linkedin-c1.json');
    const input = container.ownerDocument.querySelector('input[type="file"]');
    if (!(input instanceof HTMLInputElement)) throw new Error('no file input');
    await userEvent.upload(input, new File(['{"https://example.test/b/": {"urn": "urn:li:share:2"}}'], 'ledger.json', { type: 'application/json' }));
    expect(await screen.findByText('Imported: 2 added, 0 already here, 1 skipped.')).toBeInTheDocument();
    expect(platform.calls.find((c) => c.method === 'POST' && c.path.endsWith('/ledger-file/'))?.body).toEqual({
      content: '{"https://example.test/b/": {"urn": "urn:li:share:2"}}',
    });
  });
});

describe('the ledger and its statistics', () => {
  it('marks an attempt that may have landed and links a LinkedIn post', async () => {
    const platform = fakePlatform({
      [`GET ${API}/ledger/`]: () =>
        listOf([entry(), entry({ id: 2, key: 'https://example.test/b/', urn: '', state: 'unconfirmed', posted_at: null, attempted_at: '2026-10-21T09:00:00Z' })]),
      [`GET ${API}/channels/`]: () => listOf([channel()]),
    });
    renderUi(<Ledger siteId={1} />, { api: platform.api });
    const table = await screen.findByRole('table', { name: 'The ledger' });
    expect(within(table).getByText('unconfirmed — may have published')).toBeInTheDocument();
    expect(within(table).getByRole('link', { name: 'urn:li:share:1' })).toHaveAttribute('href', 'https://www.linkedin.com/feed/update/urn:li:share:1/');
  });

  it('lists the most seen first, with the totals', async () => {
    const platform = fakePlatform({
      [`GET ${API}/ledger/`]: () =>
        listOf([entry({ key: 'https://example.test/a/', latest: stats(10) }), entry({ id: 2, key: 'https://example.test/b/', latest: stats(90) }), entry({ id: 3, key: 'https://example.test/c/' })]),
      [`GET ${API}/channels/`]: () => listOf([channel()]),
    });
    renderUi(<Statistics />, { api: platform.api });
    const rows = within(await screen.findByRole('table', { name: 'Statistics' })).getAllByRole('row');
    expect(rows.map((r) => r.textContent?.slice(0, 26))).toEqual([
      expect.stringContaining('Post'),
      expect.stringContaining('https://example.test/b/'),
      expect.stringContaining('https://example.test/a/'),
      expect.stringContaining('All of them'),
    ]);
    expect(rows.at(-1)).toHaveTextContent('100');
  });
});
