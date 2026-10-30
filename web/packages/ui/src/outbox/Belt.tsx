// The belt (the outbox harness's, ADR 0007): what the relay delivered, refused and still holds; the messages on its
// ledger, filtered by kind, station and trace and paged; one message with its CloudEvents form and its piece of
// work's journey; the dead letters; and, for people who may, sending as the editor station and running the relay
// now. The ledger is the record, read through the platform — nothing here keeps a copy.
import { Alert, Anchor, Badge, Button, Drawer, Group, Loader, Modal, Pagination, Select, Stack, Table, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { BeltSummary, Handoff, HandoffKind } from '@zer0/api';
import { useState } from 'react';

import { JsonView } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';
import { SendHandoff } from './SendHandoff';
import { useCan, when } from './shared';

const KINDS: HandoffKind[] = ['idea', 'assignment', 'draft', 'verdict', 'approval', 'published', 'signal'];
const PAGE = 25;
/** How long a relay pass the person asked for is followed (the summary read again while records wait). */
const FOLLOW_MS = 30_000;

export function Belt() {
  const api = useApi();
  const canSend = useCan('send_handoff');
  const canDeliver = useCan('deliver_belt');
  const [followSince, setFollowSince] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [sending, setSending] = useState<{ parent?: Handoff } | null>(null);
  const [trace, setTrace] = useState('');
  const summary = useQuery({
    queryKey: ['belt'],
    queryFn: () => call(api.GET('/api/v2/outbox/belt/')),
    refetchInterval: (q) => ((q.state.data?.pending ?? 0) > 0 && Date.now() - followSince < FOLLOW_MS ? 1000 : false),
  });
  const deliver = useMutation({
    mutationFn: () => call(api.POST('/api/v2/outbox/belt/deliver/')),
    onSuccess: () => {
      setFollowSince(Date.now());
      void summary.refetch();
    },
  });

  if (summary.isPending) return <Loader aria-label="Loading the belt" />;
  if (summary.isError) return <Alert color="red">{errorText(summary.error)}</Alert>;
  const belt = summary.data;
  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <Counts belt={belt} />
        <Group>
          <Button variant="light" disabled={!canSend} onClick={() => setSending({})}>
            Send a handoff
          </Button>
          <Button disabled={!canDeliver} loading={deliver.isPending} onClick={() => deliver.mutate()}>
            Deliver now
          </Button>
        </Group>
      </Group>
      {deliver.isError ? <Alert color="red">{errorText(deliver.error)}</Alert> : null}
      {deliver.isSuccess && belt.pending > 0 ? (
        <Text size="sm" c="dimmed">
          The relay is on its way: {belt.pending} record{belt.pending === 1 ? '' : 's'} waiting.
        </Text>
      ) : null}
      <Messages belt={belt} trace={trace} onTrace={setTrace} onOpen={setOpen} />
      <DeadLetters count={belt.dead_letters} />
      <Drawer opened={open !== null} onClose={() => setOpen(null)} position="right" size="xl" title="Message" lockScroll={false} closeButtonProps={{ 'aria-label': 'Close the message' }}>
        {open ? (
          <MessageView
            id={open}
            canSend={canSend}
            onTrace={(t) => {
              setTrace(t);
              setOpen(null);
            }}
            onReply={(parent) => {
              setOpen(null);
              setSending({ parent });
            }}
          />
        ) : null}
      </Drawer>
      <Modal opened={sending !== null} onClose={() => setSending(null)} title="Send as the editor station" size="lg" lockScroll={false} closeButtonProps={{ 'aria-label': 'Close' }}>
        {sending ? <SendHandoff stations={belt.stations} parent={sending.parent} onSent={() => setSending(null)} /> : null}
      </Modal>
    </Stack>
  );
}

