// Assistants: created with their instructions, parameters, schema and tools;
// tried on a prompt with the run followed live until its answer shows,
// rendered; exported as a document (shown, copied, saved) and imported from
// one; an assistant shared with someone is theirs to run, not to change.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { AssistantEditor, AssistantList } from '../../src';
import { fakePlatform, renderUi } from '../../../../test/harness';
import { agentRun, assistant, EMPTY, liveStream, page, runRef, schema } from './fixtures';

const lists = {
  'GET /api/v2/ai/providers/': () => EMPTY,
  'GET /api/v2/ai/models/': () => EMPTY,
  'GET /api/v2/ai/output-schemas/': () => page([schema()]),
  'GET /api/v2/ai/assistants/tools/': () => [
    { name: 'content.get_page', description: 'Read a page.' },
    { name: 'content.search', description: 'Search pages.' },
  ],
  'GET /api/v2/sites/': () => [],
};

describe('<AssistantEditor>', () => {
  it('creates an assistant with its parameters, schema and tools, then opens it', async () => {
    const { api, calls } = fakePlatform({ ...lists, 'POST /api/v2/ai/assistants/': ({ body }) => ({ ...assistant(), ...(body as object), id: 'a2' }) });
    const { go } = renderUi(<AssistantEditor />, { api });
    await userEvent.type(await screen.findByLabelText(/^Name/), 'Headliner');
    await userEvent.type(screen.getByLabelText('Instructions'), 'Write one-line headlines.');
    await userEvent.type(screen.getByLabelText('Temperature'), '0.4');
    await userEvent.click(screen.getByRole('combobox', { name: 'Output schema' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Story' }));
    await userEvent.click(screen.getByRole('combobox', { name: 'Tools' }));
    await userEvent.click(await screen.findByRole('option', { name: 'content.search' }));
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'assistant', id: 'a2' }));
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
      name: 'Headliner',
      description: '',
      instructions: 'Write one-line headlines.',
      prompt_template: '',
      provider: null,
      model: null,
      output_schema: 's1',
      tools: ['content.search'],
      visibility: 'private',
      site: null,
      params: { temperature: 0.4 },
    });
  });

  it('runs on a prompt and shows the answer once the run it follows has finished', async () => {
    const { stream, finish } = liveStream();
    let status = 'running';
    const { api, calls } = fakePlatform({
      ...lists,
      'GET /api/v2/ai/assistants/a1/': () => assistant(),
      'POST /api/v2/ai/assistants/a1/run/': () => ({ run: runRef(9) }),
      'GET /api/v2/agent-runs/9/': () =>
        agentRun(status, { text: '{"headline": "Cats win"}', markdown: '## Cats win\n\nThe sofa is theirs.', json: { headline: 'Cats win' }, provider: 'fake', model: 'fake-1' }),
    });
    renderUi(<AssistantEditor id="a1" />, { api, stream });
    await userEvent.type(await screen.findByLabelText('Prompt'), 'cats');
    await userEvent.click(screen.getByRole('button', { name: 'Run' }));
    expect(await screen.findByRole('status', { name: 'Run #9' })).toHaveTextContent('running');
    expect(calls.find((c) => c.path === '/api/v2/ai/assistants/a1/run/')?.body).toEqual({ prompt: 'cats', suggest: false, block_id: '', selection: '' });
    await waitFor(() => expect(stream).toHaveBeenCalled());
    status = 'succeeded';
    finish();
    const answer = await screen.findByRole('document', { name: 'The answer' });
    expect(within(answer).getByRole('heading', { name: 'Cats win' })).toBeInTheDocument();
    expect(answer).toHaveTextContent('The sofa is theirs.');
    // With an output schema, the answer is also the validated JSON it was rendered from.
    expect(screen.getByLabelText('The structured answer')).toHaveTextContent('"headline": "Cats win"');
  });

  it('exports an assistant as a document to copy or save', async () => {
    const document = { name: 'Headliner', instructions: 'Write headlines.', provider: null, model: null, output_schema: null };
    const { api } = fakePlatform({ ...lists, 'GET /api/v2/ai/assistants/a1/': () => assistant(), 'GET /api/v2/ai/assistants/a1/export/': () => document });
    renderUi(<AssistantEditor id="a1" />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Export' }));
    const dialog = await screen.findByRole('dialog', { name: 'Export Headliner' });
    expect(within(dialog).getByLabelText('The exported document')).toHaveTextContent('"instructions": "Write headlines."');
    const download = within(dialog).getByRole('link', { name: 'Download headliner.json' });
    expect(download).toHaveAttribute('download', 'headliner.json');
    expect(decodeURIComponent(download.getAttribute('href') ?? '')).toContain('"name": "Headliner"');
    expect(within(dialog).getByRole('button', { name: 'Copy' })).toBeInTheDocument();
  });

  it('lets someone it is shared with run it, not change it', async () => {
    const { api } = fakePlatform({ ...lists, 'GET /api/v2/ai/assistants/a1/': () => assistant({ owner: 'alice', visibility: 'shared', can_edit: false }) });
    renderUi(<AssistantEditor id="a1" />, { api });
    expect(await screen.findByText(/alice shares this with you/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Name/)).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Save' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Run' })).toBeInTheDocument();
  });
});

describe('<AssistantList>', () => {
  it('lists assistants, opens one, and imports a document as a new one', async () => {
    const { api, calls } = fakePlatform({
      ...lists,
      'GET /api/v2/ai/assistants/': () => page([assistant({ output_schema: 's1', visibility: 'shared' })]),
      'POST /api/v2/ai/assistants/import/': () => assistant({ id: 'a9', name: 'Imported' }),
    });
    const { go } = renderUi(<AssistantList />, { api });
    const table = await screen.findByRole('table', { name: 'Assistants' });
    expect(within(table).getByText('Story')).toBeInTheDocument();
    await userEvent.click(within(table).getByRole('button', { name: 'Headliner' }));
    expect(go).toHaveBeenCalledWith({ to: 'assistant', id: 'a1' });
    await userEvent.click(screen.getByRole('button', { name: 'Import an assistant' }));
    const dialog = await screen.findByRole('dialog', { name: 'Import an assistant' });
    await userEvent.click(within(dialog).getByLabelText(/The document/));
    await userEvent.paste('{"name": "Imported", "instructions": "Be brief."}');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Import' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'assistant', id: 'a9' }));
    expect(calls.find((c) => c.path === '/api/v2/ai/assistants/import/')?.body).toEqual({ name: 'Imported', instructions: 'Be brief.' });
  });

  it('says so when there are none yet', async () => {
    const { api } = fakePlatform({ ...lists, 'GET /api/v2/ai/assistants/': () => EMPTY });
    const { go } = renderUi(<AssistantList />, { api });
    expect(await screen.findByText('No assistants yet')).toBeInTheDocument();
    for (const button of screen.getAllByRole('button', { name: 'New assistant' })) await userEvent.click(button);
    expect(go).toHaveBeenCalledTimes(2);
    expect(go).toHaveBeenLastCalledWith({ to: 'assistant' });
  });
});
