// The Outbox workspace: the belt's numbers, its messages filtered by kind, station and trace, a message with its
// CloudEvents form and its piece's journey, the dead letters; sending an idea and answering a message with an
// approval as the editor station; running the relay now and following it until nothing waits; a trial started from
// a task card and followed to its result and ledger; a claim check started from claims and a timeline, its
// verdicts, its resolution against the truth, and calibration. A person without the desk's permissions sees the
// actions disabled. A fake platform stands behind the real client.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ClaimCheckView, OutboxDesk, TrialView } from '../src';
import { Belt } from '../src/outbox/Belt';
import { ClaimDesk, EXAMPLE_CLAIMS, EXAMPLE_TIMELINE } from '../src/outbox/ClaimDesk';
import { EXAMPLE_CARD, Trials } from '../src/outbox/Trials';
import { watchLine } from '../src/outbox/TrialView';
import { fakePlatform, renderUi, Reply, type Call } from '../../../test/harness';

const ALL = ['send_handoff', 'deliver_belt', 'view_belt', 'add_trial', 'view_trial', 'add_claimcheck', 'change_claimcheck', 'view_claimcheck'];
const me = (permissions: string[] = ALL) => ({
  authenticated: true,
  user: { id: 1, username: 'ed', name: 'Ed', email: '', is_staff: false, is_superuser: false },
  permissions: permissions.map((p) => `outboxdesk.${p}`),
  csrf_token: 'x',
});
const page = <T,>(results: T[]) => ({ count: results.length, next: null, previous: null, results });
const posts = (calls: Call[], path: string) => calls.filter((c) => c.method === 'POST' && c.path === path);
const TRACE = 'a'.repeat(32);
const STATIONS = ['drafter', 'editor', 'learner', 'planner', 'publisher', 'scout-a', 'verifier'];

const summary = (rest: Record<string, unknown> = {}) => ({
  delivered: 3,
  dead_letters: 1,
  traces: 1,
  kinds: [
    { kind: 'idea', count: 1 },
    { kind: 'verdict', count: 1 },
  ],
  seq_gapless: true,
  ids_unique: true,
  pending: 0,
  stations: STATIONS,
  editor: 'editor',
  harness: '0.1.0',
  ...rest,
});
const handoff = (rest: Record<string, unknown> = {}) => ({
  seq: 1,
  id: 'm1',
  kind: 'idea',
  from: 'scout-a',
  to: ['planner', 'ledger'],
  subject: 'hydra-guide',
  trace: TRACE,
  parent_id: null,
  created_at: '2026-10-27T09:00:00Z',
  payload: { title: 'Hydra' },
  ref: null,
  ...rest,
});
const verdict = handoff({ seq: 3, id: 'm3', kind: 'verdict', from: 'verifier', to: ['editor', 'ledger'], parent_id: 'm2', payload: { verdict: 'pass' } });

