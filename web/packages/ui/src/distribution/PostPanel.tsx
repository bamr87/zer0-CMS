// A post in the queue: where it goes and what it shares, its text (saved as
// what changed — changing the text of an approved post, or of one whose
// attempt failed, sends it back to draft: a person approves the exact text),
// the brand guard's findings, every blocker publishing it now would meet, and
// for LinkedIn the exact payload — and, while an email post waits, that the
// newsroom is sending its issue — and its notes (where its site ledger entry
// went, say). Approve, reject, publish (asked first, never
// with unsaved changes, and past a lifted gate only when the person ticks
// "force"), and record a post
// found at the target after an attempt that may have landed. The platform
// checks every one of these again; a disabled button is a courtesy.
import { Alert, Anchor, Badge, Button, Checkbox, Code, Group, Loader, Modal, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { DistributionPostDetail } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { kindLabel, statusOf, usePost, when } from './shared';

const FORCEABLE = ['guard_error', 'already_published', 'publish_unconfirmed'];
const LEVEL_COLOR = { error: 'red', warning: 'yellow', info: 'gray' };

export function PostPanel({ postId }: { postId: string }) {
  const post = usePost(postId);
  if (post.isPending) return <Loader />;
  if (post.isError) return <Alert color="red">{errorText(post.error)}</Alert>;
  return <Panel key={post.data.updated_at} post={post.data} />;
}

function Panel({ post }: { post: DistributionPostDetail }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const path = { params: { path: { public_id: post.id } } };
  const [text, setText] = useState({ title: post.title, description: post.description, commentary: post.commentary });
  const [reason, setReason] = useState('');
  const [urn, setUrn] = useState('');
  const [confirming, setConfirming] = useState(false);
  const [force, setForce] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ['distribution'] });
  const changed = Object.fromEntries(Object.entries(text).filter(([name, value]) => value !== post[name as keyof typeof text]));
  const save = useMutation({
    mutationFn: () => call(api.PATCH('/api/v2/distribution/posts/{public_id}/', { ...path, body: changed })),
    onSuccess: refresh,
  });
  const approve = useMutation({ mutationFn: () => call(api.POST('/api/v2/distribution/posts/{public_id}/approve/', path)), onSuccess: refresh });
  const reject = useMutation({
    mutationFn: () => call(api.POST('/api/v2/distribution/posts/{public_id}/reject/', { ...path, body: { reason } })),
    onSuccess: refresh,
  });
  const publish = useMutation({
    mutationFn: () => call(api.POST('/api/v2/distribution/posts/{public_id}/publish/', { ...path, body: { force } })),
    onSuccess: () => {
      setConfirming(false);
      void refresh();
    },
  });
  const record = useMutation({
    mutationFn: () => call(api.POST('/api/v2/distribution/posts/{public_id}/record/', { ...path, body: { urn } })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/v2/distribution/posts/{public_id}/', path)),
    onSuccess: () => {
      void refresh();
      go({ to: 'distribution' });
    },
  });

  const editable = !['publishing', 'published'].includes(post.status);
  const approved = ['approved', 'failed'].includes(post.status);
  const unsaved = Object.keys(changed).length > 0;
  const status = statusOf(post.status);
  const forceable = post.blockers.some((b) => FORCEABLE.includes(b.kind));
  const failure = save.error ?? approve.error ?? reject.error ?? publish.error ?? record.error ?? remove.error;

  return (
    <Stack>
      <Group gap="xs">
        <Badge color={status.color}>{status.label}</Badge>
        <Text size="sm" c="dimmed">
          {post.channel_name} · {kindLabel(post.channel_kind)} · {post.kind === 'update' ? 'a text update' : 'an article'} · drafted by{' '}
          {post.origin === 'person' ? (post.created_by ?? 'a person') : post.origin === 'agent' ? 'an agent' : 'the page going live'}
        </Text>
      </Group>
      <Title order={3}>{post.title || post.page_title || 'Untitled'}</Title>
      {post.page ? (
        <Anchor component="button" type="button" size="sm" onClick={() => post.page && go({ to: 'page', id: post.page })}>
          Open “{post.page_title}” in the editor
        </Anchor>
      ) : null}
      {post.link ? (
        <Text size="sm">
          Canonical URL (the ledger’s key): <Code>{post.link}</Code>
        </Text>
      ) : null}
      {post.status === 'publishing' ? (
        <Alert color="blue">
          {post.channel_kind === 'email' && post.attempted_at ? 'The newsroom is sending the newsletter issue…' : 'The worker is publishing it…'}
        </Alert>
      ) : null}
      {post.status === 'published' ? (
        <Alert color="green" title="Published">
          {post.external_url ? (
            <Anchor href={post.external_url} target="_blank" rel="noreferrer">
              {post.external_id}
            </Anchor>
          ) : (
            post.external_id
          )}{' '}
          on {when(post.published_at)}.
        </Alert>
      ) : null}
      {post.error ? (
        <Alert color="red" title="It did not go">
          {post.error}
          {post.external_url ? (
            <>
              {' '}
              <Anchor href={post.external_url} target="_blank" rel="noreferrer">
                Open it
              </Anchor>
            </>
          ) : null}
        </Alert>
      ) : null}
      {post.status === 'rejected' && post.reason ? <Alert color="orange">Rejected: {post.reason}</Alert> : null}
      {post.notes.length ? (
        <Stack gap={2} aria-label="Notes">
          {post.notes.map((note, i) => (
            <Text key={i} size="sm" c="dimmed">
              {note}
            </Text>
          ))}
        </Stack>
      ) : null}
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}

      <TextInput label="Title" value={text.title} disabled={!editable} onChange={(e) => setText({ ...text, title: e.currentTarget.value })} />
      <Textarea
        label="Description"
        description="The link card's description; WordPress's meta description"
        autosize
        minRows={2}
        value={text.description}
        disabled={!editable}
        onChange={(e) => setText({ ...text, description: e.currentTarget.value })}
      />
      <Textarea
        label="Text"
        description="What goes out with it: the post's commentary, a WordPress excerpt, a pull request's description, a newsletter's introduction"
        autosize
        minRows={4}
        value={text.commentary}
        disabled={!editable}
        onChange={(e) => setText({ ...text, commentary: e.currentTarget.value })}
      />
      {editable ? (
        <Group justify="flex-end">
          {approved && unsaved ? (
            <Text size="sm" c="dimmed">
              Saving a changed text sends the post back to draft: a person approves the exact text that goes.
            </Text>
          ) : null}
          <Button variant="default" disabled={!unsaved} loading={save.isPending} onClick={() => save.mutate()}>
            Save the text
          </Button>
        </Group>
      ) : null}

      <Title order={5}>Brand guard</Title>
      <Stack gap={4} aria-label="Brand guard">
        {post.guard.map((finding, i) => (
          <Group key={i} gap="xs" wrap="nowrap" align="flex-start">
            <Badge size="sm" color={LEVEL_COLOR[finding.level]} variant="light">
              {finding.level}
            </Badge>
            <Text size="sm">{finding.message}</Text>
          </Group>
        ))}
      </Stack>

      <Title order={5}>Before it can go</Title>
      {post.blockers.length === 0 ? (
        <Text size="sm">Nothing stands in the way.</Text>
      ) : (
        <Stack gap={4} aria-label="Blockers">
          {post.blockers.map((b) => (
            <Text key={b.kind} size="sm">
              <Code>{b.kind}</Code> {b.message}
            </Text>
          ))}
        </Stack>
      )}
      {post.payload ? (
        <details>
          <summary>The exact LinkedIn request</summary>
          <Code block>{JSON.stringify(post.payload, null, 2)}</Code>
        </details>
      ) : null}

      <Group gap="xs">
        {post.status === 'draft' ? (
          <Button disabled={!post.can_publish} loading={approve.isPending} onClick={() => approve.mutate()}>
            Approve
          </Button>
        ) : null}
        {approved ? (
          <Button disabled={!post.can_publish || unsaved} onClick={() => setConfirming(true)}>
            Publish…
          </Button>
        ) : null}
        {['draft', 'rejected'].includes(post.status) ? (
          <Button variant="subtle" color="red" loading={remove.isPending} onClick={() => remove.mutate()}>
            Delete
          </Button>
        ) : null}
      </Group>
      {editable && post.status !== 'rejected' ? (
        <Group align="flex-end">
          <TextInput label="Why reject it" value={reason} onChange={(e) => setReason(e.currentTarget.value)} style={{ flex: 1 }} />
          <Button variant="default" color="orange" disabled={!post.can_publish} loading={reject.isPending} onClick={() => reject.mutate()}>
            Reject
          </Button>
        </Group>
      ) : null}
      {post.status === 'failed' || post.blockers.some((b) => b.kind === 'publish_unconfirmed') ? (
        <Group align="flex-end">
          <TextInput
            label="It went out after all? Record it"
            description="The post's id at the target — a LinkedIn post URN (urn:li:share:…), a post id, a URL"
            value={urn}
            onChange={(e) => setUrn(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button variant="default" disabled={!urn.trim() || !post.can_publish} loading={record.isPending} onClick={() => record.mutate()}>
            Record
          </Button>
        </Group>
      ) : null}

      <Modal opened={confirming} onClose={() => setConfirming(false)} title="Publish this post?" closeButtonProps={{ 'aria-label': 'Close' }}>
        <Stack>
          <Text size="sm">
            It goes to {post.channel_name} ({kindLabel(post.channel_kind)}) now, and the ledger keeps it from going there twice.
          </Text>
          {forceable ? (
            <Checkbox
              label="Force it past the brand guard, the ledger or an unconfirmed attempt — I have read why it is blocked"
              checked={force}
              onChange={(e) => setForce(e.currentTarget.checked)}
            />
          ) : null}
          {publish.error ? <Alert color="red">{errorText(publish.error)}</Alert> : null}
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button loading={publish.isPending} onClick={() => publish.mutate()}>
              Publish now
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}
