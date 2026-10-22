// Where a page stands, in one badge: the platform's five states
// (api/pages.py status_of) with the words an editor uses for them.
import { Badge } from '@mantine/core';
import type { PageStatus } from '@zer0/api';

const LOOK: Record<PageStatus, { color: string; label: string }> = {
  draft: { color: 'gray', label: 'Draft' },
  live: { color: 'teal', label: 'Live' },
  changed: { color: 'yellow', label: 'Live + draft' },
  scheduled: { color: 'blue', label: 'Scheduled' },
  expired: { color: 'red', label: 'Expired' },
};

export const STATUS_OPTIONS = Object.entries(LOOK).map(([value, { label }]) => ({ value, label }));

export function StatusBadge({ status }: { status: PageStatus }) {
  return (
    <Badge color={LOOK[status].color} variant="light">
      {LOOK[status].label}
    </Badge>
  );
}
