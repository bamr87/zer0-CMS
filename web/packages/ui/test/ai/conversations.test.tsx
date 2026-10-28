// Conversations: a message sent is answered by a run the thread follows live
// — the reply waits as a queued message with the run's progress, and the
// answer shows when the run is done; an answer can be asked for again (of the
// same assistant or another), promoted to a brief or a draft (which opens as
// a brief), or deleted; a new conversation starts with its assistant. Every
// request that starts a run carries an Idempotency-Key and is sent once — a
// second Ctrl+Enter, a message's menu while its request is out — and a thread
// opens on its newest messages, loading earlier ones when asked.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ConversationList, ConversationThread, shortId } from '../../src';
import { fakePlatform, held, renderUi } from '../../../../test/harness';
import { agentRun, assistant, EMPTY, liveStream, OTHER_RUN, page, RUN, runRef } from './fixtures';

const conversation = {
  id: 'c1',
  owner: 'editor',
  site: null,
  visibility: 'private',
  can_edit: true,
  created_at: '2026-10-22T09:00:00Z',
  updated_at: '2026-10-22T09:00:00Z',
  title: 'Names',
  assistant: 'a1',
  pipeline: null,
  page: null,
};

const message = (seq: number, role: string, text: string, overrides: Record<string, unknown> = {}) => ({
  id: `m${seq}`,
  conversation: 'c1',
  seq,
  role,
  text,
  result: null,
  assistant: role === 'assistant' ? 'a1' : null,
  run: null,
  status: 'completed',
  provider: role === 'assistant' ? 'fake' : '',
  model: role === 'assistant' ? 'fake-1' : '',
  usage: role === 'assistant' ? { tokens: 7, cost_usd: '0.001000' } : {},
  error: '',
  created_at: '2026-10-22T09:00:00Z',
  ...overrides,
});

/** A page of messages as the platform sends it: newest first when asked (`ordering=-seq`), as the thread asks. */
const cursor = <T,>(results: T[], url?: URL, next: string | null = null) => ({
  next,
  previous: null,
  results: url?.searchParams.get('ordering') === '-seq' ? [...results].reverse() : results,
});
const helpers = {
  'GET /api/v2/ai/conversations/c1/': () => conversation,
  'GET /api/v2/ai/assistants/': () => page([assistant({ id: 'a1', name: 'Namer' }), assistant({ id: 'a2', name: 'Critic' })]),
  'GET /api/v2/ai/pipelines/': () => EMPTY,
};

