// The editor: it saves only what changed, against the revision it loaded;
// publish saves pending edits first; revisions compare with the latest and
// revert as a new draft; the page list filters through the platform.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { PageEditor, PageList, RevisionHistory } from '../src';
import { fakePlatform, pageDetail, renderUi, Reply } from '../../../test/harness';

describe('<PageEditor>', () => {
  it('saves only the changed fields, against the revision it loaded', async () => {
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => pageDetail(),
      'PATCH /api/v2/content/pages/5/': () =>
        pageDetail({ title: 'Nightly backups, revised', status: 'changed', latest_revision: { id: 42, created_at: '2026-10-21T10:00:00Z', user: 'editor' } }),
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    const title = await screen.findByLabelText(/^Title/);
    expect(screen.getByRole('button', { name: 'Save draft' })).toBeDisabled();
    await userEvent.clear(title);
    await userEvent.type(title, 'Nightly backups, revised');
    expect(screen.getByText('unsaved')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(platform.calls.find((c) => c.method === 'PATCH')).toBeDefined());
    expect(platform.calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      base_revision_id: 41,
      fields: { title: 'Nightly backups, revised' },
    });
    expect(await screen.findByText('Live + draft')).toBeInTheDocument();
  });

  it('sends the edited body with its block ids, and publishing saves first', async () => {
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => pageDetail(),
      'PATCH /api/v2/content/pages/5/': () => pageDetail({ status: 'changed' }),
      'POST /api/v2/content/pages/5/publish/': () => pageDetail(),
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    const heading = within(await screen.findByLabelText('Block 1: heading')).getByLabelText('text');
    await userEvent.type(heading, ', briefly');
    await userEvent.click(screen.getByRole('button', { name: 'Publish' }));
    await waitFor(() => expect(platform.calls.map((c) => `${c.method} ${c.path}`)).toContain('POST /api/v2/content/pages/5/publish/'));
    const saved = platform.calls.find((c) => c.method === 'PATCH')?.body as { body: { id: string; value: unknown }[] };
    expect(saved.body.map((b) => b.id)).toEqual(['b1', 'b2']);
    expect(saved.body[0]?.value).toEqual({ level: '2', text: 'How it works, briefly' });
    const order = platform.calls.filter((c) => c.method !== 'GET').map((c) => c.method);
    expect(order).toEqual(['PATCH', 'POST']);
  });

  it('schedules, cancels a schedule, and unpublishes — each one request', async () => {
    const scheduled = pageDetail({ status: 'scheduled', go_live_at: '2030-01-02T09:30:00.000Z' });
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => pageDetail(),
      'POST /api/v2/content/pages/5/schedule/': () => scheduled,
      'POST /api/v2/content/pages/5/unschedule/': () => pageDetail(),
      'POST /api/v2/content/pages/5/unpublish/': () => pageDetail({ status: 'draft', live: false }),
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Schedule…' }));
    await userEvent.type(screen.getByLabelText('Publish at'), '2030-01-02T09:30');
    await userEvent.click(screen.getByRole('button', { name: 'Schedule' }));
    expect(await screen.findByText(/Goes live/)).toBeInTheDocument();
    const sent = platform.calls.find((c) => c.path.endsWith('/schedule/'))?.body as { go_live_at: string };
    expect(new Date(sent.go_live_at).getTime()).toBe(new Date(2030, 0, 2, 9, 30).getTime());

    await userEvent.click(screen.getByRole('button', { name: 'Cancel schedule' }));
    await waitFor(() => expect(platform.calls.some((c) => c.path.endsWith('/unschedule/'))).toBe(true));
    await userEvent.click(await screen.findByRole('button', { name: 'Unpublish' }));
    expect(await screen.findByText('Draft')).toBeInTheDocument();
    expect(platform.calls.filter((c) => c.method === 'POST').map((c) => c.path.split('/').at(-2))).toEqual([
      'schedule',
      'unschedule',
      'unpublish',
    ]);
  });

  it('holds accepting a suggestion while there are unsaved edits, so they are never replaced', async () => {
    const inbox = {
      count: 1,
      next: null,
      previous: null,
      results: [
        {
          id: 1,
          op: 'meta',
          block_id: '',
          field: 'seo_title',
          payload: {},
          rationale: '',
          status: 'pending',
          agent: 'seo',
          run_id: 7,
          created_at: '2026-10-21T09:00:00Z',
          target: { type: 'page', id: 5, title: 'Nightly backups' },
          change: { kind: 'field', label: 'seo_title', before: '', after: 'Backups', stale: false },
        },
      ],
    };
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => pageDetail({ pending_suggestions: 1 }),
      'GET /api/v2/review/suggestions/': () => inbox,
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await userEvent.type(await screen.findByLabelText(/^Title/), '!');
    await userEvent.click(screen.getByRole('tab', { name: 'Suggestions (1)' }));
    expect(await screen.findByText(/save them before accepting/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Accept all of run #7' })).toBeDisabled();
  });

  it('shows the platform’s refusal of a stale save', async () => {
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => pageDetail(),
      'PATCH /api/v2/content/pages/5/': () =>
        new Reply(409, { error: { code: 'resource.conflict', message: 'page 5 has a newer revision', status: 409, details: [] } }),
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await userEvent.type(await screen.findByLabelText(/^Title/), '!');
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    expect(await screen.findByText('page 5 has a newer revision')).toBeInTheDocument();
  });
});

describe('<RevisionHistory>', () => {
  const revisions = {
    count: 2,
    next: null,
    previous: null,
    results: [
      { id: 42, created_at: '2026-10-21T10:00:00Z', user: 'editor', approved_go_live_at: null, is_live: false, is_latest: true },
      { id: 41, created_at: '2026-10-20T10:00:00Z', user: 'editor', approved_go_live_at: null, is_live: true, is_latest: false },
    ],
  };
  const snapshot = (id: number, title: string, markdown: string) => ({
    id,
    created_at: '2026-10-20T10:00:00Z',
    user: 'editor',
    fields: { title },
    body: [],
    markdown,
  });

  it('compares a revision with the latest and reverts to it as a new draft', async () => {
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/revisions/': () => revisions,
      'GET /api/v2/content/pages/5/revisions/compare/': ({ url }) => {
        expect([url.searchParams.get('a'), url.searchParams.get('b')]).toEqual(['41', '42']);
        return { a: snapshot(41, 'Old title', 'One.\n'), b: snapshot(42, 'New title', 'One.\nTwo.\n'), changed: ['title', 'body'] };
      },
      'POST /api/v2/content/pages/5/revisions/41/revert/': () => pageDetail({ status: 'changed' }),
    });
    const { container } = renderUi(<RevisionHistory pageId={5} canEdit />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Compare with latest' }));
    expect(await screen.findByText('Changes since revision #41')).toBeInTheDocument();
    expect([...container.querySelectorAll('ins')].map((n) => n.textContent)).toEqual(['New', 'Two.\n']);
    await userEvent.click(screen.getByRole('button', { name: 'Revert to this' }));
    await waitFor(() => expect(platform.calls.some((c) => c.method === 'POST' && c.path.endsWith('/revisions/41/revert/'))).toBe(true));
  });
});

