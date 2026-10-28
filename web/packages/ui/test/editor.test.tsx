// The editor: it saves only what changed, against the revision it loaded;
// publish saves pending edits first; a schedule takes a time to go live and
// a time to come down; a locked page opens read-only and says why; new blocks
// keep their own text through removes and moves; revisions compare with the
// latest and revert as a new draft; the page list filters through the platform.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { Block } from '@zer0/api';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';

import { BodyEditor, PageEditor, PageList, RevisionHistory } from '../src';
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

  it('edits the SEO tab’s Open Graph fields, canonical URL and noindex, and saves only those', async () => {
    const seo = (name: string, label: string, kind: string) => ({ name, label, group: 'seo', kind, required: false, help_text: '', max_length: null, choices: [] });
    const detail = pageDetail({
      fields: { title: 'Nightly backups', og_title: '', og_image: '/assets/images/backups.png', canonical_url: '', noindex: false },
      field_specs: [
        { name: 'title', label: 'Title', group: 'content', kind: 'text', required: true, help_text: '', max_length: 255, choices: [] },
        seo('og_title', 'Open Graph title', 'text'),
        seo('og_image', 'Open Graph image', 'text'),
        seo('canonical_url', 'Canonical URL', 'text'),
        seo('noindex', 'Hide from search engines', 'boolean'),
      ],
    });
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => detail,
      'PATCH /api/v2/content/pages/5/': () => detail,
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('tab', { name: 'SEO' }));
    expect(screen.getByLabelText('Open Graph image')).toHaveValue('/assets/images/backups.png');
    await userEvent.type(screen.getByLabelText('Open Graph title'), 'Backups, nightly');
    await userEvent.type(screen.getByLabelText('Canonical URL'), 'https://example.com/backups/');
    await userEvent.click(screen.getByRole('switch', { name: 'Hide from search engines' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save draft' }));
    await waitFor(() => expect(platform.calls.find((c) => c.method === 'PATCH')).toBeDefined());
    expect(platform.calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      base_revision_id: 41,
      fields: { og_title: 'Backups, nightly', canonical_url: 'https://example.com/backups/', noindex: true },
    });
  });

  it('schedules a time to go live and one to come down, cancels the schedule, and unpublishes — each one request', async () => {
    const scheduled = pageDetail({
      status: 'scheduled',
      go_live_at: '2030-01-02T09:30:00.000Z',
      expire_at: '2030-02-01T17:00:00.000Z',
      lock: "Page 'Nightly backups' is locked and has been scheduled to go live at 2 Jan 2030",
    });
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => pageDetail(),
      'POST /api/v2/content/pages/5/schedule/': () => scheduled,
      'POST /api/v2/content/pages/5/unschedule/': () => pageDetail(),
      'POST /api/v2/content/pages/5/unpublish/': () => pageDetail({ status: 'draft', live: false }),
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Schedule…' }));
    await userEvent.type(screen.getByLabelText('Publish at'), '2030-01-02T09:30');
    await userEvent.type(screen.getByLabelText('Take down at'), '2030-02-01T17:00');
    await userEvent.click(screen.getByRole('button', { name: 'Schedule' }));
    expect(await screen.findByText(/Goes live/)).toBeInTheDocument();
    expect(screen.getByText(/Comes down/)).toBeInTheDocument();
    const sent = platform.calls.find((c) => c.path.endsWith('/schedule/'))?.body as { go_live_at: string; expire_at: string };
    expect(new Date(sent.go_live_at).getTime()).toBe(new Date(2030, 0, 2, 9, 30).getTime());
    expect(new Date(sent.expire_at).getTime()).toBe(new Date(2030, 1, 1, 17, 0).getTime());
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled(); // a scheduled page is locked …

    await userEvent.click(screen.getByRole('button', { name: 'Cancel schedule' })); // … until this
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
    expect(screen.getByRole('button', { name: 'Accept all 1 shown of run #7' })).toBeDisabled();
  });

  it('takes down a live page on a schedule without a go-live time', async () => {
    const platform = fakePlatform({
      'GET /api/v2/content/pages/5/': () => pageDetail(),
      'POST /api/v2/content/pages/5/schedule/': () => pageDetail({ expire_at: '2030-02-01T17:00:00.000Z' }),
    });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    await userEvent.click(await screen.findByRole('button', { name: 'Schedule…' }));
    await userEvent.type(screen.getByLabelText('Take down at'), '2030-02-01T17:00');
    await userEvent.click(screen.getByRole('button', { name: 'Schedule' }));
    expect(await screen.findByText(/Comes down/)).toBeInTheDocument();
    const sent = platform.calls.find((c) => c.path.endsWith('/schedule/'))?.body as { go_live_at: unknown; expire_at: string };
    expect(sent.go_live_at).toBeNull();
    expect(new Date(sent.expire_at).getTime()).toBe(new Date(2030, 1, 1, 17, 0).getTime());
  });

  it('opens a page someone else has locked read-only, and says why', async () => {
    const lock = "'Nightly backups' was locked by Ada on 21 Oct 2026.";
    const platform = fakePlatform({ 'GET /api/v2/content/pages/5/': () => pageDetail({ lock, pending_suggestions: 1 }) });
    renderUi(<PageEditor pageId={5} />, { api: platform.api });
    expect(await screen.findByText(lock)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Title/)).toBeDisabled();
    expect(within(screen.getByLabelText('Block 1: heading')).getByLabelText('text')).toBeDisabled();
    for (const name of ['Save draft', 'Publish', 'Schedule…']) expect(screen.getByRole('button', { name })).toBeDisabled();
    expect(platform.calls.every((c) => c.method === 'GET')).toBe(true);
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

describe('<BodyEditor>', () => {
  // Blocks a person added and has not saved yet carry no id.
  const NEW_BLOCKS: Block[] = [
    { type: 'markdown', value: 'FIRST block' },
    { type: 'markdown', value: 'SECOND block' },
    { type: 'markdown', value: 'THIRD block' },
  ];

  function Body() {
    const [blocks, setBlocks] = useState(NEW_BLOCKS);
    return (
      <>
        <BodyEditor blocks={blocks} onChange={setBlocks} />
        <output aria-label="Saved">{blocks.map((b) => String(b.value)).join(' | ')}</output>
      </>
    );
  }
  const shown = () => screen.getAllByRole('textbox', { name: 'Markdown block' }).map((editor) => editor.textContent);

  it('keeps each new block’s own text in its editor after a remove and a move', async () => {
    renderUi(<Body />, { api: fakePlatform({}).api });
    expect(shown()).toEqual(['FIRST block', 'SECOND block', 'THIRD block']);
    await userEvent.click(within(screen.getByLabelText('Block 1: markdown')).getByRole('button', { name: 'Remove block' }));
    expect(screen.getByLabelText('Saved')).toHaveTextContent('SECOND block | THIRD block');
    expect(shown()).toEqual(['SECOND block', 'THIRD block']);
    await userEvent.click(within(screen.getByLabelText('Block 1: markdown')).getByRole('button', { name: 'Move down' }));
    expect(screen.getByLabelText('Saved')).toHaveTextContent('THIRD block | SECOND block');
    expect(shown()).toEqual(['THIRD block', 'SECOND block']);
  });

  it('keeps an edited new block in its place when a block above it goes', async () => {
    renderUi(<Body />, { api: fakePlatform({}).api });
    await userEvent.click(within(screen.getByLabelText('Block 3: markdown')).getByText('Markdown'));
    await userEvent.type(within(screen.getByLabelText('Block 3: markdown')).getByRole('textbox'), ' edited');
    await userEvent.click(within(screen.getByLabelText('Block 1: markdown')).getByRole('button', { name: 'Remove block' }));
    expect(screen.getByLabelText('Saved')).toHaveTextContent('SECOND block | THIRD block edited');
    expect(within(screen.getByLabelText('Block 2: markdown')).getByRole('textbox')).toHaveValue('THIRD block edited');
  });
});

describe('<BodyEditor> blocks', () => {
  const START: Block[] = [
    {
      id: 't',
      type: 'table',
      value: { data: [['Name', 'Role'], ['Ada', 'engineer']], first_row_is_table_header: true, first_col_is_header: false, table_caption: '', table_header_choice: 'row' },
    },
    { id: 'tt', type: 'typed_table', value: { columns: [{ type: 'text', heading: 'Quarter' }, { type: 'number', heading: 'Score' }], rows: [{ values: ['Q1', '7'] }], caption: '' } },
    { id: 'c', type: 'callout', value: { kind: 'tip', fold: '-', title: 'Rule of thumb', body: 'Keep notes small.' } },
    { id: 'h', type: 'raw_html', value: '<div class="note">Raw</div>' },
  ];

  function Many() {
    const [blocks, setBlocks] = useState(START);
    return (
      <>
        <BodyEditor blocks={blocks} onChange={setBlocks} />
        <output aria-label="Saved">{JSON.stringify(blocks)}</output>
      </>
    );
  }
  const saved = () => JSON.parse(screen.getByLabelText('Saved').textContent ?? '[]') as { type: string; value: Record<string, unknown> }[];

  it('edits a table’s cells, rows and columns in place', async () => {
    renderUi(<Many />, { api: fakePlatform({}).api });
    const table = within(screen.getByLabelText('Block 1: table'));
    await userEvent.type(table.getByLabelText('Row 1, column 2'), ', mathematician');
    await userEvent.click(table.getByRole('button', { name: '+ row' }));
    await userEvent.click(table.getByRole('button', { name: 'Remove column 1' }));
    expect(saved()[0]?.value.data).toEqual([['Role'], ['engineer, mathematician'], ['']]);
    expect(saved()[0]?.value.table_header_choice).toBe('row');
  });

  it('keeps a typed table’s column types, and shows a callout’s fold and the source of raw HTML', async () => {
    renderUi(<Many />, { api: fakePlatform({}).api });
    const typed = within(screen.getByLabelText('Block 2: typed_table'));
    expect(typed.getByRole('combobox', { name: 'Column 2 type' })).toHaveValue('number');
    await userEvent.click(typed.getByRole('button', { name: '+ column' }));
    await userEvent.type(typed.getByLabelText('Heading 3'), 'Notes');
    expect(saved()[1]?.value).toEqual({
      columns: [
        { type: 'text', heading: 'Quarter' },
        { type: 'number', heading: 'Score' },
        { type: 'text', heading: 'Notes' },
      ],
      rows: [{ values: ['Q1', '7', ''] }],
      caption: '',
    });
    const callout = within(screen.getByLabelText('Block 3: callout'));
    expect(callout.getByRole('combobox', { name: 'Fold' })).toHaveValue('Foldable, closed');
    expect(callout.getByLabelText('body')).toHaveValue('Keep notes small.');
    expect(within(screen.getByLabelText('Block 4: raw_html')).getByRole('textbox')).toHaveValue('<div class="note">Raw</div>');
  });

  it('adds a block of each new kind with an empty value', async () => {
    renderUi(<Many />, { api: fakePlatform({}).api });
    for (const kind of ['table', 'callout', 'embed', 'liquid']) await userEvent.click(screen.getByRole('button', { name: `+ ${kind}` }));
    expect(saved().slice(4).map((b) => b.type)).toEqual(['table', 'callout', 'embed', 'liquid']);
    expect(within(screen.getByLabelText('Block 5: table')).getAllByRole('textbox')).toHaveLength(4);
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
