// The Outbox workspace (ADR 0007): the outbox harness run from the platform — its belt of handoffs between pipeline
// stations, arena trials, and the claim desk with its calibration. A tab has an address ({ to: 'outbox', tab }),
// and so do a trial and a check (TrialView, ClaimCheckView), which the host routes. Every action is checked by the
// platform against the desk's Django permissions; a button the person may not use is shown, disabled.
import { Tabs } from '@mantine/core';

import { useGo, type OutboxTab } from '../context';
import { Belt } from './Belt';
import { ClaimDesk } from './ClaimDesk';
import { Trials } from './Trials';

export function OutboxDesk({ tab = 'belt' }: { tab?: OutboxTab }) {
  const go = useGo();
  return (
    <Tabs value={tab} onChange={(value) => go({ to: 'outbox', tab: (value ?? 'belt') as OutboxTab })} keepMounted={false}>
      <Tabs.List>
        <Tabs.Tab value="belt">Belt</Tabs.Tab>
        <Tabs.Tab value="trials">Trials</Tabs.Tab>
        <Tabs.Tab value="claims">Claim desk</Tabs.Tab>
      </Tabs.List>
      <Tabs.Panel value="belt" pt="md">
        <Belt />
      </Tabs.Panel>
      <Tabs.Panel value="trials" pt="md">
        <Trials />
      </Tabs.Panel>
      <Tabs.Panel value="claims" pt="md">
        <ClaimDesk />
      </Tabs.Panel>
    </Tabs>
  );
}
