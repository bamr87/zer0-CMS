// Review: the inbox shows each suggestion's change as a diff, and accept,
// reject-with-a-reason and accept-all-of-a-run each make the one request the
// platform defines for them; DiffView marks words or lines as <ins>/<del>.
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { DiffView, SuggestionInbox } from '../src';
import { fakePlatform, nth, renderUi } from '../../../test/harness';

const suggestion = (id: number, change: Record<string, unknown>, rest: Record<string, unknown> = {}) => ({
  id,
  op: 'meta',
  block_id: '',
  field: 'seo_title',
  payload: {},
  rationale: 'Clearer for search.',
  status: 'pending',
  agent: 'seo',
  run_id: 7,
  created_at: '2026-10-21T09:00:00Z',
  target: { type: 'page', id: 5, title: 'Nightly backups' },
  change: { kind: 'field', label: 'seo_title', before: '', after: '', stale: false, ...change },
  ...rest,
});

const INBOX = {
  count: 2,
  next: null,
  previous: null,
  results: [
    suggestion(1, { before: 'Backups', after: 'Nightly backups, explained' }),
    suggestion(2, { kind: 'block', label: 'replace markdown', before: 'We copy it.', after: 'We copy it twice.' }, { op: 'replace', field: '' }),
  ],
};

describe('DiffView', () => {
  it('marks added and removed words', () => {
    const { container } = renderUi(<DiffView before="We copy the site nightly" after="We copy the site twice a night" />, {
      api: fakePlatform({}).api,
    });
    expect(container.querySelector('del')?.textContent).toBe('nightly');
    expect(container.querySelector('ins')?.textContent).toBe('twice a night');
  });

  it('diffs blocks of text by line, and says when nothing changed', () => {
    const { container } = renderUi(<DiffView before={'one\ntwo\n'} after={'one\nthree\n'} />, { api: fakePlatform({}).api });
    expect(container.querySelector('del')?.textContent).toBe('two\n');
    expect(container.querySelector('ins')?.textContent).toBe('three\n');
    renderUi(<DiffView before="same" after="same" />, { api: fakePlatform({}).api });
    expect(screen.getByText('No change')).toBeInTheDocument();
  });
});

describe('<SuggestionInbox>', () => {
  it('shows each change as a diff, grouped by run', async () => {
    const { api } = fakePlatform({ 'GET /api/v2/review/suggestions/': () => INBOX });
    const { container } = renderUi(<SuggestionInbox />, { api });
    expect(await screen.findByText('Run #7')).toBeInTheDocument();
    expect(screen.getAllByRole('article')).toHaveLength(2);
    expect([...container.querySelectorAll('ins')].map((n) => n.textContent?.trim())).toEqual(['Nightly backups, explained', 'twice']);
    expect(screen.getAllByText('Clearer for search.')).toHaveLength(2);
  });

  it('accepts one, rejects one with a reason, and accepts all of a run', async () => {
    const platform = fakePlatform({
      'GET /api/v2/review/suggestions/': () => INBOX,
      'POST /api/v2/suggestions/1/accept/': () => ({ accepted: true, revision_id: 42 }),
      'POST /api/v2/suggestions/2/reject/': () => ({ rejected: true }),
      'POST /api/v2/review/runs/7/accept/': () => ({ accepted: [1, 2], revision_ids: [43] }),
    });
    renderUi(<SuggestionInbox />, { api: platform.api });
    await userEvent.click(nth(await screen.findAllByRole('button', { name: 'Accept' })));
    await waitFor(() => expect(platform.calls.some((c) => c.path === '/api/v2/suggestions/1/accept/')).toBe(true));

    await userEvent.click(nth(screen.getAllByRole('button', { name: 'Reject…' }), 1));
    await userEvent.type(screen.getByLabelText('Why reject it?'), 'not our voice');
    await userEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() => {
      const rejected = platform.calls.find((c) => c.path === '/api/v2/suggestions/2/reject/');
      expect(rejected?.body).toEqual({ reason: 'not our voice' });
      expect(rejected?.csrf).toBe('test-csrf');
    });

    await userEvent.click(screen.getByRole('button', { name: 'Accept all of run #7' }));
    await waitFor(() => expect(platform.calls.some((c) => c.method === 'POST' && c.path === '/api/v2/review/runs/7/accept/')).toBe(true));
  });

  it('will not accept a stale suggestion, and says when there is nothing to review', async () => {
    const stale = { ...INBOX, count: 1, results: [suggestion(3, { stale: true, before: 'x', after: 'y' })] };
    renderUi(<SuggestionInbox />, { api: fakePlatform({ 'GET /api/v2/review/suggestions/': () => stale }).api });
    expect(await screen.findByText('stale')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled();
    renderUi(<SuggestionInbox />, {
      api: fakePlatform({ 'GET /api/v2/review/suggestions/': () => ({ count: 0, next: null, previous: null, results: [] }) }).api,
    });
    expect(await screen.findByText('Nothing to review.')).toBeInTheDocument();
  });
});
