// Briefs: written (a prompt, who writes it, where the draft goes) and
// generated in one step; the generation is a run followed live, after which
// the brief is read again and reviewed — the rendered Markdown, the metadata,
// the structured result — and applied: the draft opens in the editor on its
// Suggestions tab. A failed generation says why and can be asked again.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { BriefList, BriefWorkspace } from '../../src';
import { fakePlatform, pageDetail, renderUi } from '../../../../test/harness';
import { agentRun, assistant, EMPTY, liveStream, page, runRef } from './fixtures';

const brief = (overrides: Record<string, unknown> = {}) => ({
  id: 'b1',
  owner: 'editor',
  site: 1,
  visibility: 'private',
  can_edit: true,
  created_at: '2026-10-22T09:00:00Z',
  updated_at: '2026-10-22T09:00:00Z',
  title: '',
  prompt: 'Why a small site needs nightly backups',
  source_text: '',
  assistant: 'a1',
  pipeline: null,
  output_schema: null,
  page_type: 'cms.ArticlePage',
  parent: null,
  status: 'draft',
  result: null,
  markdown: '',
  metadata: {},
  page: null,
  run: null,
  error: '',
  conversation: null,
  source_message: null,
  applied_at: null,
  ...overrides,
});

const SECTION = { ...pageDetail(), id: 3, title: 'Posts', type_label: 'Collection page', children: 1 };
const places = {
  'GET /api/v2/sites/': () => [{ id: 1, name: 'Demo site', hostname: 'demo.localhost', port: 80, is_default: true, root_page_id: 2 }],
  'GET /api/v2/content/pages/': () => page([SECTION]),
  'GET /api/v2/content/pages/3/types/': () => [{ type: 'cms.ArticlePage', label: 'Article page' }],
  'GET /api/v2/ai/assistants/': () => page([assistant()]),
  'GET /api/v2/ai/pipelines/': () => EMPTY,
  'GET /api/v2/ai/output-schemas/': () => EMPTY,
};