describe('<ConversationThread>', () => {
  it('sends a message and shows the answer as the run that writes it finishes', async () => {
    let messages = [message(1, 'user', 'I am Alice'), message(2, 'assistant', 'Hello **Alice**')];
    let status = 'running';
    const { stream, finish } = liveStream();
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/messages/': ({ url }) => cursor(messages, url),
      'POST /api/v2/ai/conversations/c1/messages/': () => {
        messages = [...messages, message(3, 'user', 'What is my name?'), message(4, 'assistant', '', { status: 'queued', run: runRef() })];
        return { message: messages[2], reply: messages[3], run: runRef() };
      },
      [`GET /api/v2/agent-runs/${RUN}/`]: () => agentRun(status),
    });
    renderUi(<ConversationThread id="c1" />, { api, stream });
    const thread = within(await screen.findByRole('list', { name: 'Messages' }));
    expect(await thread.findByRole('document', { name: "Namer's answer" })).toHaveTextContent('Hello Alice');
    expect(thread.getByText('fake · fake-1 · 7 tokens · $0.001000')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Your message'), 'What is my name?');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ text: 'What is my name?', answer: true });
    expect(calls.find((c) => c.method === 'POST')?.idempotencyKey).toBeTruthy();
    expect(calls.find((c) => c.path.endsWith('/messages/'))?.query.get('ordering')).toBe('-seq');
    expect(screen.getByLabelText('Your message')).toHaveValue('');
    const waiting = await thread.findByRole('listitem', { name: 'Namer, message 4' });
    expect(within(waiting).getByText('queued')).toBeInTheDocument();
    expect(await within(waiting).findByRole('status', { name: `Run ${shortId(RUN)}` })).toBeInTheDocument();
    await waitFor(() => expect(stream).toHaveBeenCalledWith(`/api/v2/agent-runs/${RUN}/stream/`, ['step', 'status', 'end'], expect.any(Function)));
    messages = [...messages.slice(0, 3), message(4, 'assistant', 'Your name is Alice.')];
    status = 'succeeded';
    finish();
    expect(await thread.findByText('Your name is Alice.')).toBeInTheDocument();
    expect(within(thread.getByRole('listitem', { name: 'Namer, message 4' })).queryByText('queued')).toBeNull();
  });

  it('sends Ctrl+Enter, and asks a chosen assistant for this one reply', async () => {
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/messages/': () => cursor([]),
      'POST /api/v2/ai/conversations/c1/messages/': () => ({ message: message(1, 'user', 'Hi'), reply: null, run: null }),
    });
    renderUi(<ConversationThread id="c1" />, { api });
    expect(await screen.findByText(/No messages yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('combobox', { name: 'Who answers this one' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Critic' }));
    await userEvent.type(screen.getByLabelText('Your message'), 'Hi{Control>}{Enter}{/Control}');
    await waitFor(() => expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ text: 'Hi', answer: true, assistant: 'a2' }));
  });

  it('asks again, of the same assistant or another, and promotes an answer to a draft', async () => {
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/messages/': ({ url }) => cursor([message(1, 'user', 'Ideas?'), message(2, 'assistant', 'Three ideas.')], url),
      'POST /api/v2/ai/messages/m2/rerun/': () => ({ message: message(3, 'assistant', '', { status: 'queued', run: runRef() }), run: runRef() }),
      'POST /api/v2/ai/messages/m2/promote/': () => ({ brief: { id: 'b7' }, run: runRef(OTHER_RUN) }),
      [`GET /api/v2/agent-runs/${RUN}/`]: () => agentRun('running'),
    });
    const { go } = renderUi(<ConversationThread id="c1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Actions for message 2' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Ask again' }));
    await waitFor(() => expect(calls.find((c) => c.path === '/api/v2/ai/messages/m2/rerun/')?.body).toEqual({}));
    await userEvent.click(screen.getByRole('button', { name: 'Actions for message 2' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Ask Critic instead' }));
    await waitFor(() => expect(calls.findLast((c) => c.path === '/api/v2/ai/messages/m2/rerun/')?.body).toEqual({ assistant: 'a2' }));
    await userEvent.click(screen.getByRole('button', { name: 'Actions for message 2' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Promote to a draft' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'brief', id: 'b7' }));
    expect(calls.find((c) => c.path === '/api/v2/ai/messages/m2/promote/')?.body).toEqual({ to: 'draft' });
  });

  it('shows one side of the thread, or the replies that failed, as the platform filters them', async () => {
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/messages/': ({ url }) =>
        cursor(
          url.searchParams.get('status') === 'failed'
            ? [message(2, 'assistant', '', { status: 'failed', error: 'the provider is down' })]
            : [message(1, 'user', 'Ideas?'), message(2, 'assistant', '', { status: 'failed', error: 'the provider is down' })],
          url,
        ),
    });
    renderUi(<ConversationThread id="c1" />, { api });
    expect(await screen.findByText('Ideas?')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: 'Failed' }));
    await waitFor(() => expect(screen.queryByText('Ideas?')).toBeNull());
    expect(screen.getByText('the provider is down')).toBeInTheDocument();
    expect(calls.findLast((c) => c.path.endsWith('/messages/'))?.query.get('status')).toBe('failed');
    await userEvent.click(screen.getByRole('radio', { name: 'Yours' }));
    await waitFor(() => expect(calls.findLast((c) => c.path.endsWith('/messages/'))?.query.get('role')).toBe('user'));
  });

  it('runs the conversation’s pipeline on the message, each step replying in turn', async () => {
    let status = 'running';
    const { stream, finish } = liveStream();
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/': () => ({ ...conversation, pipeline: 'p1' }),
      'GET /api/v2/ai/pipelines/': () => page([{ id: 'p1', name: 'Draft, then edit', owner: 'editor', site: null, visibility: 'private', can_edit: true, created_at: '', updated_at: '', steps: [] }]),
      'GET /api/v2/ai/conversations/c1/messages/': () => cursor([]),
      'POST /api/v2/ai/conversations/c1/run-pipeline/': () => ({ run: runRef() }),
      [`GET /api/v2/agent-runs/${RUN}/`]: () => agentRun(status),
    });
    renderUi(<ConversationThread id="c1" />, { api, stream });
    await userEvent.type(await screen.findByLabelText('Your message'), 'A post about backups');
    await userEvent.click(screen.getByRole('button', { name: 'Run the pipeline' }));
    await waitFor(() => expect(calls.find((c) => c.path.endsWith('/run-pipeline/'))?.body).toEqual({ prompt: 'A post about backups' }));
    expect(await screen.findByRole('status', { name: `Run ${shortId(RUN)}` })).toHaveTextContent('running');
    const before = calls.filter((c) => c.path.endsWith('/messages/')).length;
    status = 'succeeded';
    finish();
    await waitFor(() => expect(calls.filter((c) => c.path.endsWith('/messages/')).length).toBeGreaterThan(before));
  });

  it('sends once when Ctrl+Enter is pressed twice, and the composer waits while the message is out', async () => {
    const sending = held({ message: message(1, 'user', 'Hi'), reply: null, run: null });
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/messages/': () => cursor([]),
      'POST /api/v2/ai/conversations/c1/messages/': () => sending.reply,
    });
    renderUi(<ConversationThread id="c1" />, { api });
    await userEvent.type(await screen.findByLabelText('Your message'), 'Hi{Control>}{Enter}{Enter}{/Control}');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled());
    const posts = calls.filter((c) => c.method === 'POST');
    expect(posts).toHaveLength(1);
    expect(posts[0]?.idempotencyKey).toBeTruthy();
    sending.answer();
    await waitFor(() => expect(screen.getByLabelText('Your message')).toHaveValue(''));
    await userEvent.keyboard('{Control>}{Enter}{/Control}'); // nothing left to send
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
  });

  it('holds a message’s actions while one is out, each with its own key, and promotes an answer to a brief', async () => {
    const asking = held({ message: message(3, 'assistant', '', { status: 'queued' }), run: runRef() });
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/messages/': ({ url }) => cursor([message(1, 'user', 'Ideas?'), message(2, 'assistant', 'Three ideas.')], url),
      'POST /api/v2/ai/messages/m2/rerun/': () => asking.reply,
      'POST /api/v2/ai/messages/m2/promote/': () => ({ brief: { id: 'b8' }, run: null }),
    });
    const { go } = renderUi(<ConversationThread id="c1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Actions for message 2' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Ask again' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Actions for message 2' })).toBeDisabled());
    expect(calls.filter((c) => c.path.endsWith('/rerun/'))).toHaveLength(1);
    asking.answer();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Actions for message 2' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: 'Actions for message 2' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Promote to a brief' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'brief', id: 'b8' }));
    const [rerun, promote] = calls.filter((c) => c.method === 'POST');
    expect(promote?.body).toEqual({ to: 'brief' });
    expect(rerun?.idempotencyKey && promote?.idempotencyKey && rerun.idempotencyKey !== promote.idempotencyKey).toBe(true);
  });

  it('opens on the newest messages and loads earlier ones when asked, oldest at the top', async () => {
    const all = [message(1, 'user', 'First'), message(2, 'assistant', 'Second'), message(3, 'user', 'Third'), message(4, 'assistant', 'Fourth')];
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/messages/': ({ url }) =>
        url.searchParams.get('cursor') === 'older'
          ? cursor(all.slice(0, 2), url)
          : cursor(all.slice(2), url, 'http://studio.test/api/v2/ai/conversations/c1/messages/?cursor=older&ordering=-seq&page_size=50'),
    });
    renderUi(<ConversationThread id="c1" />, { api });
    const thread = await screen.findByRole('list', { name: 'Messages' });
    const order = () => within(thread).queryAllByRole('listitem').map((item) => item.getAttribute('aria-label'));
    await waitFor(() => expect(order()).toEqual(['You, message 3', 'Namer, message 4']));
    expect(calls.find((c) => c.path.endsWith('/messages/'))?.query.get('page_size')).toBe('50');
    await userEvent.click(screen.getByRole('button', { name: 'Load earlier messages' }));
    await waitFor(() => expect(order()).toEqual(['You, message 1', 'Namer, message 2', 'You, message 3', 'Namer, message 4']));
    expect(calls.findLast((c) => c.path.endsWith('/messages/'))?.query.get('cursor')).toBe('older');
    expect(screen.queryByRole('button', { name: 'Load earlier messages' })).toBeNull();
  });

  it('deletes a message and changes who replies', async () => {
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/c1/messages/': () => cursor([message(1, 'user', 'Scratch that')]),
      'DELETE /api/v2/ai/messages/m1/': () => ({}),
      'PATCH /api/v2/ai/conversations/c1/': () => ({ ...conversation, assistant: 'a2' }),
    });
    renderUi(<ConversationThread id="c1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Actions for message 1' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Delete' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/v2/ai/messages/m1/')).toBe(true));
    await userEvent.click(screen.getByRole('combobox', { name: 'Who replies' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Critic' }));
    await waitFor(() => expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ assistant: 'a2' }));
  });
});

describe('<ConversationList>', () => {
  it('starts a conversation with an assistant and opens it', async () => {
    const { api, calls } = fakePlatform({
      ...helpers,
      'GET /api/v2/ai/conversations/': () => page([conversation]),
      'POST /api/v2/ai/conversations/': () => ({ ...conversation, id: 'c2' }),
    });
    const { go } = renderUi(<ConversationList siteId={1} />, { api });
    expect(within(await screen.findByRole('table', { name: 'Conversations' })).getByText('Namer')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('A new conversation'), 'Headlines');
    await userEvent.click(screen.getByRole('combobox', { name: 'With' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Critic' }));
    await userEvent.click(screen.getByRole('button', { name: 'Start' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'conversation', id: 'c2' }));
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ title: 'Headlines', assistant: 'a2', site: 1 });
  });
});
