// The Distribution workspace (TARGET.md § The studio: "channels, queue,
// ledger, statistics"): the queue of posts and composing one, the channels and
// their connections, what has been published, and how it did. A post and a
// channel open in a drawer beside it; opening one asks the host to go to it
// ({ to: 'distribution-post' } / { to: 'channel' }), so each has an address —
// LinkedIn's consent screen returns the person to their channel's.
import { Drawer, Stack, Tabs } from '@mantine/core';
import { useState } from 'react';

import { useGo, type DistributionTab } from '../context';
import { ChannelPanel, Channels } from './Channels';
import { Ledger, Statistics } from './Ledger';
import { PostPanel } from './PostPanel';
import { Queue } from './Queue';

interface Props {
  siteId?: number;
  tab?: DistributionTab;
  postId?: string;
  channelId?: string;
  /** The person just came back from LinkedIn's consent screen. */
  connecting?: boolean;
}

export function Distribution({ siteId, tab: firstTab, postId, channelId, connecting }: Props) {
  const go = useGo();
  const [tab, setTab] = useState<string | null>(firstTab ?? (channelId ? 'channels' : 'queue'));
  // The host may name a tab (closing a channel goes back to Channels); one it does not name keeps the person's.
  const [named, setNamed] = useState(firstTab);
  if (firstTab !== named) {
    setNamed(firstTab);
    if (firstTab) setTab(firstTab);
  }
  return (
    <Stack>
      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="queue">Queue</Tabs.Tab>
          <Tabs.Tab value="channels">Channels</Tabs.Tab>
          <Tabs.Tab value="ledger">Ledger</Tabs.Tab>
          <Tabs.Tab value="statistics">Statistics</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="queue" pt="md">
          <Stack>
            <Queue siteId={siteId} />
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="channels" pt="md">
          <Channels siteId={siteId} />
        </Tabs.Panel>
        <Tabs.Panel value="ledger" pt="md">
          <Stack>
            <Ledger siteId={siteId} />
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="statistics" pt="md">
          <Stack>
            <Statistics siteId={siteId} />
          </Stack>
        </Tabs.Panel>
      </Tabs>
      <Drawer
        opened={postId !== undefined}
        onClose={() => go({ to: 'distribution' })}
        position="right"
        size="xl"
        title="Post"
        closeButtonProps={{ 'aria-label': 'Close the post' }}
      >
        {postId ? <PostPanel postId={postId} /> : null}
      </Drawer>
      <Drawer
        opened={channelId !== undefined}
        onClose={() => go({ to: 'distribution', tab: 'channels' })}
        position="right"
        size="xl"
        title="Channel"
        closeButtonProps={{ 'aria-label': 'Close the channel' }}
      >
        {channelId ? <ChannelPanel channelId={channelId} connecting={connecting} /> : null}
      </Drawer>
    </Stack>
  );
}
