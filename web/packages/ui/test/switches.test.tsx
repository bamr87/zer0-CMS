// Content switches (the Sites area's /sites/switches): someone who may not
// manage sites sees why and the platform is never asked; without a credential
// the hub's map is read-only and says what the platform needs; with one, a
// switch — or every switch of an outlet — opens a modal that shows the
// preview, will not apply without a reason, applies with the preview's digest,
// `confirm: true` and an Idempotency-Key, and follows the job; a preview gone
// stale is said and can be read again; the credential only ever goes in.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { ContentSwitches } from '../src';
import { fakePlatform, nth, Reply, renderUi } from '../../../test/harness';

const me = (permissions: string[]) => ({ authenticated: true, user: { id: 1, username: 'ed', name: 'Ed', email: '', is_staff: false, is_superuser: false }, permissions, csrf_token: 'x' });

const row = (overrides: Record<string, unknown> = {}) => ({
  loop: 'lifehacker.dev/weekly-epic',
  workflow: '.github/workflows/weekly-epic.yml',
  variable: 'WEEKLY_EPIC_ENABLED',
  gate: 'repo_variable',
  semantics: 'opt_in',
  default: 'off',
  in_map: true,
  live: 'true',
  live_state: 'set',
  effective: 'on',
  why: "WEEKLY_EPIC_ENABLED is 'true' (opt-in)",
  map_state: 'on',
  verified: true,
  reason: 'maintainer instruction',
  set_by: 'bamr87',
  set_at: '2026-11-24',
  drift: false,
  hold: null,
  flippable: true,
  merge_authority: false,
  ...overrides,
});

const HUB = { repo: 'bamr87/bamr87', path: '_data/fleet.yml', ref: 'main', read_from: 'github', read: true, error: '' };
const NEEDS = 'a fine-grained personal access token whose repository permission “Variables” (the Actions variables) is read and write, on bamr87/lifehacker.dev';

const board = (credential: boolean) => ({
  hub: HUB,
  credential: { set: credential, error: '', needs: NEEDS },
  outlets: [
    {
      repo: 'bamr87/lifehacker.dev',
      readable: credential,
      error: credential ? '' : 'no credential: the variables are not read',
      switches: [
        row(credential ? {} : { live: null, live_state: 'unreadable', effective: 'unknown' }),
        row({
          loop: 'lifehacker.dev/auto-merge',
          workflow: '.github/workflows/auto-merge.yml',
          variable: 'AUTO_MERGE_ENABLED',
          live: 'false',
          effective: 'off',
          map_state: 'off',
          merge_authority: true,
          hold: { kind: 'env', name: 'HUB_ORIGINATION_HOLD', value: 'true', lift: 'a new amendment' },
        }),
        row({ loop: null, workflow: null, variable: 'BRAND_SWEEP_ENABLED', semantics: null, default: null, in_map: false, live: 'false', effective: 'off', map_state: null }),
        row({ loop: 'lifehacker.dev/nightly', workflow: '.github/workflows/nightly.yml', variable: null, gate: 'none', semantics: null, live: null, live_state: 'none', flippable: false }),
      ],
    },
  ],
});

const PREVIEW = {
  repo: 'bamr87/lifehacker.dev',
  scope: 'switch',
  switch: 'WEEKLY_EPIC_ENABLED',
  target: 'off',
  reason: '',
  changes: [
    { name: 'WEEKLY_EPIC_ENABLED', loops: ['lifehacker.dev/weekly-epic'], in_map: true, current: 'true', current_state: 'set', new: 'false', action: 'update', why: 'then record it in the hub map', hold: null },
  ],
  writes: 1,
  digest: 'd'.repeat(64),
  credential: { set: true, error: '', needs: NEEDS },
  hub: HUB,
};

const JOB = {
  id: 'b0b0b0b0-0000-4000-8000-000000000009',
  kind: 'switches',
  status: 'succeeded',
  is_final: true,
  site: null,
  params: {},
  created_by: 'ed',
  created_at: '2026-11-25T10:00:00Z',
  started_at: '2026-11-25T10:00:01Z',
  finished_at: '2026-11-25T10:00:02Z',
  cancel_requested: false,
  result: {},
  error: '',
  artifacts: [],
};

const CONFIG = { outlets: ['bamr87/lifehacker.dev'], has_credential: true, updated_at: '2026-11-25T09:00:00Z' };