function Counts({ belt }: { belt: BeltSummary }) {
  const items: [string, number][] = [
    ['Delivered', belt.delivered],
    ['Waiting', belt.pending],
    ['Dead letters', belt.dead_letters],
    ['Pieces of work', belt.traces],
  ];
  return (
    <Stack gap={4}>
      <Group gap="lg" aria-label="The belt in numbers">
        {items.map(([label, value]) => (
          <Stack key={label} gap={0}>
            <Text size="xs" c="dimmed">
              {label}
            </Text>
            <Text fw={600} aria-label={label}>
              {value}
            </Text>
          </Stack>
        ))}
      </Group>
      <Group gap={4}>
        <Badge color={belt.seq_gapless ? 'teal' : 'red'} variant="light">
          {belt.seq_gapless ? 'sequence gapless' : 'sequence has gaps'}
        </Badge>
        <Badge color={belt.ids_unique ? 'teal' : 'red'} variant="light">
          {belt.ids_unique ? 'ids unique' : 'ids repeat'}
        </Badge>
        {belt.kinds.map((k) => (
          <Badge key={k.kind} color="gray" variant="outline">
            {k.kind} {k.count}
          </Badge>
        ))}
        <Text size="xs" c="dimmed">
          harness {belt.harness}
        </Text>
      </Group>
    </Stack>
  );
}

interface MessagesProps {
  belt: BeltSummary;
  trace: string;
  onTrace: (trace: string) => void;
  onOpen: (id: string) => void;
}

