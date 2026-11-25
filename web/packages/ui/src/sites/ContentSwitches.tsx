// Content switches (the Sites area's /sites/switches): each content outlet's
// GitHub Actions loops, gated by repository variables, read against the hub's
// switch map (bamr87/bamr87 _data/fleet.yml), which is their record — the
// variables are its projections. A row says what the variable is set to, what
// that means for the loop (opt-in: on only at exactly `true`; opt-out: on
// unless exactly `false`), what the map records, whether the two disagree
// (drift: record it in the hub) and whether a code-level hold idles the loop
// whatever the variable says. People who manage sites (`sites.manage_site`)
// see it; with the platform's credential set they flip one switch, or all of
// an outlet's, through a modal that shows the preview (what each variable is
// and will be) and takes a reason before anything is written — the write is a
// job, followed here, and the flip is recorded as an event. Without a
// credential the map is shown read-only, with what the platform needs. The
// credential only ever goes in: the platform says "set" or "not set".
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Code,
  Group,
  Loader,
  Modal,
  PasswordInput,
  Stack,
  Switch,
  Table,
  TagsInput,
  Text,
  Textarea,
  Title,
  Tooltip,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { SwitchOutlet, SwitchPreview, SwitchRow } from '@zer0/api';
import { useState } from 'react';

import { fieldError, newKey, once, oneClick, useMe } from '../ai/shared';
import { ApiError, call, errorText } from '../call';
import { useApi } from '../context';
import { JobLog } from './JobLog';

/** What a person asked to flip: one switch of an outlet, or every switch of it (`variable` null). */
export interface Flip {
  repo: string;
  variable: string | null;
  target: 'on' | 'off';
}

const BOARD = ['switches', 'board'] as const;
const EFFECT_COLOR = { on: 'teal', off: 'gray', unknown: 'yellow' } as const;
const ACTION_TEXT: Record<string, string> = {
  update: 'set',
  create: 'created',
  none: 'no change',
  refused: 'refused',
  unreadable: 'cannot be read',
};

/** Whether the person may see and flip the switches (`sites.manage_site`, from /api/v2/me). */
export function useManagesSites(): boolean | undefined {
  const me = useMe();
  return me.data ? me.data.permissions.includes('sites.manage_site') : undefined;
}

