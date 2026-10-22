// The Ideas workspace: a board's ideas sit in columns by status and a vote
// is one request; capture sends one line (or the topic template); a
// brainstorm's reply is followed until it finishes and only the picked ideas
// are kept; duplicates are merged on a person's word; an idea is promoted to a
// draft that then opens. Each test drives the components against a fake
// platform behind the real client.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { CaptureIdea, IdeasWorkspace } from '../src';
import { Brainstorm } from '../src/ideas/Brainstorm';
import { Clusters } from '../src/ideas/Clusters';
import { IdeaDrawer } from '../src/ideas/IdeaDrawer';
import { fakePlatform, pageDetail, renderUi } from '../../../test/harness';

const page = (results: unknown[]) => ({ next: null, previous: null, results });

const idea = (id: string, title: string, rest: Record<string, unknown> = {}) => ({
  id,
  owner: 'editor',
  site: null,
  visibility: 'private',
  created_at: '2026-10-22T09:00:00Z',
  updated_at: '2026-10-22T09:00:00Z',
  board: null,
  title,
  notes: '',
  tags: [],
  status: 'new',
  origin: 'captured',
  url: '',
  sources: [],
  source_message: null,
  brief: null,
  page: null,
  votes: 0,
  voted: false,
  ...rest,
});

const reply = (status: string, result: unknown = null) => ({
  id: 'm2',
  conversation: 'c1',
  seq: 2,
  role: 'assistant',
  text: '',
  result,
  assistant: 'a1',
  run: { id: 40, status: 'queued', links: { self: '/api/v2/agent-runs/40/', stream: '/api/v2/agent-runs/40/stream/' } },
  status,
  provider: 'fake',
  model: 'fake-1',
  usage: {},
  error: '',
  created_at: '2026-10-22T09:00:00Z',
});

describe('<IdeasWorkspace>', () => {
  it('shows ideas in columns by status, and a vote is one request', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/ideas/boards/': () => page([{ id: 'b1', name: 'Spring', owner: 'editor', site: null, visibility: 'private', created_at: '', updated_at: '' }]),
      'GET /api/v2/ideas/': () =>
        page([idea('i1', 'Backups in five minutes', { votes: 2, tags: ['ops'] }), idea('i2', 'Restore drills', { status: 'planned' })]),
      'POST /api/v2/ideas/i1/vote/': () => idea('i1', 'Backups in five minutes', { votes: 3, voted: true }),
    });
    renderUi(<IdeasWorkspace />, { api });
    const fresh = await screen.findByRole('article', { name: 'Backups in five minutes' });
    expect(within(screen.getByLabelText('New')).getByText('Backups in five minutes')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Planned')).getByText('Restore drills')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Boards')).getByText('Spring')).toBeInTheDocument();
    expect(calls.find((c) => c.path === '/api/v2/ideas/')?.query.get('board')).toBe('none');
    await userEvent.click(within(fresh).getByRole('button', { name: 'Vote · 2' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/api/v2/ideas/i1/vote/')).toBe(true));
  });
});

describe('<CaptureIdea>', () => {
  it('sends a title and notes, or the topic template', async () => {
    const { api, calls } = fakePlatform({ 'POST /api/v2/ideas/capture/': () => idea('i9', 'Citability') });
    renderUi(<CaptureIdea boardId="b1" context="From “Nightly backups”." />, { api });
    await userEvent.type(screen.getByLabelText(/^Idea/), 'Citability');
    await userEvent.type(screen.getByLabelText('Notes'), 'For small sites');
    await userEvent.click(screen.getByRole('button', { name: 'Capture' }));
    await waitFor(() => expect(calls.at(-1)?.body).toEqual({ text: 'Citability\nFor small sites\nFrom “Nightly backups”.', board: 'b1', tags: [], template: '' }));
    await userEvent.type(screen.getByLabelText(/^Idea/), 'Restore drills');
    await userEvent.click(screen.getByLabelText('Start from the topic template'));
    await userEvent.click(screen.getByRole('button', { name: 'Capture' }));
    await waitFor(() => expect(calls.at(-1)?.body).toEqual({ text: 'Restore drills', board: 'b1', tags: [], template: 'topic' }));
  });
});

