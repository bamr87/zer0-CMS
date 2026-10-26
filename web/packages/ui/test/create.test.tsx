// Create: a page of a type its parent allows, as a draft. The drafter agent
// runs only when there is a brief to write from and the person asked for it —
// never because a box stayed ticked after the topic was cleared.
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { CreatePage } from '../src';
import { fakePlatform, pageDetail, renderUi } from '../../../test/harness';

const SECTION = { ...pageDetail(), id: 3, title: 'Posts', type_label: 'Collection page', children: 1 };

function platform() {
  return fakePlatform({
    'GET /api/v2/content/pages/': () => ({ count: 1, next: null, previous: null, results: [SECTION] }),
    'GET /api/v2/content/pages/3/types/': () => [{ type: 'cms.ArticlePage', label: 'Article page' }],
    'POST /api/v2/content/pages/': () => pageDetail({ id: 12, status: 'draft' }),
    'POST /api/v2/agent-runs/': () => ({ id: 30, agent: 'drafter', status: 'queued', is_final: false }),
  });
}

const posted = (calls: ReturnType<typeof platform>['calls']) => calls.filter((c) => c.method === 'POST').map((c) => c.path);

describe('<CreatePage>', () => {
  it('creates a draft and starts no run once the brief’s topic is cleared', async () => {
    const { api, calls } = platform();
    const { go } = renderUi(<CreatePage siteId={1} />, { api });
    await userEvent.type(await screen.findByLabelText(/^Title/), 'Fresh idea');
    const topic = screen.getByLabelText('Brief: what is it about?');
    await userEvent.type(topic, 'Backups');
    await userEvent.click(screen.getByLabelText(/Draft with the drafter agent/));
    expect(screen.getByRole('button', { name: 'Create and draft' })).toBeInTheDocument();
    await userEvent.clear(topic);
    await userEvent.click(screen.getByRole('button', { name: 'Create draft' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'page', id: 12 }));
    expect(posted(calls)).toEqual(['/api/v2/content/pages/']);
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ parent: 3, type: 'cms.ArticlePage', fields: { title: 'Fresh idea' }, body: [] });
  });

  it('hands the brief to the drafter when asked, and opens its run', async () => {
    const { api, calls } = platform();
    const { go } = renderUi(<CreatePage siteId={1} />, { api });
    await userEvent.type(await screen.findByLabelText(/^Title/), 'Fresh idea');
    await userEvent.type(screen.getByLabelText('Brief: what is it about?'), 'Backups');
    await userEvent.click(screen.getByLabelText(/Draft with the drafter agent/));
    await userEvent.click(screen.getByRole('button', { name: 'Create and draft' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'run', id: 30 }));
    expect(posted(calls)).toEqual(['/api/v2/content/pages/', '/api/v2/agent-runs/']);
    expect(calls.at(-1)?.body).toEqual({ agent: 'drafter', page_id: 12 });
  });
});
