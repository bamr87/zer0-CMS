// Create: a page of a type its parent allows, as a draft. The drafter agent
// runs only when there is a brief to write from and the person asked for it —
// never because a box stayed ticked after the topic was cleared. Where it goes
// is searched on the platform, so a site with more sections than one answer
// holds still offers every one of them.
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
    'POST /api/v2/agent-runs/': () => ({ id: 'r30', agent: 'drafter', status: 'queued', is_final: false }),
  });
}

const posted = (calls: ReturnType<typeof platform>['calls']) => calls.filter((c) => c.method === 'POST').map((c) => c.path);

async function chooseWhere(name: string, typed = name.split(' (')[0] ?? name) {
  await userEvent.type(await screen.findByLabelText('Where', { selector: 'input' }), typed);
  await userEvent.click(await screen.findByRole('option', { name }));
}

describe('<CreatePage>', () => {
  it('creates a draft and starts no run once the brief’s topic is cleared', async () => {
    const { api, calls } = platform();
    const { go } = renderUi(<CreatePage siteId={1} />, { api });
    await chooseWhere('Posts (Collection page)');
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
    await chooseWhere('Posts (Collection page)');
    await userEvent.type(await screen.findByLabelText(/^Title/), 'Fresh idea');
    await userEvent.type(screen.getByLabelText('Brief: what is it about?'), 'Backups');
    await userEvent.click(screen.getByLabelText(/Draft with the drafter agent/));
    await userEvent.click(screen.getByRole('button', { name: 'Create and draft' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'run', id: 'r30' }));
    expect(posted(calls)).toEqual(['/api/v2/content/pages/', '/api/v2/agent-runs/']);
    expect(calls.at(-1)?.body).toEqual({ agent: 'drafter', page_id: 12 });
  });

  it('searches every section of the site as the person types, past the first hundred', async () => {
    const sections = Array.from({ length: 200 }, (_, at) => ({ ...SECTION, id: 1000 + at, title: `Section ${at + 1}` }));
    const { api, calls } = fakePlatform({
      'GET /api/v2/content/pages/': ({ url }) => {
        const q = (url.searchParams.get('q') ?? '').toLowerCase();
        const found = q ? sections.filter((s) => s.title.toLowerCase() === q) : sections;
        const results = found.slice(0, Number(url.searchParams.get('page_size') ?? 20));
        return { count: found.length, next: null, previous: null, results };
      },
      'GET /api/v2/content/pages/1149/types/': () => [{ type: 'cms.ArticlePage', label: 'Article page' }],
      'POST /api/v2/content/pages/': () => pageDetail({ id: 12, status: 'draft' }),
    });
    const { go } = renderUi(<CreatePage siteId={1} />, { api });
    await chooseWhere('Section 150 (Collection page)');
    const listed = calls.filter((c) => c.method === 'GET' && c.path === '/api/v2/content/pages/');
    expect(listed.map((c) => c.query.get('q'))).toContain('Section 150');
    expect(listed.every((c) => c.query.get('site') === '1' && c.query.get('can_have_children') === 'true')).toBe(true);
    await userEvent.type(screen.getByLabelText(/^Title/), 'Deep in the tree');
    await userEvent.click(screen.getByRole('button', { name: 'Create draft' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'page', id: 12 }));
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ parent: 1149, type: 'cms.ArticlePage', fields: { title: 'Deep in the tree' }, body: [] });
  });

  it('creates nothing until the person says where the page goes', async () => {
    const { api } = platform();
    renderUi(<CreatePage siteId={1} />, { api });
    await userEvent.type(await screen.findByLabelText(/^Title/), 'Fresh idea');
    expect(screen.getByRole('button', { name: 'Create draft' })).toBeDisabled();
  });
});
