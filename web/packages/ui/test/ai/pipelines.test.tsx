// Pipelines: created from their steps (once, however the button is clicked)
// and opened; steps are reordered by dragging — here from the keyboard, as
// @dnd-kit's sensor reads it (space picks a step up, an arrow moves it, space
// drops it) — or with the move buttons, and the whole list is saved in the
// new order; a step reads what its source says; the pipeline runs on a
// prompt and its run is followed.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PipelineEditor } from '../../src';
import { fakePlatform, renderUi } from '../../../../test/harness';
import { agentRun, assistant, liveStream, page, RUN, runRef } from './fixtures';

const pipeline = {
  owner: 'editor',
  site: null,
  visibility: 'private',
  can_edit: true,
  created_at: '2026-10-22T09:00:00Z',
  updated_at: '2026-10-22T09:00:00Z',
  id: 'p1',
  name: 'Draft, then edit',
  description: '',
  steps: [
    { position: 1, assistant: 'a1', source: 'previous', source_field: '' },
    { position: 2, assistant: 'a2', source: 'previous', source_field: '' },
    { position: 3, assistant: 'a3', source: 'conversation', source_field: '' },
  ],
};

function platform() {
  return fakePlatform({
    'GET /api/v2/ai/pipelines/p1/': () => pipeline,
    'PATCH /api/v2/ai/pipelines/p1/': ({ body }) => ({ ...pipeline, ...(body as object) }),
    'GET /api/v2/ai/assistants/': () =>
      page([assistant({ id: 'a1', name: 'Drafter' }), assistant({ id: 'a2', name: 'Editor' }), assistant({ id: 'a3', name: 'Headliner' })]),
    'GET /api/v2/sites/': () => [],
  });
}

const savedOrder = (calls: ReturnType<typeof platform>['calls']) =>
  (calls.findLast((c) => c.method === 'PATCH')?.body as { steps: { assistant: string; source: string }[] }).steps.map((s) => s.assistant);

describe('<PipelineEditor>', () => {
  afterEach(() => vi.restoreAllMocks());

  it('moves a step by dragging it from the keyboard, and saves the steps in the new order', async () => {
    // jsdom lays nothing out: give each step a place in a column, so the sensor can find the one below.
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const step = this.closest('li');
      const at = step?.parentElement ? [...step.parentElement.children].indexOf(step) : 0;
      return { x: 0, y: at * 60, top: at * 60, left: 0, right: 600, bottom: at * 60 + 50, width: 600, height: 50, toJSON: () => ({}) } as DOMRect;
    });
    const { api, calls } = platform();
    renderUi(<PipelineEditor id="p1" />, { api });
    const handle = await screen.findByRole('button', { name: 'Drag step 1' });
    handle.focus();
    await userEvent.keyboard('[Space]');
    await userEvent.keyboard('[ArrowDown]');
    await userEvent.keyboard('[Space]');
    const steps = within(screen.getByRole('list', { name: 'Steps' }));
    await waitFor(() => expect(steps.getByRole('listitem', { name: 'Step 1' })).toHaveTextContent('Editor'));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(savedOrder(calls)).toEqual(['a2', 'a1', 'a3']);
    expect((calls.findLast((c) => c.method === 'PATCH')?.body as { steps: unknown[] }).steps[2]).toEqual({ assistant: 'a3', source: 'conversation', source_field: '' });
  });

  it('moves, adds and removes steps with the buttons too', async () => {
    const { api, calls } = platform();
    renderUi(<PipelineEditor id="p1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Move step 3 up' }));
    await userEvent.click(screen.getByRole('button', { name: 'Remove step 1' }));
    await userEvent.click(screen.getByRole('button', { name: 'Add a step' }));
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled(); // the new step has no assistant yet
    const added = screen.getByRole('listitem', { name: 'Step 3' });
    await userEvent.click(within(added).getByRole('combobox', { name: 'Assistant' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Drafter' }));
    await userEvent.click(within(added).getByRole('combobox', { name: 'Reads' }));
    await userEvent.click(await screen.findByRole('option', { name: 'A field of the page' }));
    await userEvent.type(within(added).getByLabelText('Field'), 'summary');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    const body = calls.findLast((c) => c.method === 'PATCH')?.body as { steps: unknown[] };
    expect(body.steps).toEqual([
      { assistant: 'a3', source: 'conversation', source_field: '' },
      { assistant: 'a2', source: 'previous', source_field: '' },
      { assistant: 'a1', source: 'page', source_field: 'summary' },
    ]);
  });

  it('creates a pipeline from its steps and opens it', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/ai/assistants/': () => page([assistant({ id: 'a1', name: 'Drafter' }), assistant({ id: 'a2', name: 'Editor' })]),
      'GET /api/v2/sites/': () => [],
      'POST /api/v2/ai/pipelines/': ({ body }) => ({ ...pipeline, ...(body as object), id: 'p9' }),
    });
    const { go } = renderUi(<PipelineEditor />, { api });
    expect(await screen.findByRole('heading', { name: 'New pipeline' })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^Name/), 'Draft, then edit');
    for (const name of ['Drafter', 'Editor']) {
      await userEvent.click(screen.getByRole('button', { name: 'Add a step' }));
      const step = screen.getAllByRole('listitem').at(-1);
      if (!step) throw new Error('no step was added');
      await userEvent.click(within(step).getByRole('combobox', { name: 'Assistant' }));
      await userEvent.click(await screen.findByRole('option', { name }));
    }
    await userEvent.dblClick(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'pipeline', id: 'p9' }));
    const posts = calls.filter((c) => c.method === 'POST');
    expect(posts).toHaveLength(1); // a double click makes one pipeline
    expect(posts[0]?.body).toEqual({
      name: 'Draft, then edit',
      description: '',
      visibility: 'private',
      site: null,
      steps: [
        { assistant: 'a1', source: 'previous', source_field: '' },
        { assistant: 'a2', source: 'previous', source_field: '' },
      ],
    });
  });

  it('runs the pipeline on a prompt and shows what its last step wrote', async () => {
    const { stream, finish } = liveStream();
    let status = 'running';
    const { api, calls } = fakePlatform({
      'GET /api/v2/ai/pipelines/p1/': () => pipeline,
      'GET /api/v2/ai/assistants/': () => page([assistant()]),
      'GET /api/v2/sites/': () => [],
      'POST /api/v2/ai/pipelines/p1/run/': () => ({ run: runRef() }),
      [`GET /api/v2/agent-runs/${RUN}/`]: () => agentRun(status, { text: 'A tight draft.', markdown: 'A tight draft.', steps: ['r10', 'r11', 'r12'] }),
    });
    renderUi(<PipelineEditor id="p1" />, { api, stream });
    await userEvent.click(await screen.findByRole('button', { name: 'Run' }));
    expect(calls.find((c) => c.path === '/api/v2/ai/pipelines/p1/run/')?.body).toEqual({ prompt: '', suggest: false, block_id: '', selection: '' });
    await waitFor(() => expect(stream).toHaveBeenCalled());
    status = 'succeeded';
    finish();
    expect(await screen.findByRole('document', { name: 'The answer' })).toHaveTextContent('A tight draft.');
  });
});
