// The Distribution workspace: the queue lists posts and opens one; a post's
// panel saves its text, approves, publishes after asking (sending `force` only
// when the person ticks it, and showing the platform's blockers when it
// refuses) and records a post found at the target; Distribute — from the
// editor or a story — drafts a post and leads to the queue; a channel takes a
// credential once and never shows it, connects LinkedIn and X through their
// consent screens, arms, and downloads and imports its ledger file; the ledger marks an
// attempt that may have landed; statistics list the most seen first with
// totals.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { Distribute, Distribution } from '../src';
import { ChannelPanel } from '../src/distribution/Channels';
import { ComposeForm } from '../src/distribution/Compose';
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
    id: '7d3c9f0e-4a1b-4c2d-9e8f-0a1b2c3d4e5f',
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

  it('deletes a draft and goes back to the queue — the platform’s empty 204 is the success, not an error', async () => {
    const platform = fakePlatform({
      [`GET ${API}/posts/p1/`]: () => post(),
      [`DELETE ${API}/posts/p1/`]: () => new Reply(204, null),
    });
    const { go } = renderUi(<PostPanel postId="p1" />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'distribution' }));
    expect(screen.queryByText('No Content')).toBeNull();
  });
});

describe('a rejected post', () => {
  it('is read-only: no text to save and nothing to reject', async () => {
    const platform = fakePlatform({ [`GET ${API}/posts/p1/`]: () => post({ status: 'rejected', reason: 'not this week' }) });
    renderUi(<PostPanel postId="p1" />, { api: platform.api });
    expect(await screen.findByText('Rejected: not this week')).toBeInTheDocument();
    expect(screen.getByLabelText('Text')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Save the text' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
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
    await userEvent.dblClick(screen.getByRole('button', { name: 'Draft the post' }));
    expect(await screen.findByText(/banned phrase "world-class"/)).toBeInTheDocument();
    expect(platform.calls.filter((c) => c.method === 'POST')).toHaveLength(1); // a double click drafts once
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

describe('an X channel', () => {
  it('connects through X’s consent screen, says its token renews itself, and reads its statistics', async () => {
    const consent = 'https://x.com/i/oauth2/authorize?response_type=code&state=s&code_challenge=x';
    const x = { id: 'c3', kind: 'x', kind_label: 'X', name: 'The account', settings: { account: 'bamr87' }, account: '@bamr87' };
    const platform = fakePlatform({
      [`GET ${API}/channels/c3/`]: () => channel({ ...x, has_credential: true, expires_at: '2026-10-31T12:00:00Z' }),
      [`POST ${API}/channels/c3/connect/`]: () => ({ url: consent }),
      [`POST ${API}/channels/c3/statistics/`]: () => new Reply(202, {}),
      [`GET ${API}/channels/c3/ledger-file/`]: () => ({ filename: 'x-c3.json', content: '{}\n' }),
    });
    renderUi(<ChannelPanel channelId="c3" />, { api: platform.api });
    expect(await screen.findByLabelText('Account')).toHaveValue('bamr87');
    expect(screen.getByText(/publishes as @bamr87 · its token renews itself/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Connect with X' }));
    expect(await screen.findByRole('link', { name: 'Continue to X' })).toHaveAttribute('href', consent);
    expect(screen.queryByLabelText('API key')).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Read statistics now' }));
    expect(await screen.findByText('The worker is reading X’s statistics; they appear under Statistics.')).toBeInTheDocument();
  });

  it('offers a text update, and the ledger links its post', async () => {
    const platform = fakePlatform({
      [`GET ${API}/channels/`]: () => listOf([channel({ id: 'c3', kind: 'x', kind_label: 'X', name: 'The account' })]),
      [`GET ${API}/ledger/`]: () => listOf([entry({ channel: 'c3', channel_kind: 'x', urn: '1850000000000000001' })]),
    });
    const { unmount } = renderUi(<ComposeForm siteId={1} onDone={() => undefined} />, { api: platform.api });
    await userEvent.click(await screen.findByLabelText('Channel', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: /The account — X/ }));
    expect(screen.getByRole('radio', { name: 'A text update' })).toBeInTheDocument();
    unmount();
    renderUi(<Ledger siteId={1} />, { api: platform.api });
    const table = await screen.findByRole('table', { name: 'The ledger' });
    expect(within(table).getByRole('link', { name: '1850000000000000001' })).toHaveAttribute('href', 'https://x.com/i/status/1850000000000000001');
  });
});

describe('a channel to someone who does not manage channels', () => {
  it('offers neither a check nor a statistics read', async () => {
    const platform = fakePlatform({
      [`GET ${API}/channels/c1/`]: () => channel({ can_manage: false }),
      [`GET ${API}/channels/c1/ledger-file/`]: () => ({ filename: 'linkedin-c1.json', content: '{}\n' }),
    });
    renderUi(<ChannelPanel channelId="c1" />, { api: platform.api });
    expect(await screen.findByRole('button', { name: 'Check it' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Read statistics now' })).toBeDisabled();
  });
});

describe('removing a channel', () => {
  it('asks first, says how many posts go with it, and shows the platform’s refusal', async () => {
    const platform = fakePlatform({
      [`GET ${API}/channels/c1/`]: () => channel(),
      [`GET ${API}/channels/c1/ledger-file/`]: () => ({ filename: 'linkedin-c1.json', content: '{}\n' }),
      [`GET ${API}/posts/`]: () => ({ count: 3, next: null, previous: null, results: [post()] }),
      [`DELETE ${API}/channels/c1/`]: () =>
        new Reply(409, { error: { code: 'conflict', message: 'The page’s ledger holds 1 entry: disconnect the channel instead', status: 409, details: [] } }),
    });
    renderUi(<ChannelPanel channelId="c1" />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Remove the channel…' }));
    const dialog = await screen.findByRole('dialog', { name: 'Remove this channel?' });
    expect(await within(dialog).findByText(/and its 3 posts with it/)).toBeInTheDocument();
    expect(platform.calls.some((c) => c.method === 'DELETE')).toBe(false);
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove it' }));
    expect(await within(dialog).findByText(/disconnect the channel instead/)).toBeInTheDocument();
    expect(platform.calls.find((c) => c.path === `${API}/posts/`)?.query.get('channel')).toBe('c1');
  });
});

describe('the ledger and its statistics', () => {
  it('marks an attempt that may have landed and links a LinkedIn post', async () => {
    const platform = fakePlatform({
      [`GET ${API}/ledger/`]: () =>
        listOf([entry(), entry({ id: '7d3c9f0e-4a1b-4c2d-9e8f-0a1b2c3d4e60', key: 'https://example.test/b/', urn: '', state: 'unconfirmed', posted_at: null, attempted_at: '2026-10-21T09:00:00Z' })]),
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
        listOf([entry({ key: 'https://example.test/a/', latest: stats(10) }), entry({ id: '7d3c9f0e-4a1b-4c2d-9e8f-0a1b2c3d4e60', key: 'https://example.test/b/', latest: stats(90) }), entry({ id: '7d3c9f0e-4a1b-4c2d-9e8f-0a1b2c3d4e61', key: 'https://example.test/c/' })]),
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

describe('the release queue (a channel’s cadence)', () => {
  it('approves into the next slot on a cadence channel, shows when it goes, and unschedules', async () => {
    let state: Record<string, unknown> = { status: 'draft', channel_cadence: 'tue,thu 09:00 (America/Denver), at most 1 a day' };
    const platform = fakePlatform({
      [`GET ${API}/posts/p1/`]: () => post(state),
      [`POST ${API}/posts/p1/approve/`]: () => {
        state = { ...state, status: 'approved', scheduled_for: '2026-11-10T16:00:00Z', scheduled_by: 'editor', scheduled_pinned: false, blockers: [], updated_at: '2026-11-05T00:00:01Z' };
        return post(state);
      },
      [`POST ${API}/posts/p1/unschedule/`]: () => {
        state = { ...state, scheduled_for: null, scheduled_by: null, updated_at: '2026-11-05T00:00:02Z' };
        return post(state);
      },
      [`POST ${API}/posts/p1/schedule/`]: ({ body }) => {
        state = { ...state, scheduled_for: (body as { at?: string }).at ?? '2026-11-12T16:00:00Z', scheduled_pinned: Boolean((body as { at?: string }).at), updated_at: '2026-11-05T00:00:03Z' };
        return post(state);
      },
    });
    renderUi(<PostPanel postId="p1" />, { api: platform.api });
    expect(await screen.findByText(/publishes on a cadence \(tue,thu 09:00/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Approve and queue' }));
    expect(await screen.findByText(/The next slot of The page’s cadence, as editor’s publish/)).toBeInTheDocument();
    expect(screen.getByText('Scheduled')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Unschedule' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Schedule in the next slot' }));
    await waitFor(() => expect(platform.calls.filter((c) => c.path === `${API}/posts/p1/schedule/`).map((c) => c.body)).toEqual([{}]));
    expect(await screen.findByRole('button', { name: 'Unschedule' })).toBeInTheDocument();
  });

  it('schedules a post on a channel with no cadence at a time a person picks', async () => {
    let state: Record<string, unknown> = { status: 'approved', channel_cadence: '', blockers: [] };
    const platform = fakePlatform({
      [`GET ${API}/posts/p1/`]: () => post(state),
      [`POST ${API}/posts/p1/schedule/`]: () => {
        state = { ...state, scheduled_for: '2026-11-20T17:30:00Z', scheduled_pinned: true, updated_at: '2026-11-05T00:00:00Z' };
        return post(state);
      },
    });
    renderUi(<PostPanel postId="p1" />, { api: platform.api });
    expect(await screen.findByRole('button', { name: 'Publish…' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Schedule in the next slot' })).toBeNull();
    const at = screen.getByLabelText('Or at a time');
    await userEvent.type(at, '2026-11-20T10:30');
    await userEvent.click(screen.getByRole('button', { name: 'Schedule at this time' }));
    await waitFor(() => expect(platform.calls.find((c) => c.path === `${API}/posts/p1/schedule/`)?.body).toEqual({ at: new Date('2026-11-20T10:30').toISOString() }));
    expect(await screen.findByText(/A time a person chose/)).toBeInTheDocument();
  });

  it('sets a channel’s cadence from the form and shows its release calendar', async () => {
    const platform = fakePlatform({
      [`GET ${API}/channels/c1/`]: () => channel({ cadence: {}, cadence_summary: '' }),
      [`PATCH ${API}/channels/c1/`]: () => channel({ cadence: { slots: ['tue 09:00'] }, cadence_summary: 'tue 09:00 (UTC), at most 1 a day' }),
      [`GET ${API}/channels/c1/ledger-file/`]: () => ({ filename: 'linkedin-c1.json', content: '{}\n' }),
      [`GET ${API}/channels/c1/calendar/`]: () => ({
        summary: 'tue 09:00 (UTC), at most 1 a day',
        timezone: 'UTC',
        problems: [],
        scheduled: [post({ id: 'p9', title: 'Weekly restores', status: 'approved', scheduled_for: '2026-11-10T09:00:00Z', scheduled_pinned: true })],
        free: ['2026-11-17T09:00:00Z', '2026-11-24T09:00:00Z'],
        recent: ['2026-11-03T09:00:00Z'],
      }),
    });
    const { go } = renderUi(<ChannelPanel channelId="c1" />, { api: platform.api });
    expect(await screen.findByText(/No cadence: an approved post goes when a person publishes it/)).toBeInTheDocument();
    const calendar = await screen.findByRole('table', { name: 'Scheduled posts' });
    expect(within(calendar).getByText('(a time a person chose)')).toBeInTheDocument();
    await userEvent.click(within(calendar).getByRole('button', { name: 'Weekly restores' }));
    expect(go).toHaveBeenCalledWith({ to: 'distribution-post', id: 'p9' });
    expect(screen.getByText(/Next free slots:/)).toBeInTheDocument();
    const timezone = screen.getByLabelText('Time zone');
    await userEvent.clear(timezone);
    await userEvent.type(timezone, 'America/Denver');
    await userEvent.type(screen.getByLabelText('Slots'), 'tue 09:00, thu 09:00');
    await userEvent.type(screen.getByLabelText('Gap between posts'), '48h');
    await userEvent.type(screen.getByLabelText('At most a week'), '2');
    await userEvent.type(screen.getByLabelText('Blackout dates'), '2026-12-24..2027-01-01');
    await userEvent.click(screen.getByRole('button', { name: 'Save the cadence' }));
    await waitFor(() =>
      expect(platform.calls.find((c) => c.method === 'PATCH')?.body).toEqual({
        cadence: { timezone: 'America/Denver', slots: ['tue 09:00', 'thu 09:00'], minGap: '48h', perWeek: 2, blackout: ['2026-12-24..2027-01-01'] },
      }),
    );
  });

  it('lists when each post goes and filters to the scheduled ones', async () => {
    const platform = fakePlatform({
      [`GET ${API}/posts/`]: () => listOf([post({ status: 'approved', scheduled_for: '2026-11-10T16:00:00Z' })]),
      [`GET ${API}/channels/`]: () => listOf([channel()]),
    });
    renderUi(<Distribution siteId={1} />, { api: platform.api });
    const table = await screen.findByRole('table', { name: 'The queue' });
    expect(within(table).getByText(/^scheduled /)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Scheduled only' }));
    await waitFor(() => expect(platform.calls.filter((c) => c.path === `${API}/posts/`).at(-1)?.query.get('scheduled')).toBe('true'));
  });
});
