// Citation tracking: the questions people ask AI engines, and whether each
// engine's answer cites the site — asked now or on a schedule, every answer
// kept — with share of voice per engine and week by week. An engine is a
// provider of the AI layer; each check is a run of the citation probe.
import { Alert, Badge, Button, Group, MultiSelect, NumberInput, Paper, Progress, Stack, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AieoCitationQuery } from '@zer0/api';
import { useState } from 'react';

import { newKey, once, oneClick, useProviders } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';

export function Citations({ siteId }: { siteId?: number }) {
  return (
    <Stack>
      <TrackQuestion siteId={siteId} />
      <Queries siteId={siteId} />
      <ShareOfVoice siteId={siteId} />
    </Stack>
  );
}

function TrackQuestion({ siteId }: { siteId?: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const providers = useProviders();
  const [prompt, setPrompt] = useState('');
  const [domain, setDomain] = useState('');
  const [engines, setEngines] = useState<string[]>([]);
  const [days, setDays] = useState<number>(7);
  const track = useMutation({
    mutationFn: () =>
      call(
        api.POST('/api/v2/aieo/citations/queries/', {
          body: { prompt, domain, engines, interval_days: days, active: true, site: siteId ?? null, visibility: siteId ? 'site' : 'private' },
        }),
      ),
    onSuccess: () => {
      setPrompt('');
      void qc.invalidateQueries({ queryKey: ['aieo', 'queries'] });
    },
  });
  const enabled = (providers.data?.results ?? []).filter((p) => p.enabled);
  return (
    <Paper withBorder p="md" component="form" aria-label="Track a question" onSubmit={(e) => e.preventDefault()}>
      <Stack gap="sm">
        <Textarea label="A question people ask AI engines" autosize minRows={2} value={prompt} onChange={(e) => setPrompt(e.currentTarget.value)} />
        <Group align="end">
          <TextInput label="The site to look for" placeholder="example.com" value={domain} onChange={(e) => setDomain(e.currentTarget.value)} />
          <MultiSelect
            label="Engines"
            placeholder="The default provider"
            data={enabled.map((p) => ({ value: p.slug, label: p.display_name || p.slug }))}
            value={engines}
            onChange={setEngines}
            w={280}
          />
          <NumberInput label="Ask again every (days; 0 = on request)" min={0} max={365} w={240} value={days} onChange={(v) => setDays(Number(v) || 0)} />
        </Group>
        <Group>
          <Button disabled={!prompt.trim() || !domain.trim()} loading={track.isPending} onClick={oneClick(() => track.mutate())}>
            Track it
          </Button>
        </Group>
        {track.isError ? <Alert color="red">{errorText(track.error)}</Alert> : null}
      </Stack>
    </Paper>
  );
}

function Queries({ siteId }: { siteId?: number }) {
  const api = useApi();
  const queries = useQuery({
    queryKey: ['aieo', 'queries', siteId],
    queryFn: () => call(api.GET('/api/v2/aieo/citations/queries/', { params: { query: { site: siteId, page_size: 100 } } })),
    refetchInterval: (query) =>
      (query.state.data?.results ?? []).some((q) => Object.values(latestOf(q)).some((c) => c.status === 'queued')) ? 2000 : false,
  });
  return (
    <Stack gap="xs">
      <Title order={4}>Tracked questions</Title>
      {queries.isError ? <Alert color="red">{errorText(queries.error)}</Alert> : null}
      {queries.data?.results.length === 0 ? <Text c="dimmed">No questions tracked yet.</Text> : null}
      {queries.data?.results.length ? (
        <Table aria-label="Tracked questions">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Question</Table.Th>
              <Table.Th>Site</Table.Th>
              <Table.Th>Last answers</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {queries.data.results.map((q) => (
              <QueryRow key={q.id} query={q} />
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </Stack>
  );
}

interface Latest {
  cited: boolean | null;
  position: number | null;
  status: string;
}

/** Each engine's last answer, read defensively (the API types it as an object of objects). */
function latestOf(query: AieoCitationQuery): Record<string, Latest> {
  return Object.fromEntries(
    Object.entries(query.latest ?? {}).map(([engine, last]) => [
      engine,
      {
        cited: typeof last.cited === 'boolean' ? last.cited : null,
        position: typeof last.position === 'number' ? last.position : null,
        status: typeof last.status === 'string' ? last.status : '',
      },
    ]),
  );
}

function QueryRow({ query }: { query: AieoCitationQuery }) {
  const api = useApi();
  const qc = useQueryClient();
  const check = useMutation({
    mutationFn: (key: string) =>
      call(api.POST('/api/v2/aieo/citations/queries/{public_id}/check/', { params: { path: { public_id: query.id }, header: once(key) } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['aieo', 'queries'] });
      void qc.invalidateQueries({ queryKey: ['aieo', 'share'] });
    },
  });
  return (
    <Table.Tr>
      <Table.Td>{query.prompt}</Table.Td>
      <Table.Td>{query.domain}</Table.Td>
      <Table.Td>
        <Group gap={4}>
          {Object.entries(latestOf(query)).map(([engine, last]) => (
            <Badge key={engine} color={last.status === 'queued' ? 'blue' : last.cited ? 'teal' : last.status === 'failed' ? 'red' : 'gray'} variant="light">
              {engine}: {last.status === 'queued' ? 'asking…' : last.cited ? `cited${last.position ? ` #${last.position}` : ''}` : last.status === 'failed' ? 'failed' : 'not cited'}
            </Badge>
          ))}
        </Group>
        {check.isError ? <Text c="red" size="xs">{errorText(check.error)}</Text> : null}
      </Table.Td>
      <Table.Td>
        <Button size="xs" variant="light" loading={check.isPending} onClick={oneClick(() => check.mutate(newKey()))} disabled={!query.can_edit}>
          Ask now
        </Button>
      </Table.Td>
    </Table.Tr>
  );
}

function ShareOfVoice({ siteId }: { siteId?: number }) {
  const api = useApi();
  const share = useQuery({
    queryKey: ['aieo', 'share', siteId],
    queryFn: () => call(api.GET('/api/v2/aieo/citations/share/', { params: { query: { site: siteId } } })),
  });
  const data = share.data;
  const weeks = [...new Set((data?.weeks ?? []).map((w) => w.week))];
  const engines = (data?.engines ?? []).map((e) => e.engine);
  const at = (week: string, engine: string) => data?.weeks.find((w) => w.week === week && w.engine === engine);
  return (
    <Stack gap="xs">
      <Title order={4}>Share of voice</Title>
      {share.isError ? <Alert color="red">{errorText(share.error)}</Alert> : null}
      {data && !data.engines.length ? <Text c="dimmed">No answers yet in the last {data.days} days.</Text> : null}
      {(data?.engines ?? []).map((e) => (
        <div key={e.engine}>
          <Group justify="space-between">
            <Text size="sm">{e.engine}</Text>
            <Text size="sm">
              cited in {e.cited} of {e.checks} answers
            </Text>
          </Group>
          <Progress value={e.rate * 100} aria-label={`${e.engine} share of voice ${Math.round(e.rate * 100)}%`} />
        </div>
      ))}
      {weeks.length ? (
        <Table aria-label="Share of voice by week">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Week of</Table.Th>
              {engines.map((e) => (
                <Table.Th key={e}>{e}</Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {weeks.map((week) => (
              <Table.Tr key={week}>
                <Table.Td>{week}</Table.Td>
                {engines.map((engine) => {
                  const cell = at(week, engine);
                  return <Table.Td key={engine}>{cell ? `${Math.round(cell.rate * 100)}% (${cell.cited}/${cell.checks})` : '—'}</Table.Td>;
                })}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </Stack>
  );
}
