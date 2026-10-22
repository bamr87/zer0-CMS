// The Research workspace: a page is captured by asking the platform (which
// fetches it), a note and a document are added, a web search is a run; a
// source shows its text, summary and entities, a summary is asked for, and a
// suggested passage becomes a quote only when kept; a question's answer shows
// its citations, checked or not; and from the editor a draft cites a source
// and is fact-checked, its corrections waiting in Review. A fake platform
// stands behind the real client.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { PageResearch, ResearchWorkspace, SourceView } from '../src';
import { AskPanel } from '../src/research/AskPanel';
import { CaptureSource } from '../src/research/CaptureSource';
import { fakePlatform, renderUi, type Call } from '../../../test/harness';

const page = (results: unknown[]) => ({ next: null, previous: null, results });
const run = (id: number, status = 'queued') => ({ id, status, links: { self: `/api/v2/agent-runs/${id}/`, stream: `/api/v2/agent-runs/${id}/stream/` } });
const owned = { owner: 'editor', site: null, visibility: 'private', created_at: '2026-10-22T09:00:00Z', updated_at: '2026-10-22T09:00:00Z' };

const source = (rest: Record<string, unknown> = {}) => ({
  ...owned,
  id: 's1',
  kind: 'url',
  collection: 'c1',
  url: 'https://example.com/backups',
  title: 'Backups explained',
  author: 'Ada Lovelace',
  site_name: 'Example News',
  published: '2026-10-01',
  status: 'ready',
  error: '',
  robots: 'allowed',
  fetched_at: '2026-10-22T09:00:00Z',
  language: 'en',
  text: 'A nightly backup to a second disk costs almost nothing.',
  metadata: {},
  summary: 'Nightly backups save small sites.',
  entities: [{ name: 'Ada Lovelace', kind: 'person' }],
  highlights: ['A nightly backup to a second disk costs almost nothing.'],
  summary_run: run(30, 'succeeded'),
  feed: null,
  ...rest,
});

const posts = (calls: Call[]) => calls.filter((c) => c.method === 'POST');

describe('<ResearchWorkspace>', () => {
  it('lists collections and sources, and a source opens on its own page', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/research/collections/': () => page([{ ...owned, id: 'c1', name: 'Backups', description: '' }]),
      'GET /api/v2/research/sources/': () => page([source(), source({ id: 's2', title: '', url: 'https://example.com/x', status: 'failed', error: 'the site answered HTTP 404' })]),
    });
    const { go } = renderUi(<ResearchWorkspace />, { api });
    await userEvent.click(await screen.findByText('Backups'));
    await waitFor(() => expect(calls.at(-1)?.query.get('collection')).toBe('c1'));
    expect(await screen.findByText('the site answered HTTP 404')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Backups explained' }));
    expect(go).toHaveBeenCalledWith({ to: 'source', id: 's1' });
  });
});

describe('<CaptureSource>', () => {
  it('asks the platform to capture a page, adds a note and a document, and searches the web as a run', async () => {
    const { api, calls } = fakePlatform({
      'POST /api/v2/research/sources/': () => source({ status: 'pending' }),
      'POST /api/v2/research/sources/upload/': () => source({ kind: 'document' }),
      'POST /api/v2/research/sources/search/': () => ({ run: run(41) }),
      'GET /api/v2/agent-runs/41/': () => ({ id: 41, status: 'succeeded', is_final: true, output: {}, error: '' }),
    });
    const { container } = renderUi(<CaptureSource collection="c1" />, { api });
    await userEvent.type(screen.getByLabelText('Page address'), 'https://example.com/backups');
    await userEvent.click(screen.getByRole('button', { name: 'Capture' }));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(calls.at(-1)?.body).toEqual({ kind: 'url', url: 'https://example.com/backups', collection: 'c1' });
    await userEvent.click(screen.getByRole('radio', { name: 'Note' }));
    await userEvent.type(screen.getByLabelText('Title'), 'Call the host');
    await userEvent.type(screen.getByLabelText('Note', { selector: 'textarea' }), 'About restores.');
    await userEvent.click(screen.getByRole('button', { name: 'Add note' }));
    await waitFor(() => expect(posts(calls)).toHaveLength(2));
    expect(posts(calls)[1]?.body).toEqual({ kind: 'note', title: 'Call the host', text: 'About restores.', collection: 'c1' });
    await userEvent.click(screen.getByRole('radio', { name: 'Upload' }));
    const input = container.querySelector('input[type="file"]');
    if (!(input instanceof HTMLInputElement)) throw new Error('no file input');
    await userEvent.upload(input, new File(['# Restores'], 'guide.md', { type: 'text/markdown' }));
    await userEvent.click(screen.getByRole('button', { name: 'Upload' }));
    await waitFor(() => expect(posts(calls).map((c) => c.path)).toContain('/api/v2/research/sources/upload/'));
    await userEvent.click(screen.getByRole('radio', { name: 'Search the web' }));
    await userEvent.type(screen.getByLabelText('Search for'), 'nightly backups');
    await userEvent.click(screen.getByRole('button', { name: 'Search' }));
    await waitFor(() => expect(calls.some((c) => c.path === '/api/v2/agent-runs/41/')).toBe(true));
    expect(posts(calls).at(-1)?.body).toEqual({ query: 'nightly backups', max_results: 5, collection: 'c1' });
  });
});