describe('<Brainstorm>', () => {
  it('follows the reply until it finishes and keeps only the picked ideas', async () => {
    let status = 'queued';
    const ideas = {
      ideas: [
        { title: 'Backups in five minutes', notes: 'For beginners.', kind: 'angle' },
        { title: 'Will you notice?', notes: 'A wake-up call.', kind: 'headline' },
      ],
    };
    const { api, calls } = fakePlatform({
      'POST /api/v2/ideas/brainstorm/': () => ({ conversation: 'c1', message: reply('completed'), reply: reply('queued'), run: reply('queued').run }),
      'GET /api/v2/ai/messages/m2/': () => (status === 'completed' ? reply('completed', ideas) : reply(status)),
      'POST /api/v2/ideas/keep/': () => ({ ideas: [idea('i3', 'Will you notice?')] }),
    });
    renderUi(<Brainstorm boardId={null} />, { api });
    await userEvent.click(screen.getByRole('radio', { name: 'Headlines' }));
    await userEvent.type(screen.getByLabelText('What should we brainstorm?'), 'nightly backups');
    await userEvent.click(screen.getByRole('button', { name: 'Brainstorm' }));
    await waitFor(() => expect(calls.find((c) => c.path === '/api/v2/ideas/brainstorm/')?.body).toEqual({ prompt: 'nightly backups', kind: 'headlines', count: 8, board: null, conversation: null }));
    expect(await screen.findByText('The assistant is thinking…')).toBeInTheDocument();
    status = 'completed';
    const second = await screen.findByLabelText('Will you notice? (headline)', {}, { timeout: 4000 });
    await userEvent.click(second);
    await userEvent.click(screen.getByRole('button', { name: 'Keep 1 idea' }));
    await waitFor(() => expect(calls.at(-1)?.body).toEqual({ message: 'm2', picks: [1], board: null }));
    expect(screen.getByRole('button', { name: 'Brainstorm more' })).toBeInTheDocument();
  });
});

describe('<Clusters>', () => {
  it('lists likely duplicates and merges the second into the first on request', async () => {
    const ref = (id: string, title: string) => ({ id, title, status: 'new' });
    const { api, calls } = fakePlatform({
      'GET /api/v2/ideas/clusters/': () => ({
        model: 'hashing-256',
        clusters: [{ ideas: [ref('i1', 'Nightly backups'), ref('i2', 'Nightly backups, explained'), ref('i3', 'Why back up')] }],
        duplicates: [{ a: ref('i1', 'Nightly backups'), b: ref('i2', 'Nightly backups, explained'), similarity: 0.91 }],
        pending: [ref('i4', 'Just captured')],
      }),
      'POST /api/v2/ideas/i1/merge/': () => idea('i1', 'Nightly backups'),
    });
    renderUi(<Clusters board="none" onOpen={() => undefined} />, { api });
    expect(await screen.findByText('91% alike')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Cluster 1')).getByText('Why back up')).toBeInTheDocument();
    expect(screen.getByText('1 idea is still being read.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Merge the second into the first' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')).toMatchObject({ path: '/api/v2/ideas/i1/merge/', body: { other: 'i2' } }));
  });
});

describe('<IdeaDrawer>', () => {
  it('promotes an idea to an article draft and opens it', async () => {
    const section = { ...pageDetail(), id: 3, title: 'Posts', type_label: 'Collection page' };
    const { api, calls } = fakePlatform({
      'GET /api/v2/ideas/i1/': () => idea('i1', 'Restore drills', { notes: 'Once a quarter.' }),
      'GET /api/v2/research/sources/': () => page([]),
      'GET /api/v2/content/pages/': () => ({ count: 1, next: null, previous: null, results: [section] }),
      'POST /api/v2/ideas/i1/promote/': () => ({ idea: idea('i1', 'Restore drills', { status: 'promoted' }), brief: null, page_id: 12, run: null }),
    });
    const { go } = renderUi(<IdeaDrawer ideaId="i1" boards={[]} onClose={() => undefined} />, { api });
    expect(await screen.findByDisplayValue('Restore drills')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'An article draft' }));
    expect(screen.getByRole('button', { name: 'Promote' })).toBeDisabled();
    await userEvent.click(screen.getByLabelText('Where the draft goes', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Posts (Collection page)' }));
    await userEvent.click(screen.getByRole('button', { name: 'Promote' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'page', id: 12 }));
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ into: 'article', generate: false, parent: 3 });
  });
});