describe('<Belt>', () => {
  it('shows the numbers, filters the messages and opens one with its journey and CloudEvent', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/outbox/belt/': () => summary(),
      'GET /api/v2/outbox/belt/messages/': () => page([verdict, handoff()]),
      'GET /api/v2/outbox/belt/dead-letters/': () => [{ id: 'x', station: 'planner', path: '20261027_idea_x.json', errors: ['missing:subject'] }],
      'GET /api/v2/outbox/belt/messages/m3/': () => ({
        ...verdict,
        cloudevent: { specversion: '1.0', id: 'm3', source: 'outbox://belt/verifier', type: 'dev.bamr87.outbox.verdict', subject: 'hydra-guide', time: verdict.created_at, datacontenttype: 'application/json', traceparent: `00-${TRACE}-m3-01`, data: {} },
      }),
      [`GET /api/v2/outbox/belt/traces/${TRACE}/`]: () => ({ trace: TRACE, messages: [handoff(), handoff({ seq: 2, id: 'm2', kind: 'draft', from: 'drafter' }), verdict] }),
    });
    renderUi(<Belt />, { api });
    expect(await screen.findByLabelText('Delivered')).toHaveTextContent('3');
    expect(screen.getByLabelText('Dead letters')).toHaveTextContent('1');
    expect(screen.getByText('sequence gapless')).toBeInTheDocument();
    expect(await screen.findByText('missing:subject')).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText('Kind', { selector: 'input' }));
    await userEvent.click(await screen.findByRole('option', { name: 'verdict' }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/v2/outbox/belt/messages/').at(-1)?.query.get('kind')).toBe('verdict'));
    await userEvent.click(screen.getAllByRole('button', { name: `Follow trace ${TRACE}` })[0] as HTMLElement);
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/v2/outbox/belt/messages/').at(-1)?.query.get('trace')).toBe(TRACE));

    await userEvent.click(screen.getByRole('button', { name: 'Open verdict 3' }));
    const journey = await screen.findByRole('table', { name: 'Journey' });
    expect(within(journey).getAllByRole('row')).toHaveLength(3);
    expect(screen.getByLabelText('CloudEvent')).toHaveTextContent('dev.bamr87.outbox.verdict');
  });

  it('runs the relay now and follows the summary until nothing waits', async () => {
    let pending = 2;
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/outbox/belt/': () => summary({ pending, delivered: 3 - pending }),
      'GET /api/v2/outbox/belt/messages/': () => page([]),
      'GET /api/v2/outbox/belt/dead-letters/': () => [],
      'POST /api/v2/outbox/belt/deliver/': () => {
        const was = pending;
        pending = 0;
        return { pending: was };
      },
    });
    renderUi(<Belt />, { api });
    expect(await screen.findByLabelText('Waiting')).toHaveTextContent('2');
    await userEvent.click(await screen.findByRole('button', { name: 'Deliver now' }));
    await waitFor(() => expect(screen.getByLabelText('Waiting')).toHaveTextContent('0'));
    expect(screen.getByLabelText('Delivered')).toHaveTextContent('3');
    expect(posts(calls, '/api/v2/outbox/belt/deliver/')).toHaveLength(1);
  });

  it('sends an idea as the editor, and answers a delivered verdict with an approval on its trace', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/outbox/belt/': () => summary(),
      'GET /api/v2/outbox/belt/messages/': () => page([verdict]),
      'GET /api/v2/outbox/belt/dead-letters/': () => [],
      'GET /api/v2/content/pages/': () => page([]),
      'GET /api/v2/outbox/belt/messages/m3/': () => ({ ...verdict, cloudevent: { specversion: '1.0', id: 'm3', source: '', type: '', subject: '', time: '', datacontenttype: '', traceparent: '', data: {} } }),
      [`GET /api/v2/outbox/belt/traces/${TRACE}/`]: () => ({ trace: TRACE, messages: [verdict] }),
      'POST /api/v2/outbox/belt/send/': ({ body }) => handoff({ ...(body as object), seq: null, id: 'new', from: 'editor' }),
    });
    renderUi(<Belt />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'Send a handoff' }));
    let form = await screen.findByRole('form', { name: 'Send a handoff' });
    await userEvent.type(within(form).getByLabelText('Subject'), 'backups-guide');
    const payload = within(form).getByLabelText('Payload');
    await userEvent.clear(payload);
    await userEvent.type(payload, '{{"title": "Backups"}');
    await userEvent.click(within(form).getByRole('button', { name: 'Send' }));
    await waitFor(() =>
      expect(posts(calls, '/api/v2/outbox/belt/send/').at(-1)?.body).toEqual({
        kind: 'idea',
        to: ['planner', 'ledger'],
        subject: 'backups-guide',
        payload: { title: 'Backups' },
        parent_id: '',
        trace: '',
        page: null,
      }),
    );
    await waitFor(() => expect(screen.queryByRole('form', { name: 'Send a handoff' })).toBeNull());

    await userEvent.click(screen.getByRole('button', { name: 'Open verdict 3' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Answer it' }));
    form = await screen.findByRole('form', { name: 'Send a handoff' });
    expect(within(form).getByLabelText('Subject')).toHaveValue('hydra-guide');
    await userEvent.click(within(form).getByRole('button', { name: 'Send' }));
    await waitFor(() =>
      expect(posts(calls, '/api/v2/outbox/belt/send/').at(-1)?.body).toMatchObject({ kind: 'approval', to: ['publisher', 'ledger'], parent_id: 'm3', subject: 'hydra-guide' }),
    );
  });

  it('shows the platform’s refusal, and disables what the person may not do', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/me': () => me(['view_belt']),
      'GET /api/v2/outbox/belt/': () => summary(),
      'GET /api/v2/outbox/belt/messages/': () => page([]),
      'GET /api/v2/outbox/belt/dead-letters/': () => [],
    });
    renderUi(<Belt />, { api });
    expect(await screen.findByText(/No message on the ledger yet/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Deliver now' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Send a handoff' })).toBeDisabled();
  });

  it('says so when the platform cannot load the harness', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/outbox/belt/': () =>
        new Reply(503, { error: { code: 'outbox.unavailable', message: 'the outbox harness cannot load belt', status: 503, details: [] } }),
    });
    renderUi(<Belt />, { api });
    expect(await screen.findByText('the outbox harness cannot load belt')).toBeInTheDocument();
  });
});

describe('<OutboxDesk>', () => {
  it('asks the host to go to a tab', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/outbox/belt/': () => summary(),
      'GET /api/v2/outbox/belt/messages/': () => page([]),
      'GET /api/v2/outbox/belt/dead-letters/': () => [],
    });
    const { go } = renderUi(<OutboxDesk />, { api });
    await userEvent.click(await screen.findByRole('tab', { name: 'Claim desk' }));
    expect(go).toHaveBeenCalledWith({ to: 'outbox', tab: 'claims' });
  });
});