function Messages({ belt, trace, onTrace, onOpen }: MessagesProps) {
  const api = useApi();
  const [kind, setKind] = useState<HandoffKind | null>(null);
  const [station, setStation] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const query = { kind: kind ?? undefined, station: station ?? undefined, trace: trace || undefined, page, page_size: PAGE };
  const messages = useQuery({
    // A relay pass changes what the ledger holds; reading the count into the key reads the list again after one.
    queryKey: ['belt-messages', query, belt.delivered],
    queryFn: () => call(api.GET('/api/v2/outbox/belt/messages/', { params: { query } })),
  });
  const filter = (set: () => void) => {
    set();
    setPage(1);
  };
  const pages = Math.max(1, Math.ceil((messages.data?.count ?? 0) / PAGE));
  return (
    <Stack gap="xs">
      <Title order={4}>Messages</Title>
      <Group align="flex-end">
        <Select label="Kind" placeholder="Every kind" clearable w={160} data={KINDS} value={kind} onChange={(v) => filter(() => setKind(v as HandoffKind | null))} />
        <Select label="Station" placeholder="Every station" clearable w={180} data={belt.stations} value={station} onChange={(v) => filter(() => setStation(v))} />
        <TextInput label="Trace" placeholder="32 hex digits" w={300} value={trace} onChange={(e) => filter(() => onTrace(e.currentTarget.value.trim()))} />
      </Group>
      {messages.isPending ? <Loader aria-label="Loading messages" /> : null}
      {messages.isError ? <Alert color="red">{errorText(messages.error)}</Alert> : null}
      {messages.data?.count === 0 ? <Text c="dimmed">No message on the ledger{kind || station || trace ? ' matches' : ' yet'}.</Text> : null}
      {messages.data?.results.length ? (
        <Table highlightOnHover aria-label="Messages">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Seq</Table.Th>
              <Table.Th>Kind</Table.Th>
              <Table.Th>From → to</Table.Th>
              <Table.Th>Subject</Table.Th>
              <Table.Th>Trace</Table.Th>
              <Table.Th>Sent</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {messages.data.results.map((m) => (
              <Table.Tr key={m.id}>
                <Table.Td>{m.seq}</Table.Td>
                <Table.Td>
                  <Anchor component="button" type="button" onClick={() => onOpen(m.id)} aria-label={`Open ${m.kind} ${m.seq ?? ''}`.trim()}>
                    {m.kind}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  {m.from} → {m.to.join(', ')}
                </Table.Td>
                <Table.Td>{m.subject}</Table.Td>
                <Table.Td>
                  <Anchor component="button" type="button" size="sm" ff="monospace" onClick={() => filter(() => onTrace(m.trace))} aria-label={`Follow trace ${m.trace}`}>
                    {m.trace.slice(0, 8)}
                  </Anchor>
                </Table.Td>
                <Table.Td>{when(m.created_at)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
      {pages > 1 ? <Pagination total={pages} value={page} onChange={setPage} aria-label="Pages of messages" /> : null}
    </Stack>
  );
}

interface MessageViewProps {
  id: string;
  canSend: boolean;
  onTrace: (trace: string) => void;
  onReply: (parent: Handoff) => void;
}

function MessageView({ id, canSend, onTrace, onReply }: MessageViewProps) {
  const api = useApi();
  const message = useQuery({
    queryKey: ['belt-message', id],
    queryFn: () => call(api.GET('/api/v2/outbox/belt/messages/{message_id}/', { params: { path: { message_id: id } } })),
  });
  const trace = message.data?.trace;
  const journey = useQuery({
    queryKey: ['belt-journey', trace],
    queryFn: () => call(api.GET('/api/v2/outbox/belt/traces/{trace}/', { params: { path: { trace: trace ?? '' } } })),
    enabled: Boolean(trace),
  });
  if (message.isPending) return <Loader aria-label="Loading the message" />;
  if (message.isError) return <Alert color="red">{errorText(message.error)}</Alert>;
  const m = message.data;
  return (
    <Stack>
      <Group justify="space-between">
        <Text fw={600}>
          #{m.seq} {m.kind} · {m.from} → {m.to.join(', ')}
        </Text>
        <Button size="xs" variant="light" disabled={!canSend} onClick={() => onReply(m)}>
          Answer it
        </Button>
      </Group>
      <Text size="sm">Subject: {m.subject}</Text>
      {m.parent_id ? <Text size="sm">Answers: {m.parent_id}</Text> : null}
      <JsonView label="Payload" value={m.payload} />
      {m.ref ? <JsonView label="What it is about" value={m.ref} /> : null}
      <Title order={5}>Its piece of work</Title>
      {journey.isError ? <Alert color="red">{errorText(journey.error)}</Alert> : null}
      <Table aria-label="Journey">
        <Table.Tbody>
          {(journey.data?.messages ?? []).map((step) => (
            <Table.Tr key={step.id} fw={step.id === m.id ? 700 : undefined}>
              <Table.Td>{step.seq}</Table.Td>
              <Table.Td>{step.kind}</Table.Td>
              <Table.Td>
                {step.from} → {step.to.join(', ')}
              </Table.Td>
              <Table.Td>{when(step.created_at)}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      <Anchor component="button" type="button" size="sm" onClick={() => onTrace(m.trace)}>
        Show only this piece’s messages
      </Anchor>
      <Title order={5}>As a CloudEvent</Title>
      <JsonView label="CloudEvent" value={m.cloudevent} />
    </Stack>
  );
}

function DeadLetters({ count }: { count: number }) {
  const api = useApi();
  const dead = useQuery({
    queryKey: ['belt-dead-letters', count],
    queryFn: () => call(api.GET('/api/v2/outbox/belt/dead-letters/')),
  });
  return (
    <Stack gap="xs">
      <Title order={4}>Dead letters</Title>
      {dead.isError ? <Alert color="red">{errorText(dead.error)}</Alert> : null}
      {dead.data?.length === 0 ? <Text c="dimmed">The relay has refused nothing.</Text> : null}
      {dead.data?.length ? (
        <Table aria-label="Dead letters">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Station</Table.Th>
              <Table.Th>File</Table.Th>
              <Table.Th>Why</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {dead.data.map((d) => (
              <Table.Tr key={d.id}>
                <Table.Td>{d.station}</Table.Td>
                <Table.Td ff="monospace">{d.path}</Table.Td>
                <Table.Td>{d.errors.join(', ')}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </Stack>
  );
}
