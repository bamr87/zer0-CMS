// The Sites area's registry: every site a person sees, how each renders, where
// its files live, when it was last synced and what its last doctor run found;
// and, for someone who may manage sites, registering another — one the
// repository's workspace.yml declares, a checkout under SITES_DIR, or a path
// typed in — whose first sync starts at once. Opening a site goes to its view.
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ManagedSite, Site } from '@zer0/api';
import { useState } from 'react';

import { oneClick, useMe } from '../ai/shared';
import { ApiError, call, errorText } from '../call';
import { useApi, useGo } from '../context';

export function rendersWith(managed: ManagedSite): string {
  if (managed.render !== 'jekyll-theme') return 'React renderer';
  return `Jekyll theme ${managed.theme_tag || '(no tag)'} · ${managed.server || 'no server'}`;
}

export const when = (at: string | null | undefined) => (at ? new Date(at).toLocaleString() : 'never');

export function DoctorBadges({ managed }: { managed: ManagedSite }) {
  if (!managed.last_doctor_at) return <Text size="sm" c="dimmed">not checked</Text>;
  return (
    <Group gap={4}>
      <Badge color={managed.errors ? 'red' : 'teal'} variant="light">
        {managed.errors} error{managed.errors === 1 ? '' : 's'}
      </Badge>
      <Badge color={managed.warnings ? 'orange' : 'gray'} variant="light">
        {managed.warnings} warning{managed.warnings === 1 ? '' : 's'}
      </Badge>
    </Group>
  );
}

export function SitesWorkspace() {
  const api = useApi();
  const go = useGo();
  const sites = useQuery({ queryKey: ['sites'], queryFn: () => call(api.GET('/api/v2/sites/')) });
  if (sites.isPending) return <Loader />;
  if (sites.isError) return <Alert color="red">{errorText(sites.error)}</Alert>;
  return (
    <Stack>
      {sites.data.length === 0 ? <Text c="dimmed">No sites yet.</Text> : null}
      {sites.data.length ? (
        <Table highlightOnHover verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Site</Table.Th>
              <Table.Th>Renders with</Table.Th>
              <Table.Th>Files</Table.Th>
              <Table.Th>Last sync</Table.Th>
              <Table.Th>Doctor</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {sites.data.map((site: Site) => (
              <Table.Tr key={site.id}>
                <Table.Td>
                  <Anchor component="button" type="button" fw={600} onClick={() => go({ to: 'site', id: site.id })}>
                    {site.name}
                  </Anchor>
                  <Text size="xs" c="dimmed">
                    {site.hostname}
                  </Text>
                </Table.Td>
                {site.managed ? (
                  <>
                    <Table.Td>{rendersWith(site.managed)}</Table.Td>
                    <Table.Td>
                      <Text size="sm">{site.managed.checkout}</Text>
                      <Text size="xs" c="dimmed">
                        {site.managed.content_source === 'files' ? 'people edit the files' : 'generated from the platform'}
                      </Text>
                    </Table.Td>
                    <Table.Td>{when(site.managed.last_synced_at)}</Table.Td>
                    <Table.Td>
                      <DoctorBadges managed={site.managed} />
                    </Table.Td>
                  </>
                ) : (
                  <Table.Td colSpan={4}>
                    <Text size="sm" c="dimmed">
                      Not managed: register its checkout below.
                    </Text>
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
      <RegisterSite />
    </Stack>
  );
}

/** Register a site from its checkout; hidden from someone who may not, who is never sent to ask the platform for
 * checkouts (`sites.manage_site`, from /api/v2/me) — so their browser logs no refusal. A 403 still hides it. */
export function RegisterSite() {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [checkout, setCheckout] = useState<string | null>(null);
  const [typed, setTyped] = useState('');
  const [key, setKey] = useState('');
  const mayRegister = useMe().data?.permissions.includes('sites.manage_site') ?? false;
  const candidates = useQuery({ queryKey: ['site-candidates'], queryFn: () => call(api.GET('/api/v2/sites/discover/')), enabled: mayRegister });
  const register = useMutation({
    mutationFn: (vars: { checkout: string; key: string }) =>
      call(api.POST('/api/v2/sites/', { body: { checkout: vars.checkout, key: vars.key } })),
    onSuccess: (made) => {
      void qc.invalidateQueries({ queryKey: ['sites'] });
      void qc.invalidateQueries({ queryKey: ['site-candidates'] });
      go({ to: 'site', id: made.site.id });
    },
  });
  if (!mayRegister || (candidates.error instanceof ApiError && candidates.error.status === 403)) return null;
  const chosen = typed.trim() || checkout || '';
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={4}>Register a site</Title>
        <Text size="sm" c="dimmed">
          Its pages are read in at once (a sync job you can follow); its files stay where they are.
        </Text>
        {candidates.isError ? <Alert color="red">{errorText(candidates.error)}</Alert> : null}
        <Group align="end" grow>
          <Select
            label="A known checkout"
            placeholder={candidates.data?.length ? 'Pick one' : 'None left to register'}
            data={(candidates.data ?? []).map((c) => ({ value: c.checkout, label: `${c.key} — ${c.checkout}` }))}
            value={checkout}
            onChange={(value) => {
              setCheckout(value);
              setKey(candidates.data?.find((c) => c.checkout === value)?.key ?? '');
            }}
            clearable
          />
          <TextInput label="…or its path" placeholder="sites/drsai" value={typed} onChange={(e) => setTyped(e.currentTarget.value)} />
          <TextInput label="Key" description="Letters, digits and hyphens" value={key} onChange={(e) => setKey(e.currentTarget.value)} />
        </Group>
        {register.isError ? <Alert color="red">{errorText(register.error)}</Alert> : null}
        <Group>
          <Button
            disabled={!chosen}
            loading={register.isPending}
            onClick={oneClick(() => register.mutate({ checkout: chosen, key: key.trim() }))}
          >
            Register and sync
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