const trial = (rest: Record<string, unknown> = {}) => ({
  id: 't1',
  task: EXAMPLE_CARD,
  lag_b: null,
  status: 'succeeded',
  error: '',
  result: {
    task_id: 'T-stale-fact',
    family: 'stale_fact',
    latest_env_seq: 2,
    n_active_claims: 2,
    winner: { from: 'claimant-a', id: 'c', confidence: 0.86, env_seq: 2, answer: 'green', tick: 4 },
    first_claim_from: 'claimant-a',
    resolved: true,
    correct: true,
    confidence_inversion: false,
    retracts: 1,
    claims_per_agent: { 'claimant-a': 2, 'claimant-b': 1 },
    expected_answer: 'green',
  },
  run_dir: 'runs/trial-t1',
  requested_by: 'ed',
  created_at: '2026-10-27T09:00:00Z',
  started_at: '2026-10-27T09:00:01Z',
  finished_at: '2026-10-27T09:00:02Z',
  ...rest,
});

describe('<Trials> and <TrialView>', () => {
  it('runs a task card once, with its key and a lag, and opens the trial', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/outbox/trials/': () => page([trial()]),
      'POST /api/v2/outbox/trials/': () => trial({ id: 't2', status: 'queued', result: null }),
    });
    const { go } = renderUi(<Trials />, { api });
    expect(await screen.findByText('claimant-a: green')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Claimant B's lag/), '6');
    await userEvent.click(screen.getByRole('button', { name: 'Run trial' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'trial', id: 't2' }));
    const [started] = posts(calls, '/api/v2/outbox/trials/');
    expect(started?.body).toEqual({ task: EXAMPLE_CARD, lag_b: 6 });
    expect(started?.idempotencyKey).toBeTruthy();

    const card = screen.getByLabelText('Task card');
    await userEvent.clear(card);
    await userEvent.type(card, '{{ not json');
    expect(screen.getByRole('button', { name: 'Run trial' })).toBeDisabled();
  });

  it('follows a trial until the worker has run it, then shows its result and the arena’s ledger', async () => {
    let reads = 0;
    const ledger = [
      { event: 'deliver', type: 'task_open', id: 'o', from: 'arena', created_at_tick: 0, env_seq: 0, payload: { question: 'What is it?' } },
      { event: 'tick', tick: 0, task_id: 'T' },
      { event: 'deliver', type: 'claim', id: 'c', from: 'claimant-a', created_at_tick: 4, env_seq: 2, confidence: 0.86, payload: { answer: 'green' } },
    ];
    const { api } = fakePlatform({
      'GET /api/v2/outbox/trials/t1/': () => (++reads === 1 ? { ...trial({ status: 'running', result: null }), ledger: [] } : { ...trial(), ledger }),
    });
    renderUi(<TrialView trialId="t1" />, { api });
    expect(await screen.findByText('The worker is running the arena…')).toBeInTheDocument();
    expect(await screen.findByText(/claimant-a answered green at confidence 0.86/, {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByLabelText('Ledger').textContent?.split('\n')).toEqual([
      't+0  task_open  What is it?',
      't+0  tick',
      't+4  claimant-a claim  conf=0.86  env=2  ans=green',
    ]);
    expect(watchLine({ event: 'tick', tick: 3 })).toBe('t+3  tick');
  });
});

const check = (rest: Record<string, unknown> = {}) => ({
  id: 'k1',
  title: 'Hydra explainer',
  author: 'rhea',
  page: { id: 5, title: 'Hydra' },
  claim_count: 2,
  status: 'succeeded',
  passed: false,
  resolution_status: null,
  requested_by: 'ed',
  created_at: '2026-10-27T09:00:00Z',
  finished_at: '2026-10-27T09:00:02Z',
  resolved_at: null,
  ...rest,
});
const detail = (rest: Record<string, unknown> = {}) => ({
  ...check(),
  claims: EXAMPLE_CLAIMS,
  timeline: EXAMPLE_TIMELINE,
  closes_at_tick: 8,
  lag_b: 2,
  error: '',
  report: {
    pass: false,
    claims: [
      { claim_id: 'hydra-status', question: 'What status does hydra report?', draft_answer: 'amber', verdict: 'block', reason: 'sources_disagree', supported_answer: 'green', winner_from: 'claimant-a', winner_confidence: 0.86, winner_env_seq: 2, latest_env_seq: 2 },
      { claim_id: 'hydra-region', question: 'Which region serves hydra?', draft_answer: 'eu-west', verdict: 'pass', reason: 'sources_agree', supported_answer: 'eu-west', winner_from: 'claimant-a', winner_confidence: 0.79, winner_env_seq: 1, latest_env_seq: 1 },
    ],
  },
  truth: null,
  resolutions: null,
  resolution_error: '',
  run_dir: 'runs/claims-k1',
  ...rest,
});