describe('<ContentSwitches>', () => {
  it('tells someone who may not manage sites why, and never asks the platform for the switches', async () => {
    const { api, calls } = fakePlatform({ 'GET /api/v2/me': () => me([]) });
    renderUi(<ContentSwitches />, { api });
    expect(await screen.findByText('For people who manage sites')).toBeInTheDocument();
    expect(calls.some((c) => c.path.startsWith('/api/v2/switches/'))).toBe(false);
  });

  it('shows the hub map read-only without a credential, and says what the platform needs', async () => {
    const { api } = fakePlatform({
      'GET /api/v2/me': () => me(['sites.manage_site']),
      'GET /api/v2/switches/': () => board(false),
      'GET /api/v2/switches/config/': () => ({ ...CONFIG, has_credential: false }),
    });
    renderUi(<ContentSwitches />, { api });
    const notice = await screen.findByText('Read-only: no GitHub credential');
    expect(notice.closest('[role="alert"]') ?? notice.parentElement).toHaveTextContent('“Variables”');
    const table = screen.getByRole('table', { name: 'Switches of bamr87/lifehacker.dev' });
    const epic = within(table).getByText('WEEKLY_EPIC_ENABLED').closest('tr') as HTMLElement;
    expect(within(epic).getByText('unreadable')).toBeInTheDocument();
    expect(within(epic).getByText('unknown')).toBeInTheDocument();
    expect(within(epic).getByRole('switch')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'All on' })).toBeDisabled();
    expect(within(table).getByText('not in the hub map', { selector: '.mantine-Badge-label' })).toBeInTheDocument();
    expect(within(table).getByText('held: HUB_ORIGINATION_HOLD')).toBeInTheDocument();
    expect(within(table).getByText('no switch (none)')).toBeInTheDocument();
    expect(await screen.findByText('GitHub credential: not set')).toBeInTheDocument();
  });

  it('flips one switch through a preview, a reason and a confirmation, and follows the job', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(['sites.manage_site']),
      'GET /api/v2/switches/': () => board(true),
      'GET /api/v2/switches/config/': () => CONFIG,
      'POST /api/v2/switches/preview/': () => PREVIEW,
      'POST /api/v2/switches/apply/': () => new Reply(202, { job: JOB }),
      [`GET /api/v2/jobs/${JOB.id}/`]: () => ({ ...JOB, lines: [{ idx: 0, at: '2026-11-25T10:00:01Z', level: 'info', text: 'WEEKLY_EPIC_ENABLED: true → false (updated, read back)' }] }),
    });
    renderUi(<ContentSwitches />, { api });
    const merge = await screen.findByRole('switch', { name: 'AUTO_MERGE_ENABLED on bamr87/lifehacker.dev' });
    expect(merge).toBeDisabled(); // what merges without a person is not switched on from here
    await userEvent.click(screen.getByRole('switch', { name: 'WEEKLY_EPIC_ENABLED on bamr87/lifehacker.dev' }));
    const dialog = await screen.findByRole('dialog', { name: 'Switch off WEEKLY_EPIC_ENABLED on bamr87/lifehacker.dev?' });
    const plan = await within(dialog).findByRole('table', { name: 'What the flip would write' });
    expect(within(plan).getByText('set: then record it in the hub map')).toBeInTheDocument();
    expect(nth(calls.filter((c) => c.path === '/api/v2/switches/preview/')).body).toEqual({
      repo: 'bamr87/lifehacker.dev',
      switch: 'WEEKLY_EPIC_ENABLED',
      target: 'off',
      reason: '',
    });
    const applyButton = within(dialog).getByRole('button', { name: 'Apply: switch off' });
    expect(applyButton).toBeDisabled();
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Reason/ }), 'Pausing the epic for a week');
    await userEvent.click(applyButton);
    expect(await within(dialog).findByText('WEEKLY_EPIC_ENABLED: true → false (updated, read back)')).toBeInTheDocument();
    const applied = nth(calls.filter((c) => c.path === '/api/v2/switches/apply/'));
    expect(applied.body).toEqual({
      repo: 'bamr87/lifehacker.dev',
      switch: 'WEEKLY_EPIC_ENABLED',
      target: 'off',
      reason: 'Pausing the epic for a week',
      digest: 'd'.repeat(64),
      confirm: true,
    });
    expect(applied.idempotencyKey).toMatch(/.{16,}/);
  });

  it('switches every switch of an outlet with one preview, and a stale preview is said and read again', async () => {
    let stale = true;
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(['sites.manage_site']),
      'GET /api/v2/switches/': () => board(true),
      'GET /api/v2/switches/config/': () => CONFIG,
      'POST /api/v2/switches/preview/': () => ({ ...PREVIEW, scope: 'outlet', switch: null, target: 'on' }),
      'POST /api/v2/switches/apply/': () =>
        stale
          ? new Reply(409, { error: { code: 'switches.changed', message: 'the switches changed since the preview: preview the flip again', status: 409, details: [] } })
          : new Reply(202, { job: JOB }),
      [`GET /api/v2/jobs/${JOB.id}/`]: () => ({ ...JOB, lines: [] }),
    });
    renderUi(<ContentSwitches />, { api });
    await userEvent.click(await screen.findByRole('button', { name: 'All on' }));
    const dialog = await screen.findByRole('dialog', { name: 'Switch on every switch of bamr87/lifehacker.dev?' });
    await within(dialog).findByRole('table', { name: 'What the flip would write' });
    expect(nth(calls.filter((c) => c.path === '/api/v2/switches/preview/')).body).toMatchObject({ switch: null, target: 'on' });
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Reason/ }), 'switch them all on');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply: switch on' }));
    expect(await within(dialog).findByText('The switches changed since this preview')).toBeInTheDocument();
    stale = false;
    await userEvent.click(within(dialog).getByRole('button', { name: 'Preview again' }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/v2/switches/preview/')).toHaveLength(2));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply: switch on' }));
    expect(await within(dialog).findByText('The flip')).toBeInTheDocument();
  });

  it('sends the credential only when one is typed, and shows only whether one is set', async () => {
    const { api, calls } = fakePlatform({
      'GET /api/v2/me': () => me(['sites.manage_site']),
      'GET /api/v2/switches/': () => board(false),
      'GET /api/v2/switches/config/': () => ({ ...CONFIG, has_credential: false }),
      'PATCH /api/v2/switches/config/': () => CONFIG,
    });
    renderUi(<ContentSwitches />, { api });
    const settings = await screen.findByRole('region', { name: 'Outlets and credential' });
    expect(within(settings).getByRole('button', { name: 'Save' })).toBeDisabled();
    await userEvent.type(within(settings).getByLabelText('Credential'), 'not-a-real-token');
    await userEvent.click(within(settings).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.some((c) => c.method === 'PATCH')).toBe(true));
    expect(nth(calls.filter((c) => c.method === 'PATCH')).body).toEqual({ credential: 'not-a-real-token' });
    await waitFor(() => expect(within(settings).getByLabelText('Credential')).toHaveValue(''));
  });
});
