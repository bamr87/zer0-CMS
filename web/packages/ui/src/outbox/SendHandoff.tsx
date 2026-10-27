// Send a handoff onto the belt as the editor station: a new idea, an approval of a delivered message (a reply: it
// keeps the message's trace and subject), or a signal about a piece of work (on its trace). The platform validates
// it with the harness, records who sent it and writes it to the editor's outbox; the relay delivers it on its next
// pass. What it is about can be a page the person finds.
import { Alert, Button, Group, MultiSelect, SegmentedControl, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { Handoff, SendableKind } from '@zer0/api';
import { useState } from 'react';

import { fieldError, isRecord, oneClick } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';
import { PagePicker } from '../PagePicker';
import { parseJson } from './shared';

interface Props {
  /** The stations on the belt (the summary's). */
  stations: string[];
  /** A delivered message this answers: an approval of it, or a signal about it. */
  parent?: Handoff;
  onSent: (sent: Handoff) => void;
}

export function SendHandoff({ stations, parent, onSent }: Props) {
  const api = useApi();
  const qc = useQueryClient();
  const [kind, setKind] = useState<SendableKind>(parent ? 'approval' : 'idea');
  // An approval goes on toward publishing; a new idea goes to planning — each where the belt has that station.
  const [to, setTo] = useState<string[]>(() => [parent ? 'publisher' : 'planner'].filter((s) => stations.includes(s)).concat('ledger'));
  const [subject, setSubject] = useState(parent?.subject ?? '');
  const [trace, setTrace] = useState('');
  const [payload, setPayload] = useState('{}');
  const [page, setPage] = useState<number | null>(null);
  const parsed = parseJson(payload);
  const send = useMutation({
    mutationFn: () => {
      if (!isRecord(parsed.value)) throw new Error('The payload is a JSON object');
      return call(
        api.POST('/api/v2/outbox/belt/send/', {
          body: {
            kind,
            to,
            subject,
            payload: parsed.value,
            parent_id: parent && kind !== 'idea' ? parent.id : '',
            trace: !parent && kind === 'signal' ? trace : '',
            page,
          },
        }),
      );
    },
    onSuccess: (sent) => {
      void qc.invalidateQueries({ queryKey: ['belt'] });
      onSent(sent);
    },
  });
  const payloadError = parsed.error ?? (isRecord(parsed.value) ? undefined : 'The payload is a JSON object');

  return (
    <Stack
      component="form"
      aria-label="Send a handoff"
      onSubmit={(e) => {
        e.preventDefault();
        send.mutate();
      }}
    >
      {parent ? (
        <Text size="sm">
          Answers {parent.kind} <code>{parent.id}</code> from {parent.from}, on its trace.
        </Text>
      ) : null}
      <SegmentedControl
        aria-label="Kind"
        value={kind}
        onChange={(value) => setKind(value as SendableKind)}
        data={[
          { value: 'idea', label: 'Idea', disabled: Boolean(parent) },
          { value: 'approval', label: 'Approval', disabled: !parent },
          { value: 'signal', label: 'Signal' },
        ]}
      />
      <MultiSelect label="To" data={[...stations, 'ledger']} value={to} onChange={setTo} error={fieldError(send.error, 'to')} />
      <TextInput
        label="Subject"
        description={parent ? 'The piece of work it is about; the parent’s unless you change it.' : 'The stable key of the piece of work.'}
        value={subject}
        onChange={(e) => setSubject(e.currentTarget.value)}
        error={fieldError(send.error, 'subject')}
      />
      {kind === 'signal' && !parent ? (
        <TextInput
          label="Trace"
          description="The piece of work's trace (32 hex digits); empty starts a new one."
          value={trace}
          onChange={(e) => setTrace(e.currentTarget.value.trim())}
          error={fieldError(send.error, 'trace')}
        />
      ) : null}
      <PagePicker label="About a page" description="Optional: the page this is about." value={page} onChange={setPage} />
      <Textarea
        label="Payload"
        description="A JSON object; the platform adds who sent it (by)."
        autosize
        minRows={3}
        ff="monospace"
        value={payload}
        onChange={(e) => setPayload(e.currentTarget.value)}
        error={payloadError ?? fieldError(send.error, 'payload')}
      />
      {send.isError ? <Alert color="red">{errorText(send.error)}</Alert> : null}
      <Group>
        <Button type="submit" loading={send.isPending} disabled={to.length === 0 || Boolean(payloadError)} onClick={oneClick()}>
          Send
        </Button>
      </Group>
    </Stack>
  );
}