describe('<ClaimDesk> and <ClaimCheckView>', () => {
  it('checks claims against a timeline, lists checks with their verdicts, and shows calibration', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/content/pages/': () => page([]),
      'GET /api/v2/outbox/claim-checks/': () => page([check()]),
      'GET /api/v2/outbox/claim-checks/calibration/': () => ({
        resolved: 2,
        winner_accuracy: 1,
        verifiers: [
          { name: 'claimant-a', n: 2, brier: 0.0319 },
          { name: 'claimant-b', n: 2, brier: 0.1305 },
        ],
        authors: [{ name: 'rhea', n: 2, brier: 0.325 }],
      }),
      'POST /api/v2/outbox/claim-checks/': () => check({ id: 'k2', status: 'queued', passed: null }),
    });
    const { go } = renderUi(<ClaimDesk />, { api });
    expect(await screen.findByRole('button', { name: 'Hydra explainer' })).toBeInTheDocument();
    expect(screen.getByText('block')).toBeInTheDocument();
    const authors = await screen.findByRole('table', { name: 'Authors' });
    expect(within(authors).getByText('0.3250')).toBeInTheDocument();

    const form = screen.getByRole('form', { name: 'Check claims' });
    await userEvent.type(within(form).getByLabelText('Title'), 'Hydra v2');
    await userEvent.type(within(form).getByLabelText(/^Author/), 'rhea');
    await userEvent.click(within(form).getByRole('button', { name: 'Check claims' }));
    await waitFor(() => expect(go).toHaveBeenCalledWith({ to: 'claim-check', id: 'k2' }));
    expect(posts(calls, '/api/v2/outbox/claim-checks/')[0]?.body).toEqual({
      title: 'Hydra v2',
      author: 'rhea',
      page: null,
      claims: EXAMPLE_CLAIMS,
      timeline: EXAMPLE_TIMELINE,
      closes_at_tick: 8,
      lag_b: 2,
    });
    const claims = within(form).getByLabelText('Claims');
    await userEvent.clear(claims);
    await userEvent.type(claims, '{{}');
    expect(within(form).getByText('A JSON list')).toBeInTheDocument();
    expect(within(form).getByRole('button', { name: 'Check claims' })).toBeDisabled();
  });

  it('shows a verdict per claim, opens the draft, and resolves against the truth', async () => {
    let resolved = false;
    const resolutions = [
      { claim_id: 'hydra-status', task_id: 'C-hydra-status', truth: 'green', winner_correct: true, confidence_inversion: false, draft_correct: false, brier: { 'claimant-a': 0.0196, 'claimant-b': 0.1089 }, draft_brier: 0.64 },
      { claim_id: 'hydra-region', task_id: 'C-hydra-region', truth: 'eu-west', winner_correct: true, confidence_inversion: false, draft_correct: true, brier: { 'claimant-a': 0.0441 }, draft_brier: 0.01 },
    ];
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(),
      'GET /api/v2/outbox/claim-checks/k1/': () =>
        resolved ? detail({ resolution_status: 'succeeded', truth: { 'hydra-status': 'green', 'hydra-region': 'eu-west' }, resolutions }) : detail(),
      'POST /api/v2/outbox/claim-checks/k1/resolve/': () => {
        resolved = true;
        return detail({ resolution_status: 'queued', truth: { 'hydra-status': 'green', 'hydra-region': 'eu-west' } });
      },
    });
    const { go } = renderUi(<ClaimCheckView checkId="k1" />, { api });
    const verdicts = await screen.findByRole('table', { name: 'Verdicts' });
    expect(within(verdicts).getByText('sources disagree')).toBeInTheDocument();
    expect(within(verdicts).getByText('green')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Open the draft: Hydra' }));
    expect(go).toHaveBeenCalledWith({ to: 'page', id: 5 });

    expect(screen.getByRole('button', { name: 'Resolve' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Truth for hydra-status'), 'green');
    await userEvent.type(screen.getByLabelText('Truth for hydra-region'), 'eu-west');
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));
    await waitFor(() => expect(posts(calls, '/api/v2/outbox/claim-checks/k1/resolve/')[0]?.body).toEqual({ truth: { 'hydra-status': 'green', 'hydra-region': 'eu-west' } }));
    expect(posts(calls, '/api/v2/outbox/claim-checks/k1/resolve/')[0]?.idempotencyKey).toBeTruthy();
    expect(await screen.findByText('draft wrong', {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByText(/Brier claimant-a 0.0196, claimant-b 0.1089 · draft 0.64/)).toBeInTheDocument();
  });
});
