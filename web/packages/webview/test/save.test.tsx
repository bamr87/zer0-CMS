// Downloads in the extension's webviews (W1-18): a webview cannot save a file,
// so a download button there hands the host an intent — the path that answers
// the file, the JSON field that holds its text, and the name to offer — never
// the file's text, and never as a link the host would try to open. The host
// fetches the path again through its own gates and writes where the person
// chooses (src/core/studio/bridge.ts, src/studio/studio.ts).
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { App } from '../src/App';
import type { Port } from '../src/transport';
import { fakePlatform, pageDetail, type Handler } from '../../../test/harness';

type Message = Record<string, unknown>;

/** The extension host as the webview sees it, answering each request from a fake platform. */
function host(routes: Record<string, Handler>) {
  const platform = fakePlatform(routes);
  const listeners = new Set<(message: unknown) => void>();
  const sent: Message[] = [];
  const deliver = (message: unknown) => act(() => listeners.forEach((listen) => listen(message)));
  const port: Port = {
    post: (message) => {
      const m = message as Message;
      sent.push(m);
      if (m.type !== 'api') return;
      const body = typeof m.body === 'string' ? m.body : undefined;
      void platform
        .fetch(new Request(`https://platform.test${String(m.path)}`, { method: String(m.method), ...(body ? { body } : {}) }))
        .then(async (reply) => deliver({ type: 'api', id: m.id, status: reply.status, body: await reply.text(), headers: { 'Content-Type': 'application/json' } }));
    },
    listen: (handler) => {
      listeners.add(handler);
      return () => void listeners.delete(handler);
    },
  };
  return { port, sent, deliver };
}

const MARKDOWN = '# The Impairment\n\n---\n';
const BOOK = {
  id: 20, slug: 'impairment', title: 'The Impairment', status: 'drafting', page_status: 'live', profile: 'book', logline: '', genre: '',
  chapters: 0, planned_chapters: 14, word_count: 0, target_word_count: 90000, progress: 0, site_id: 1, template: false,
  stats: { chapters: 0, status_counts: {}, word_count: 0, target_word_count: 90000, planned_chapters: 14, average: 0, longest: null, shortest: null, progress: 0 },
  chapter_list: [], errors: 0, warnings: 0, documents: [], can_edit: true, can_add_chapter: true,
};
const PLATFORM: Record<string, Handler> = {
  'GET /api/v2/sites/': () => [],
  'GET /api/v2/review/suggestions/': () => ({ count: 0, next: null, previous: null, results: [] }),
  'GET /api/v2/agent-runs/': () => ({ count: 0, next: null, previous: null, results: [] }),
  'GET /api/v2/books/': () => [BOOK],
  'GET /api/v2/books/20/': () => BOOK,
  'GET /api/v2/content/pages/20/': () => pageDetail({ id: 20, type: 'cms.BookPage' }),
  'GET /api/v2/books/tasks/': () => [],
  'GET /api/v2/books/20/issues/': () => [],
  'GET /api/v2/books/20/manuscript/': () => ({ filename: 'impairment-manuscript.md', markdown: MARKDOWN, word_count: 4 }),
};

describe('a download in the extension', () => {
  it("posts the manuscript's path, field and file name for the host to save — no text, no link to open", async () => {
    const extension = host(PLATFORM);
    render(<App view="dashboard" port={extension.port} />);
    await screen.findByRole('tablist', { name: 'Workspaces' });
    await extension.deliver({ type: 'go', to: { to: 'book', id: 20 } });
    await userEvent.click(await screen.findByRole('tab', { name: 'Manuscript' }));
    await userEvent.click(screen.getByRole('button', { name: 'Build the manuscript' }));
    await screen.findByText(/title page, act headings/);
    await userEvent.click(screen.getByRole('button', { name: 'Download impairment-manuscript.md' }));

    const saves = extension.sent.filter((m) => m.type === 'save');
    expect(saves).toEqual([{ type: 'save', path: '/api/v2/books/20/manuscript/?include_outline=false', field: 'markdown', filename: 'impairment-manuscript.md' }]);
    expect(JSON.stringify(saves)).not.toContain('The Impairment');
    expect(extension.sent.some((m) => m.type === 'open')).toBe(false);
    expect(screen.queryByRole('link', { name: /Download/ })).toBeNull();
  });

  it('posts an export by its path, with no field: the host saves the whole document', async () => {
    const assistant = {
      id: 'a1', name: 'Headliner', description: '', instructions: 'Write headlines.', provider: null, model: null, output_schema: null,
      owner: 'editor', site: null, visibility: 'private', can_edit: true, created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z',
    };
    const extension = host({
      ...PLATFORM,
      'GET /api/v2/ai/assistants/': () => ({ count: 1, next: null, previous: null, results: [assistant] }),
      'GET /api/v2/ai/assistants/a1/': () => assistant,
      'GET /api/v2/ai/assistants/a1/export/': () => ({ name: 'Headliner', instructions: 'Write headlines.' }),
      'GET /api/v2/ai/providers/': () => [],
      'GET /api/v2/ai/output-schemas/': () => ({ count: 0, next: null, previous: null, results: [] }),
      'GET /api/v2/me': () => ({ authenticated: true, user: { id: 1, username: 'editor', name: 'Ed', email: '', is_staff: true, is_superuser: false }, permissions: [], csrf_token: 'x' }),
    });
    render(<App view="ai" port={extension.port} />);
    await extension.deliver({ type: 'go', to: { to: 'assistant', id: 'a1' } });
    await userEvent.click(await screen.findByRole('button', { name: 'Export' }));
    const dialog = await screen.findByRole('dialog', { name: 'Export Headliner' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Download headliner.json' }));
    expect(extension.sent.filter((m) => m.type === 'save')).toEqual([{ type: 'save', path: '/api/v2/ai/assistants/a1/export/', filename: 'headliner.json' }]);
  });
});