describe('<PageList>', () => {
  it('lists pages, walks into the tree, and filters by status through the platform', async () => {
    const section = { ...pageDetail(), id: 3, title: 'Posts', type_label: 'Collection page', children: 1 };
    const page = { ...pageDetail(), status: 'draft', title: 'A draft' };
    const platform = fakePlatform({
      'GET /api/v2/content/types/': () => [{ type: 'cms.ArticlePage', label: 'Article page' }],
      'GET /api/v2/content/pages/': ({ url }) => {
        const inside = url.searchParams.get('parent') === '3';
        const results = url.searchParams.get('status') === 'live' ? [] : inside ? [page] : [section];
        return { count: results.length, next: null, previous: null, results };
      },
    });
    const { go } = renderUi(<PageList siteId={1} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: '1 inside' }));
    expect(within(screen.getByLabelText('Where in the tree')).getByText('Posts')).toBeInTheDocument();
    await userEvent.click(await screen.findByRole('button', { name: 'A draft' }));
    expect(go).toHaveBeenCalledWith({ to: 'page', id: 5 });
    const listed = platform.calls.filter((c) => c.path === '/api/v2/content/pages/');
    expect(listed.map((c) => c.query.get('parent'))).toEqual([null, '3']);
    expect(listed.every((c) => c.query.get('site') === '1')).toBe(true);
    await userEvent.click(screen.getByLabelText('Status', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Live' }));
    expect(await screen.findByText('No pages match.')).toBeInTheDocument();
    const queries = platform.calls.filter((c) => c.path === '/api/v2/content/pages/');
    expect(queries.at(-1)?.method).toBe('GET');
    expect(queries.length).toBeGreaterThan(1);
  });
});
