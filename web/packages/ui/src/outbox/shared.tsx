// What the Outbox desk's screens share: the person's permissions on the desk (the platform checks again on every
// request), a trial's or a check's status as a badge, how long to keep reading a row the worker is still on, and
// reading the JSON a person typed into a field.
import { Badge } from '@mantine/core';
import type { OutboxRunStatus } from '@zer0/api';

import { useMe } from '../ai/shared';

/** A row the worker has not finished: read again until it has. */
export const WAITING = new Set<OutboxRunStatus | null>(['queued', 'running']);
export const POLL_MS = 1500;

const LOOK: Record<OutboxRunStatus, string> = { queued: 'yellow', running: 'yellow', succeeded: 'teal', failed: 'red' };

export function RunStatusBadge({ status }: { status: OutboxRunStatus }) {
  return (
    <Badge color={LOOK[status]} variant="light">
      {status}
    </Badge>
  );
}

/** A verdict or an outcome as a badge: green when it holds, red when it does not, grey when unknown. */
export function YesNo({ value, yes, no }: { value: boolean | null | undefined; yes: string; no: string }) {
  if (value === null || value === undefined) return <Badge color="gray" variant="light">—</Badge>;
  return (
    <Badge color={value ? 'teal' : 'red'} variant="light">
      {value ? yes : no}
    </Badge>
  );
}

/** Whether the person holds one of the desk's permissions (`outboxdesk.<codename>`). */
export function useCan(codename: string): boolean {
  return useMe().data?.permissions.includes(`outboxdesk.${codename}`) ?? false;
}

/** The JSON a person typed, or why it is not JSON. */
export function parseJson(text: string): { value?: unknown; error?: string } {
  try {
    return { value: JSON.parse(text) as unknown };
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}

/** A value from the belt or an arena, as one line a person reads: strings as they are, the rest as JSON. */
export const shown = (value: unknown): string => (typeof value === 'string' ? value : JSON.stringify(value));

export const when = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : '—');