describe('<BriefWorkspace>', () => {
  it('writes a brief and generates it in one step, then opens it', async () => {
    const { api, calls } = fakePlatform({
      ...places,
      'POST /api/v2/ai/briefs/': ({ body }) => brief({ ...(body as object) }),
      'POST /api/v2/ai/briefs/b1/generate/': () => ({ brief: brief({ status: 'generating', run: runRef(9) }), run: runRef(9) }),
    });
    const { go } = renderUi(<BriefWorkspace siteId={1} />, { api });
    await userEvent.type(await screen.findByLabelText('Prompt'), 'Why a small site needs nightly backups');
    expect(screen.getByRole('button', { name: 'Save and generate' })).toBeDisabled(); // nobody to write it yet
    await userEvent.click(screen.getByRole('combobox', { name: 'Assistant' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Headliner' }));
    await userEvent.click(screen.getByRole('combobox', { name: 'Where the draft goes' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Posts (Collection page)' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save and generate' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'brief', id: 'b1' }));
    expect(calls.filter((c) => c.method === 'POST').map((c) => c.path)).toEqual(['/api/v2/ai/briefs/', '/api/v2/ai/briefs/b1/generate/']);
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      title: '',
      prompt: 'Why a small site needs nightly backups',
      source_text: '',
      assistant: 'a1',
      pipeline: null,
      output_schema: null,
      parent: 3,
      page_type: 'cms.ArticlePage',
      visibility: 'private',
      site: 1,
    });
  });

  it('follows the generation live, then reviews the result and applies it as a draft with suggestions', async () => {
    let current = brief({ status: 'generating', run: runRef(9), parent: 3 });
    let status = 'running';
    const { stream, finish } = liveStream();
    const { api, calls } = fakePlatform({
      ...places,
      'GET /api/v2/ai/briefs/b1/': () => current,
      'GET /api/v2/agent-runs/9/': () => agentRun(status),
      'POST /api/v2/ai/briefs/b1/apply/': () => ({ brief: { ...current, status: 'applied', page: 12 }, page_id: 12, suggestions: [41, 42, 43] }),
    });
    const { go } = renderUi(<BriefWorkspace id="b1" />, { api, stream });
    expect(await screen.findByText('Writing…')).toBeInTheDocument();
    expect(await screen.findByRole('status', { name: 'Run #9' })).toHaveTextContent('running');
    await waitFor(() => expect(stream).toHaveBeenCalledWith('/api/v2/agent-runs/9/stream/', ['step', 'status', 'end'], expect.any(Function)));
    current = brief({
      status: 'ready',
      run: runRef(9),
      parent: 3,
      title: 'Backups, nightly',
      markdown: '## Why it matters\n\nA copy every night.',
      result: { headline: 'Why it matters', body: 'A copy every night.' },
      metadata: { title: 'Backups, nightly', slug: 'backups-nightly', keywords: ['backups', 'ops'], tags: [] },
    });
    status = 'succeeded';
    finish();
    const rendered = await screen.findByRole('document', { name: "The brief's Markdown, rendered" });
    expect(within(rendered).getByRole('heading', { name: 'Why it matters' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: 'Metadata' })).toHaveTextContent('backups, ops');
    expect(screen.getByLabelText('The structured result')).toHaveTextContent('"headline": "Why it matters"');
    await userEvent.click(screen.getByRole('button', { name: 'Apply as a draft' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'page', id: 12, tab: 'suggestions' }));
    expect(calls.find((c) => c.path === '/api/v2/ai/briefs/b1/apply/')?.body).toEqual({ parent: 3, page_type: 'cms.ArticlePage' });
  });

  it('offers to apply a ready brief to whoever the platform lets: its owner, or anyone shown one an agent asked for', async () => {
    const ready = { status: 'ready', markdown: 'Text.', can_edit: false };
    const shared = fakePlatform({ ...places, 'GET /api/v2/ai/briefs/b1/': () => brief({ ...ready, owner: 'alice' }) });
    const { unmount } = renderUi(<BriefWorkspace id="b1" />, { api: shared.api });
    expect(await screen.findByText(/alice shares this with you/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Apply as a draft' })).toBeNull();
    unmount();
    const asked = fakePlatform({ ...places, 'GET /api/v2/ai/briefs/b1/': () => brief({ ...ready, owner: 'agent:seo' }) });
    renderUi(<BriefWorkspace id="b1" />, { api: asked.api });
    expect(await screen.findByRole('button', { name: 'Apply as a draft' })).toBeInTheDocument();
  });

  it('says why a generation failed and asks again', async () => {
    const { api, calls } = fakePlatform({
      ...places,
      'GET /api/v2/ai/briefs/b1/': () => brief({ status: 'failed', error: 'the anthropic provider is disabled', run: runRef(9) }),
      'POST /api/v2/ai/briefs/b1/generate/': () => ({ brief: brief({ status: 'generating', run: runRef(10) }), run: runRef(10) }),
    });
    renderUi(<BriefWorkspace id="b1" />, { api });
    expect(await screen.findByText('the anthropic provider is disabled')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Generate again' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v2/ai/briefs/b1/generate/')).toBe(true));
  });

  it('opens an applied brief’s draft on its suggestions, and starts a conversation about a brief', async () => {
    const { api, calls } = fakePlatform({
      ...places,
      'GET /api/v2/ai/briefs/b1/': () => brief({ status: 'applied', page: 12, markdown: 'Text.' }),
      'POST /api/v2/ai/conversations/': () => ({ id: 'c1' }),
    });
    const { go } = renderUi(<BriefWorkspace id="b1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Open the draft' }));
    expect(go).toHaveBeenCalledWith({ to: 'page', id: 12, tab: 'suggestions' });
    await userEvent.click(screen.getByRole('button', { name: 'Talk it over' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'conversation', id: 'c1' }));
    expect(calls.find((c) => c.method === 'POST')?.body).toMatchObject({ from_brief: 'b1', assistant: 'a1', site: 1 });
  });
});

describe('<BriefList>', () => {
  it('lists the briefs of the site with their status', async () => {
    const { api, calls } = fakePlatform({ 'GET /api/v2/ai/briefs/': () => page([brief({ status: 'ready', title: 'Backups, nightly' })]) });
    const { go } = renderUi(<BriefList siteId={1} />, { api });
    const table = await screen.findByRole('table', { name: 'Briefs' });
    expect(within(table).getByText('ready')).toBeInTheDocument();
    expect(calls[0]?.query.get('site')).toBe('1');
    await userEvent.click(within(table).getByRole('button', { name: 'Backups, nightly' }));
    expect(go).toHaveBeenCalledWith({ to: 'brief', id: 'b1' });
  });
});
