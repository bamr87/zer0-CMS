// The ledger — what has been published, keyed by canonical URL, with the
// attempts that may have landed marked unconfirmed — and its statistics: the
// latest aggregate counts LinkedIn reported for each of the channels' own
// posts, the most seen first, with the totals. Nothing about who engaged.
import { Alert, Anchor, Badge, Loader, Select, Table, Text } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import type { DistributionLedgerEntry } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { kindLabel, useChannels, when } from './shared';

const METRICS = ['impressions', 'clicks', 'reactions', 'comments', 'shares', 'engagements'] as const;

function useLedger(siteId?: number, channel?: string | null) {
  const api = useApi();
  const query = { site: siteId, channel: channel ?? undefined, page_size: 200 };
  return useQuery({
    queryKey: ['distribution', 'ledger', query],
    queryFn: () => call(api.GET('/api/v2/distribution/ledger/', { params: { query } })),
  });
}

function ChannelFilter({ siteId, value, onChange }: { siteId?: number; value: string | null; onChange: (v: string | null) => void }) {
  const channels = useChannels(siteId);
  return (
    <Select
      label="Channel"
      placeholder="Every channel"
      data={(channels.data?.results ?? []).map((c) => ({ value: c.id, label: c.name }))}
      value={value}
      onChange={onChange}
      clearable
      w={240}
    />
  );
}

const linkFor = (entry: DistributionLedgerEntry) =>
  entry.urn.startsWith('urn:li:') ? `https://www.linkedin.com/feed/update/${entry.urn}/` : null;

export function Ledger({ siteId }: { siteId?: number }) {
  const go = useGo();
  const [channel, setChannel] = useState<string | null>(null);
  const ledger = useLedger(siteId, channel);
  return (
    <>
      <ChannelFilter siteId={siteId} value={channel} onChange={setChannel} />
      {ledger.isPending ? <Loader /> : null}
      {ledger.isError ? <Alert color="red">{errorText(ledger.error)}</Alert> : null}
      {ledger.isSuccess && ledger.data.results.length === 0 ? <Text c="dimmed">Nothing has been published yet.</Text> : null}
      {ledger.isSuccess && ledger.data.results.length > 0 ? (
        <Table aria-label="The ledger">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Key (canonical URL)</Table.Th>
              <Table.Th>Channel</Table.Th>
              <Table.Th>Published as</Table.Th>
              <Table.Th>When</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {ledger.data.results.map((entry) => (
              <Table.Tr key={entry.id}>
                <Table.Td>
                  {entry.post ? (
                    <Anchor component="button" type="button" onClick={() => entry.post && go({ to: 'distribution-post', id: entry.post })}>
                      {entry.key}
                    </Anchor>
                  ) : (
                    entry.key
                  )}
                </Table.Td>
                <Table.Td>
                  {entry.channel_name} <Text span size="xs" c="dimmed">({kindLabel(entry.channel_kind)})</Text>
                </Table.Td>
                <Table.Td>
                  {entry.state === 'unconfirmed' ? (
                    <Badge color="red" variant="light" title={entry.error}>
                      unconfirmed — may have published
                    </Badge>
                  ) : linkFor(entry) ? (
                    <Anchor href={linkFor(entry) ?? undefined} target="_blank" rel="noreferrer">
                      {entry.urn}
                    </Anchor>
                  ) : (
                    entry.urn
                  )}
                </Table.Td>
                <Table.Td>{when(entry.posted_at ?? entry.attempted_at)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </>
  );
}

export function Statistics({ siteId }: { siteId?: number }) {
  const [channel, setChannel] = useState<string | null>(null);
  const ledger = useLedger(siteId, channel);
  const measured = (ledger.data?.results ?? [])
    .filter((e) => e.latest)
    .sort((a, b) => (b.latest?.impressions ?? 0) - (a.latest?.impressions ?? 0));
  const total = (metric: (typeof METRICS)[number]) => measured.reduce((sum, e) => sum + (e.latest?.[metric] ?? 0), 0);
  return (
    <>
      <ChannelFilter siteId={siteId} value={channel} onChange={setChannel} />
      <Text size="sm" c="dimmed">
        Aggregate counts for the channels’ own LinkedIn posts, read once a day (or now, from a channel’s panel). Nothing about who
        engaged is read or kept.
      </Text>
      {ledger.isPending ? <Loader /> : null}
      {ledger.isError ? <Alert color="red">{errorText(ledger.error)}</Alert> : null}
      {ledger.isSuccess && measured.length === 0 ? <Text c="dimmed">No statistics yet.</Text> : null}
      {measured.length ? (
        <Table aria-label="Statistics">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Post</Table.Th>
              {METRICS.map((m) => (
                <Table.Th key={m}>{m}</Table.Th>
              ))}
              <Table.Th>Read</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {measured.map((entry) => (
              <Table.Tr key={entry.id}>
                <Table.Td>{entry.key}</Table.Td>
                {METRICS.map((m) => (
                  <Table.Td key={m}>{entry.latest?.[m]}</Table.Td>
                ))}
                <Table.Td>{entry.latest?.day}</Table.Td>
              </Table.Tr>
            ))}
            <Table.Tr>
              <Table.Td fw={600}>All of them</Table.Td>
              {METRICS.map((m) => (
                <Table.Td key={m} fw={600}>
                  {total(m)}
                </Table.Td>
              ))}
              <Table.Td />
            </Table.Tr>
          </Table.Tbody>
        </Table>
      ) : null}
    </>
  );
}
