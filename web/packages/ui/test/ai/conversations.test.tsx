// Conversations: a message sent is answered by a run the thread follows live
// — the reply waits as a queued message with the run's progress, and the
// answer shows when the run is done; an answer can be asked for again (of the
// same assistant or another), promoted to a brief or a draft (which opens as
// a brief), or deleted; a new conversation starts with its assistant.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ConversationList, ConversationThread } from '../../src';
import { fakePlatform, renderUi } from '../../../../test/harness';
import { agentRun, assistant, EMPTY, liveStream, page, runRef } from './fixtures';

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

const cursor = <T,>(results: T[]) => ({ next: null, previous: null, results });
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
      'GET /api/v2/ai/conversations/c1/messages/': () => cursor(messages),
      'POST /api/v2/ai/conversations/c1/messages/': () => {
        messages = [...messages, message(3, 'user', 'What is my name?'), message(4, 'assistant', '', { status: 'queued', run: runRef(9) })];
        return { message: messages[2], reply: messages[3], run: runRef(9) };
      },
      'GET /api/v2/agent-runs/9/': () => agentRun(status),
    });
    renderUi(<ConversationThread id="c1" />, { api, stream });
    const thread = within(await screen.findByRole('list', { name: 'Messages' }));
    expect(await thread.findByRole('document', { name: "Namer's answer" })).toHaveTextContent('Hello Alice');
    expect(thread.getByText('fake · fake-1 · 7 tokens · $0.001000')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Your message'), 'What is my name?');
    await userEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ text: 'What is my name?', answer: true });
    expect(screen.getByLabelText('Your message')).toHaveValue('');
    const waiting = await thread.findByRole('listitem', { name: 'Namer, message 4' });
    expect(within(waiting).getByText('queued')).toBeInTheDocument();
    expect(await within(waiting).findByRole('status', { name: 'Run #9' })).toBeInTheDocument();
    await waitFor(() => expect(stream).toHaveBeenCalledWith('/api/v2/agent-runs/9/stream/', ['step', 'status', 'end'], expect.any(Function)));
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
      'GET /api/v2/ai/conversations/c1/messages/': () => cursor([message(1, 'user', 'Ideas?'), message(2, 'assistant', 'Three ideas.')]),
      'POST /api/v2/ai/messages/m2/rerun/': () => ({ message: message(3, 'assistant', '', { status: 'queued', run: runRef(9) }), run: runRef(9) }),
      'POST /api/v2/ai/messages/m2/promote/': () => ({ brief: { id: 'b7' }, run: runRef(10) }),
      'GET /api/v2/agent-runs/9/': () => agentRun('running'),
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
