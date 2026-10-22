// The editor's AI panel: an assistant run on the open page asks the platform
// for suggestions (never an edit) — on the whole page, on one block, or on
// text selected in a block — follows the run live, and points at the page's
// Suggestions tab, read again, where the change waits as a diff. A page the
// person cannot change runs nothing; unsaved edits are pointed out.
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { PageEditor } from '../../src';
import { fakePlatform, pageDetail, renderUi } from '../../../../test/harness';
import { agentRun, assistant, EMPTY, liveStream, page, runRef } from './fixtures';

const SUGGESTION = {
  id: 41,
  op: 'insert',
  block_id: '',
  field: '',
  payload: { type: 'markdown', value: 'Back up nightly.' },
  rationale: 'Headliner: Add a summary',
  status: 'pending',
  agent: 'assistant',
  run_id: 9,
  created_at: '2026-10-22T09:00:00Z',
  target: { type: 'page', id: 5, title: 'Nightly backups' },
  change: { kind: 'block', label: 'insert markdown at the end', before: '', after: 'Back up nightly.', stale: false },
};

function platform(overrides: Record<string, unknown> = {}) {
  let status = 'running';
  let proposed = false;
  const live = liveStream();
  const fake = fakePlatform({
    'GET /api/v2/content/pages/5/': () => pageDetail({ pending_suggestions: proposed ? 1 : 0, ...overrides }),
    'GET /api/v2/ai/assistants/': () => page([assistant()]),
    'GET /api/v2/ai/pipelines/': () => EMPTY,
    'POST /api/v2/ai/assistants/a1/run/': () => ({ run: runRef(9) }),
    'GET /api/v2/agent-runs/9/': () => agentRun(status, { markdown: 'Back up nightly.', suggestions: proposed ? [41] : [] }),
    'GET /api/v2/review/suggestions/': () => page(proposed ? [SUGGESTION] : []),
  });
  const done = () => {
    status = 'succeeded';
    proposed = true;
    live.finish();
  };
  return { ...fake, ...live, done };
}

async function openPanel() {
  await userEvent.click(await screen.findByRole('button', { name: 'AI' }));
  const panel = await screen.findByRole('complementary', { name: 'AI panel' });
  await userEvent.click(within(panel).getByRole('combobox', { name: 'Assistant' }));
  await userEvent.click(await screen.findByRole('option', { name: 'Headliner' }));
  return within(panel);
}

describe('<PageEditor>’s AI panel', () => {
  it('runs an assistant on the whole page, follows the run, and opens the suggestions it made', async () => {
    const { api, calls, stream, done } = platform();
    renderUi(<PageEditor pageId={5} />, { api, stream });
    const panel = await openPanel();
    expect(screen.getByRole('button', { name: 'AI' })).toHaveAttribute('aria-expanded', 'true');
    await userEvent.type(panel.getByLabelText('What should it do?'), 'Add a summary');
    await userEvent.click(panel.getByRole('button', { name: 'Suggest' }));
    expect(await panel.findByRole('status', { name: 'Run #9' })).toHaveTextContent('running');
    expect(calls.find((c) => c.path === '/api/v2/ai/assistants/a1/run/')?.body).toEqual({
      prompt: 'Add a summary',
      page_id: 5,
      suggest: true,
      block_id: '',
      selection: '',
    });
    await waitFor(() => expect(stream).toHaveBeenCalledWith('/api/v2/agent-runs/9/stream/', ['step', 'status', 'end'], expect.any(Function)));
    done();
    expect(await panel.findByText('1 suggestion on this page')).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: 'Suggestions (1)' })).toBeInTheDocument(); // the page was read again
    await userEvent.click(panel.getByRole('button', { name: 'Review them' }));
    expect(screen.getByRole('tab', { name: 'Suggestions (1)' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('Headliner: Add a summary')).toBeInTheDocument();
    expect(calls.some((c) => c.path === '/api/v2/review/suggestions/' && c.query.get('page_id') === '5')).toBe(true);
  });

  it('works on one block, or on text selected in a block, which it offers as soon as it is selected', async () => {
    const { api, calls, stream } = platform();
    renderUi(<PageEditor pageId={5} />, { api, stream });
    const panel = await openPanel();
    await userEvent.click(panel.getByRole('combobox', { name: 'Work on' }));
    await userEvent.click(await screen.findByRole('option', { name: /^Block 2 · markdown · We copy the site/ }));
    await userEvent.type(panel.getByLabelText('What should it do?'), 'Shorter');
    await userEvent.click(panel.getByRole('button', { name: 'Suggest' }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/v2/ai/assistants/a1/run/')).toHaveLength(1));
    expect(calls.find((c) => c.path === '/api/v2/ai/assistants/a1/run/')?.body).toMatchObject({ block_id: 'b2', selection: '' });

    // Select "How it" in the heading's text field: the panel offers that selection and chooses it.
    const heading = within(screen.getByLabelText('Block 1: heading')).getByLabelText('text') as HTMLInputElement;
    act(() => {
      heading.focus();
      heading.setSelectionRange(0, 6);
      fireEvent(document, new Event('selectionchange'));
    });
    expect(panel.getByRole('combobox', { name: 'Work on' })).toHaveValue('The selection in block 1: “How it”');
    await userEvent.click(panel.getByRole('button', { name: 'Suggest' }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/v2/ai/assistants/a1/run/')).toHaveLength(2));
    expect(calls.findLast((c) => c.path === '/api/v2/ai/assistants/a1/run/')?.body).toMatchObject({ block_id: 'b1', selection: 'How it', suggest: true });
  });

  it('runs nothing on a page the person cannot change, and points out unsaved edits', async () => {
    const locked = platform({ lock: "Page 'Nightly backups' is locked by someone else" });
    renderUi(<PageEditor pageId={5} />, { api: locked.api, stream: locked.stream });
    const panel = await openPanel();
    await userEvent.type(panel.getByLabelText('What should it do?'), 'Anything');
    expect(panel.getByRole('button', { name: 'Suggest' })).toBeDisabled();
    expect(panel.getByText(/locked by someone else/)).toBeInTheDocument();
  });

  it('says the assistant reads the saved draft when there are unsaved edits', async () => {
    const { api, stream } = platform();
    renderUi(<PageEditor pageId={5} />, { api, stream });
    await userEvent.type(await screen.findByLabelText(/^Title/), ' again');
    const panel = await openPanel();
    expect(panel.getByText(/reads the saved draft/)).toBeInTheDocument();
  });
});