describe('<SourceView>', () => {
  it('shows the text, summary and entities; summarizes on request; keeps a suggested passage as a quote', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/research/sources/s1/': () => source(),
      'GET /api/v2/research/quotes/': () => page([]),
      'GET /api/v2/research/citations/': () => page([{ id: 'x1', source: 's1', source_title: 'Backups explained', source_url: '', quote: null, page: 5, page_title: 'Nightly backups', brief: null, note: '', created_by: 'editor', created_at: '' }]),
      'GET /api/v2/content/pages/': () => ({ count: 0, next: null, previous: null, results: [] }),
      'POST /api/v2/research/sources/s1/summarize/': () => ({ source: source(), run: run(31) }),
      'POST /api/v2/research/quotes/': () => ({ id: 'q1', source: 's1', text: 'A nightly backup', note: '', location: '', owner: 'editor', created_at: '' }),
    });
    const { go } = renderUi(<SourceView sourceId="s1" />, { api });
    expect(await screen.findByRole('heading', { name: 'Backups explained' })).toBeInTheDocument();
    expect(screen.getByLabelText('Extracted text')).toHaveTextContent('A nightly backup to a second disk');
    expect(screen.getByText('Nightly backups save small sites.')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Entities')).getByText('Ada Lovelace · person')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Keep as a quote' }));
    await waitFor(() => expect(posts(calls).at(-1)?.body).toEqual({ source: 's1', text: 'A nightly backup to a second disk costs almost nothing.' }));
    await userEvent.click(screen.getByRole('button', { name: 'Summarize again' }));
    await waitFor(() => expect(posts(calls).at(-1)?.path).toBe('/api/v2/research/sources/s1/summarize/'));
    await userEvent.click(await screen.findByRole('button', { name: 'Nightly backups' }));
    expect(go).toHaveBeenCalledWith({ to: 'page', id: 5 });
  });
});

describe('<AskPanel>', () => {
  it('asks a question and shows its cited answer, each quote checked or not', async () => {
    const answered = {
      ...owned,
      id: 'q1',
      collection: 'c1',
      text: 'How often should we back up?',
      answer: 'Nightly [S1].',
      citations: [
        { label: 'S1', source: 's1', title: 'Backups explained', quote: 'A nightly backup', verified: true },
        { label: 'S1', source: 's1', title: 'Backups explained', quote: 'Words it never says', verified: false },
      ],
      status: 'ready',
      error: '',
      run: run(33, 'succeeded'),
    };
    const { api, calls } = fakePlatform({
      'GET /api/v2/research/questions/': () => page([answered]),
      'POST /api/v2/research/questions/': () => ({ question: { ...answered, status: 'pending', answer: '' }, run: run(34) }),
    });
    const { go } = renderUi(<AskPanel collection="c1" />, { api });
    const card = await screen.findByRole('article', { name: 'How often should we back up?' });
    expect(within(card).getByText('Nightly [S1].')).toBeInTheDocument();
    expect(within(card).getByText('quote checked')).toBeInTheDocument();
    expect(within(card).getByText('not found in the source')).toBeInTheDocument();
    await userEvent.click(within(card).getAllByRole('button', { name: 'Backups explained' })[0] as HTMLElement);
    expect(go).toHaveBeenCalledWith({ to: 'source', id: 's1' });
    await userEvent.type(screen.getByLabelText(/Ask your sources/), 'Which disk?');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await waitFor(() => expect(posts(calls).at(-1)?.body).toEqual({ text: 'Which disk?', collection: 'c1' }));
  });
});

describe('<PageResearch>', () => {
  it('cites a source on the draft, fact-checks it, and sends the corrections to Review', async () => {
    const check = {
      ...owned,
      id: 'f1',
      page: 5,
      page_title: 'Nightly backups',
      collection: null,
      summary: 'One claim is wrong.',
      findings: [
        { block: 'b1', claim: 'Back up weekly', verdict: 'contradicted', explanation: 'The guide says nightly.', correction: 'Back up nightly.', sources: [{ id: 's1', title: 'Backups explained' }], suggestion: 77, error: '' },
        { block: 'b2', claim: 'Keep two copies', verdict: 'supported', explanation: 'It says so.', correction: '', sources: [], suggestion: null, error: '' },
      ],
      status: 'ready',
      error: '',
      run: run(9, 'succeeded'),
    };
    const { api, calls } = fakePlatform({
      'GET /api/v2/research/citations/': () => page([]),
      'GET /api/v2/research/sources/': () => page([source()]),
      'GET /api/v2/research/collections/': () => page([]),
      'GET /api/v2/research/fact-checks/': () => page([check]),
      'POST /api/v2/research/citations/': () => ({ id: 'x1', source: 's1', source_title: 'Backups explained', source_url: '', quote: null, page: 5, page_title: 'Nightly backups', brief: null, note: '', created_by: 'editor', created_at: '' }),
      'POST /api/v2/research/fact-checks/': () => ({ fact_check: { ...check, status: 'pending', findings: [] }, run: run(10) }),
    });
    const { go } = renderUi(<PageResearch pageId={5} pageTitle="Nightly backups" />, { api });
    const findings = await screen.findByLabelText('Findings');
    expect(within(findings).getByText('contradicted')).toBeInTheDocument();
    expect(within(findings).getByText('Suggested: Back up nightly.')).toBeInTheDocument();
    await userEvent.click(within(findings).getByRole('button', { name: 'Review 1 suggested correction' }));
    expect(go).toHaveBeenCalledWith({ to: 'review', runId: 9 });
    await userEvent.click(screen.getByLabelText('Cite a source', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Backups explained' }));
    await userEvent.click(screen.getByRole('button', { name: 'Cite' }));
    await waitFor(() => expect(posts(calls).at(-1)?.body).toEqual({ source: 's1', page: 5 }));
    await userEvent.click(screen.getByRole('button', { name: 'Fact-check' }));
    await waitFor(() => expect(posts(calls).at(-1)?.body).toEqual({ page_id: 5, collection: null }));
    expect(screen.getByLabelText('Capture an idea')).toBeInTheDocument();
  });
});