export function ContentSwitches() {
  const api = useApi();
  const manages = useManagesSites();
  const [flip, setFlip] = useState<Flip | null>(null);
  const board = useQuery({
    queryKey: BOARD,
    queryFn: () => call(api.GET('/api/v2/switches/')),
    enabled: manages === true,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  if (manages === undefined) return <Loader aria-label="Loading" />;
  if (!manages)
    return (
      <Alert color="gray" title="For people who manage sites">
        The content outlets’ switches are read with the platform’s GitHub credential, so they are shown to people who manage sites
        (the sites.manage_site permission).
      </Alert>
    );
  if (board.isPending) return <Loader aria-label="Reading the switches" />;
  if (board.isError) return <Alert color="red">{errorText(board.error)}</Alert>;
  const { hub, credential, outlets } = board.data;
  const canFlip = credential.set && !credential.error;
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Each outlet’s content loops run on GitHub Actions, each gated by a repository variable. The hub’s switch map is their record and
        the variables its projections: a flip here writes the variable, and the hub’s console is where the map records it.
      </Text>
      <Group gap="xs">
        <Text size="sm">
          Hub map: <Code>{`${hub.repo}/${hub.path}@${hub.ref}`}</Code> {hub.read_from === 'checkout' ? '(local checkout)' : ''}
        </Text>
        <Badge color={hub.read ? 'teal' : 'red'} variant="light">
          {hub.read ? 'read' : 'not read'}
        </Badge>
      </Group>
      {hub.error ? <Alert color="red">{hub.error}</Alert> : null}
      {!credential.set || credential.error ? (
        <Alert color="yellow" title="Read-only: no GitHub credential">
          {credential.error ? `${credential.error}. ` : ''}The map is shown as the hub records it. To read and flip the switches, the platform
          needs {credential.needs}.
        </Alert>
      ) : null}
      {outlets.map((outlet) => (
        <OutletCard key={outlet.repo} outlet={outlet} canFlip={canFlip} onFlip={setFlip} />
      ))}
      <SwitchSettings />
      <FlipModal flip={flip} onClose={() => setFlip(null)} />
    </Stack>
  );
}

function OutletCard({ outlet, canFlip, onFlip }: { outlet: SwitchOutlet; canFlip: boolean; onFlip: (flip: Flip) => void }) {
  const flippable = outlet.switches.filter((row) => row.flippable);
  const live = canFlip && outlet.readable && flippable.length > 0;
  return (
    <Card withBorder component="section" aria-label={outlet.repo}>
      <Stack gap="xs">
        <Group justify="space-between">
          <Title order={4}>
            <Anchor href={`https://github.com/${outlet.repo}/actions`} target="_blank" rel="noreferrer">
              {outlet.repo}
            </Anchor>
          </Title>
          <Group gap="xs">
            <Button size="xs" variant="light" disabled={!live} onClick={() => onFlip({ repo: outlet.repo, variable: null, target: 'on' })}>
              All on
            </Button>
            <Button size="xs" variant="light" color="gray" disabled={!live} onClick={() => onFlip({ repo: outlet.repo, variable: null, target: 'off' })}>
              All off
            </Button>
          </Group>
        </Group>
        {outlet.error ? (
          <Text size="sm" c={canFlip ? 'red' : 'dimmed'}>
            {outlet.error}
          </Text>
        ) : null}
        {outlet.switches.length === 0 ? (
          <Text size="sm" c="dimmed">
            The hub map has no loop of this repository, and it has no *_ENABLED variable{outlet.readable ? '' : ' that could be read'}.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={980}>
            <Table verticalSpacing={6} aria-label={`Switches of ${outlet.repo}`}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Workflow</Table.Th>
                  <Table.Th>Variable</Table.Th>
                  <Table.Th>Semantics</Table.Th>
                  <Table.Th>Live</Table.Th>
                  <Table.Th>Effective</Table.Th>
                  <Table.Th>Map</Table.Th>
                  <Table.Th>Drift</Table.Th>
                  <Table.Th>Hold</Table.Th>
                  <Table.Th>Switch</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {outlet.switches.map((row) => (
                  <SwitchRow key={`${row.loop ?? ''}:${row.variable ?? ''}`} repo={outlet.repo} row={row} live={canFlip && outlet.readable} onFlip={onFlip} />
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Stack>
    </Card>
  );
}

function SwitchRow({ repo, row, live, onFlip }: { repo: string; row: SwitchRow; live: boolean; onFlip: (flip: Flip) => void }) {
  const variable = row.variable;
  const workflow = row.workflow ? row.workflow.replace('.github/workflows/', '') : null;
  // A switch that decides what merges without a person is a brake here: it may be switched off, never on.
  const brakeOnly = row.merge_authority && row.effective !== 'on';
  return (
    <Table.Tr>
      <Table.Td>
        <Text size="sm">{workflow ?? '—'}</Text>
        <Text size="xs" c="dimmed">
          {row.loop ?? 'not in the hub map'}
        </Text>
      </Table.Td>
      <Table.Td>{variable ? <Code>{variable}</Code> : <Text size="sm" c="dimmed">no switch ({row.gate})</Text>}</Table.Td>
      <Table.Td>
        <Text size="sm">{row.semantics ? row.semantics.replace('_', '-') : variable ? 'unknown' : '—'}</Text>
      </Table.Td>
      <Table.Td>
        {row.live_state === 'set' ? <Code>{row.live}</Code> : <Text size="sm" c="dimmed">{row.live_state === 'none' ? '—' : row.live_state}</Text>}
      </Table.Td>
      <Table.Td>
        <Tooltip label={row.why} multiline w={320} withArrow>
          <Badge color={EFFECT_COLOR[row.effective]} variant="light" tabIndex={0}>
            {row.effective}
          </Badge>
        </Tooltip>
      </Table.Td>
      <Table.Td>
        {row.map_state ? (
          <Tooltip
            label={[row.reason, row.set_by && `set by ${row.set_by}`, row.set_at].filter(Boolean).join(' · ') || 'no reason recorded'}
            multiline
            w={320}
            withArrow
          >
            <Text size="sm" tabIndex={0}>
              {row.map_state}
              {row.verified ? ' ✓' : ''}
            </Text>
          </Tooltip>
        ) : (
          <Text size="sm" c="dimmed">
            —
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        {row.drift ? (
          <Badge color="orange" variant="light">
            drift: record it in the hub map
          </Badge>
        ) : !row.in_map ? (
          <Badge color="gray" variant="outline">
            not in the hub map
          </Badge>
        ) : null}
      </Table.Td>
      <Table.Td>
        {row.hold ? (
          <Tooltip label={row.hold.lift ? `To lift: ${row.hold.lift}` : 'A code-level hold'} multiline w={320} withArrow>
            <Badge color="red" variant="light" tabIndex={0}>
              held: {row.hold.name ?? 'yes'}
            </Badge>
          </Tooltip>
        ) : null}
      </Table.Td>
      <Table.Td>
        {variable && row.flippable ? (
          <Switch
            aria-label={`${variable} on ${repo}`}
            checked={row.effective === 'on'}
            disabled={!live || row.live_state === 'unreadable' || brakeOnly}
            title={brakeOnly ? 'It decides what merges without a person: switch it on in the hub' : undefined}
            onChange={(event) => onFlip({ repo, variable, target: event.currentTarget.checked ? 'on' : 'off' })}
          />
        ) : null}
      </Table.Td>
    </Table.Tr>
  );
}

/** The flip's confirm modal: the preview — each variable as it is and as it will be — then a reason, then apply. */
export function FlipModal({ flip, onClose }: { flip: Flip | null; onClose: () => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const [reason, setReason] = useState('');
  const [key, setKey] = useState(newKey);
  const preview = useQuery({
    queryKey: ['switches', 'preview', flip],
    enabled: flip !== null,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: () =>
      call(
        api.POST('/api/v2/switches/preview/', {
          body: { repo: flip?.repo ?? '', switch: flip?.variable ?? null, target: flip?.target ?? 'off', reason: '' },
        }),
      ),
  });
  const apply = useMutation({
    mutationFn: (plan: SwitchPreview) =>
      call(
        api.POST('/api/v2/switches/apply/', {
          params: { header: once(key) },
          body: { repo: plan.repo, switch: plan.switch, target: plan.target, reason: reason.trim(), digest: plan.digest, confirm: true },
        }),
      ),
  });
  const close = () => {
    if (apply.isSuccess) void qc.invalidateQueries({ queryKey: BOARD });
    setReason('');
    setKey(newKey());
    apply.reset();
    onClose();
  };
  const changed = apply.error instanceof ApiError && apply.error.code === 'switches.changed';
  const scope = flip ? (flip.variable ? `${flip.variable} on ${flip.repo}` : `every switch of ${flip.repo}`) : '';
  const plan = preview.data;
  const blocked = plan?.changes.some((c) => c.action === 'unreadable');
  return (
    <Modal opened={flip !== null} onClose={close} size="xl" title={flip ? `Switch ${flip.target} ${scope}?` : ''}>
      {preview.isPending ? <Loader aria-label="Reading what the flip would write" /> : null}
      {preview.isError ? <Alert color="red">{errorText(preview.error)}</Alert> : null}
      {plan && !apply.data ? (
        <Stack>
          <Table.ScrollContainer minWidth={620}>
            <Table aria-label="What the flip would write" verticalSpacing={6}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Variable</Table.Th>
                  <Table.Th>Now</Table.Th>
                  <Table.Th>Will be</Table.Th>
                  <Table.Th>What happens</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {plan.changes.map((c) => (
                  <Table.Tr key={c.name}>
                    <Table.Td>
                      <Code>{c.name}</Code>
                      <Text size="xs" c="dimmed">
                        {c.loops.join(', ') || 'not in the hub map'}
                      </Text>
                    </Table.Td>
                    <Table.Td>{c.current_state === 'set' ? <Code>{c.current}</Code> : c.current_state}</Table.Td>
                    <Table.Td>{c.action === 'update' || c.action === 'create' ? <Code>{c.new}</Code> : '—'}</Table.Td>
                    <Table.Td>
                      <Text size="sm" c={c.action === 'refused' || c.action === 'unreadable' ? 'red' : undefined}>
                        {ACTION_TEXT[c.action]}: {c.why}
                        {c.hold ? ` · held by ${c.hold.name ?? 'a hold'}, which idles the loop whatever the variable says` : ''}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Text size="sm">
            {plan.writes === 0
              ? 'Nothing to write.'
              : `${plan.writes} variable${plan.writes === 1 ? '' : 's'} will be written on ${plan.repo}. The hub’s switch map is not changed: record the flip there (${plan.hub.repo} ${plan.hub.path}).`}
          </Text>
          {blocked ? <Alert color="yellow">{plan.credential.set ? 'A switch in scope could not be read.' : `No credential: the platform needs ${plan.credential.needs}.`}</Alert> : null}
          <Textarea
            label="Reason"
            description="Recorded with the flip: who, what, the scope, the reason, each old and new value."
            required
            autosize
            minRows={2}
            value={reason}
            onChange={(event) => setReason(event.currentTarget.value)}
            error={fieldError(apply.error, 'reason')}
          />
          {apply.error && !changed ? <Alert color="red">{errorText(apply.error)}</Alert> : null}
          {changed ? (
            <Alert color="orange" title="The switches changed since this preview">
              <Group justify="space-between">
                <Text size="sm">{errorText(apply.error)}</Text>
                <Button size="xs" variant="light" onClick={() => { apply.reset(); void preview.refetch(); }}>
                  Preview again
                </Button>
              </Group>
            </Alert>
          ) : null}
          <Group justify="end">
            <Button variant="default" onClick={close}>
              Cancel
            </Button>
            <Button
              color={flip?.target === 'off' ? 'gray' : undefined}
              disabled={!reason.trim() || plan.writes === 0 || blocked || changed}
              loading={apply.isPending}
              onClick={oneClick(() => apply.mutate(plan))}
            >
              {`Apply: switch ${plan.target}`}
            </Button>
          </Group>
        </Stack>
      ) : null}
      {apply.data ? (
        <Stack>
          <JobLog jobId={apply.data.job.id} title="The flip" />
          <Text size="sm">Once it holds, record the flip in the hub’s switch map: until then each switch shows drift.</Text>
          <Group justify="end">
            <Button onClick={close}>Done</Button>
          </Group>
        </Stack>
      ) : null}
    </Modal>
  );
}

/** The outlets and the platform's GitHub credential, which only ever goes in. */
function SwitchSettings() {
  const api = useApi();
  const qc = useQueryClient();
  const config = useQuery({ queryKey: ['switches', 'config'], queryFn: () => call(api.GET('/api/v2/switches/config/')) });
  const [outlets, setOutlets] = useState<string[] | null>(null);
  const [secret, setSecret] = useState('');
  const [forget, setForget] = useState(false);
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH('/api/v2/switches/config/', {
          body: {
            ...(outlets ? { outlets } : {}),
            // The credential goes only when someone typed one, or asked to remove it.
            ...(secret ? { credential: secret } : forget ? { credential: '' } : {}),
          },
        }),
      ),
    onSuccess: () => {
      setSecret('');
      setForget(false);
      setOutlets(null);
      notifications.show({ message: 'Content switches saved' });
      void qc.invalidateQueries({ queryKey: ['switches'] });
    },
  });
  if (config.isPending) return <Loader size="sm" />;
  if (config.isError) return <Alert color="red">{errorText(config.error)}</Alert>;
  return (
    <Card withBorder component="section" aria-label="Outlets and credential">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <Stack gap="sm">
          <Title order={4}>Outlets and credential</Title>
          <TagsInput
            label="Outlets"
            description="The repositories whose switches are shown, owner/name each."
            value={outlets ?? config.data.outlets ?? []}
            onChange={setOutlets}
            error={fieldError(save.error, 'outlets')}
          />
          <Text size="sm" fw={500}>
            GitHub credential: {config.data.has_credential ? 'set' : 'not set'}
          </Text>
          <PasswordInput
            label={config.data.has_credential ? 'Replace the credential' : 'Credential'}
            description="A fine-grained token with the “Variables” repository permission (read and write) on the outlets. Stored encrypted and never shown again."
            autoComplete="off"
            value={secret}
            onChange={(event) => setSecret(event.currentTarget.value)}
            error={fieldError(save.error, 'credential')}
          />
          {config.data.has_credential ? (
            <Checkbox label="Remove the stored credential" checked={forget} disabled={!!secret} onChange={(event) => setForget(event.currentTarget.checked)} />
          ) : null}
          {save.error ? <Alert color="red">{errorText(save.error)}</Alert> : null}
          <Group justify="end">
            <Button type="submit" loading={save.isPending} disabled={!outlets && !secret && !forget}>
              Save
            </Button>
          </Group>
        </Stack>
      </form>
    </Card>
  );
}
