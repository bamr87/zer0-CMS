// Composing a post: a channel of the site, the page (or a story, whose page it
// is) it shares, and — optionally — the text that goes out with it; left empty,
// the platform starts from the page's own summary and tags. What comes back is
// a draft with the brand guard's findings and every blocker, which the person
// opens in the queue to approve. `Distribute` is the same form behind a button,
// for the editor and the newsroom's story panel.
import { Alert, Badge, Button, Group, Modal, SegmentedControl, Select, Stack, Text, Textarea } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { DistributionPostDetail } from '@zer0/api';
import { useState } from 'react';

import { oneClick } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { PagePicker } from '../PagePicker';
import { kindLabel, useChannels } from './shared';

interface Target {
  pageId?: number;
  storyId?: string;
  siteId?: number;
}

export function ComposeForm({ pageId, storyId, siteId, onDone }: Target & { onDone: (post: DistributionPostDetail) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const channels = useChannels(siteId);
  const [channel, setChannel] = useState<string | null>(null);
  const [page, setPage] = useState<number | null>(pageId ?? null);
  const [kind, setKind] = useState<'article' | 'update'>('article');
  const [commentary, setCommentary] = useState('');
  const all = channels.data?.results ?? [];
  const chosen = all.find((c) => c.id === channel);
  const compose = useMutation({
    mutationFn: () =>
      call(
        api.POST('/api/v2/distribution/posts/', {
          body: {
            channel: channel ?? '',
            kind,
            ...(kind === 'article' && page ? { page } : {}),
            ...(storyId ? { story: storyId } : {}),
            ...(commentary.trim() ? { commentary } : {}),
          },
        }),
      ),
    onSuccess: (post) => {
      void qc.invalidateQueries({ queryKey: ['distribution'] });
      onDone(post);
    },
  });
  return (
    <Stack>
      {channels.isSuccess && all.length === 0 ? (
        <Alert color="gray" title="No channel here yet">
          Someone who manages channels sets one up in Distribution → Channels.
        </Alert>
      ) : null}
      <Select
        label="Channel"
        placeholder="Where it goes"
        data={all.map((c) => ({ value: c.id, label: `${c.name} — ${kindLabel(c.kind)} (${c.site_name})` }))}
        value={channel}
        onChange={setChannel}
      />
      {chosen?.kind === 'linkedin' && !storyId && !pageId ? (
        <SegmentedControl
          value={kind}
          onChange={(v) => setKind(v as 'article' | 'update')}
          data={[
            { value: 'article', label: 'Share a page' },
            { value: 'update', label: 'A text update' },
          ]}
        />
      ) : null}
      {kind === 'article' && !storyId && !pageId ? <PagePicker label="Page" value={page} onChange={setPage} siteId={siteId} /> : null}
      <Textarea
        label="Text"
        description={kind === 'update' ? 'What the update says' : 'Optional: empty starts from the page’s own summary and tags'}
        autosize
        minRows={3}
        value={commentary}
        onChange={(e) => setCommentary(e.currentTarget.value)}
      />
      {compose.error ? <Alert color="red">{errorText(compose.error)}</Alert> : null}
      <Group justify="flex-end">
        <Button
          disabled={!channel || (kind === 'article' && !page && !storyId) || (kind === 'update' && !commentary.trim())}
          loading={compose.isPending}
          onClick={oneClick(() => compose.mutate())}
        >
          Draft the post
        </Button>
      </Group>
    </Stack>
  );
}

/** What a person sees after composing: the draft's guard findings and blockers, and the way to the queue. */
function Drafted({ post, onOpen }: { post: DistributionPostDetail; onOpen: () => void }) {
  const errors = post.guard.filter((f) => f.level === 'error');
  return (
    <Stack>
      <Alert color={errors.length ? 'yellow' : 'green'} title="Drafted">
        The post to {post.channel_name} is a draft: a person who may publish the page approves it in the queue.
      </Alert>
      {errors.map((f, i) => (
        <Group key={i} gap="xs">
          <Badge color="red" variant="light" size="sm">
            error
          </Badge>
          <Text size="sm">{f.message}</Text>
        </Group>
      ))}
      <Group justify="flex-end">
        <Button onClick={onOpen}>Open it in the queue</Button>
      </Group>
    </Stack>
  );
}

/** "Distribute" — the editor's and the story panel's way into the queue. */
export function Distribute({ pageId, storyId, siteId, disabled }: Target & { disabled?: boolean }) {
  const go = useGo();
  const [open, setOpen] = useState(false);
  const [made, setMade] = useState<DistributionPostDetail | null>(null);
  const close = () => {
    setOpen(false);
    setMade(null);
  };
  return (
    <>
      <Button variant="light" disabled={disabled} onClick={() => setOpen(true)}>
        Distribute
      </Button>
      <Modal opened={open} onClose={close} title="Distribute" size="lg" closeButtonProps={{ 'aria-label': 'Close' }}>
        {made ? (
          <Drafted post={made} onOpen={() => go({ to: 'distribution-post', id: made.id })} />
        ) : (
          <ComposeForm pageId={pageId} storyId={storyId} siteId={siteId} onDone={setMade} />
        )}
      </Modal>
    </>
  );
}
