// Newsletters: a site's lists and their subscribers (confirmed, waiting to
// confirm, gone — subscribing is double opt-in), each list's issues, composing
// an issue from published stories (newest first, searched as one types), its
// preview exactly as it is sent, and sending it: as a job on the platform, to
// the confirmed subscribers, once each — a send that failed part way, or that
// a worker left unfinished, is sent again to those who have not had it.
import { Alert, Badge, Button, Card, Code, Group, Loader, MultiSelect, Select, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Issue, Newsletter } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { slugify } from './Fronts';
import { usePublishedPicker, when } from './shared';

const COLOR = { draft: 'gray', sending: 'blue', sent: 'green', failed: 'red' };

export function Newsletters({ siteId }: { siteId?: number }) {
  return siteId ? <SiteNewsletters siteId={siteId} /> : <Text c="dimmed">Pick a site in the header to work on its newsletters.</Text>;
}

function SiteNewsletters({ siteId }: { siteId: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<string | null>(null);
  const [name, setName] = useState('');
  const lists = useQuery({
    queryKey: ['newsroom', 'newsletters', siteId],
    queryFn: () => call(api.GET('/api/v2/newsroom/newsletters/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
  const create = useMutation({
    mutationFn: () => call(api.POST('/api/v2/newsroom/newsletters/', { body: { site: siteId, name, slug: slugify(name) } })),
    onSuccess: (made) => {
      setName('');
      setChosen(made.id);
      void qc.invalidateQueries({ queryKey: ['newsroom', 'newsletters'] });
    },
  });
  if (lists.isPending) return <Loader />;
  if (lists.isError) return <Alert color="red">{errorText(lists.error)}</Alert>;
  const newsletter = lists.data.results.find((n) => n.id === chosen) ?? lists.data.results[0];
  return (
    <Stack>
      <Group align="flex-end">
        <Select
          label="Newsletter"
          data={lists.data.results.map((n) => ({ value: n.id, label: n.name }))}
          value={newsletter?.id ?? null}
          onChange={setChosen}
          w={260}
        />
        <TextInput label="New newsletter" value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Button variant="default" disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}>
          Add the newsletter
        </Button>
      </Group>
      {create.error ? <Alert color="red">{errorText(create.error)}</Alert> : null}
      {newsletter ? <Issues key={newsletter.id} newsletter={newsletter} siteId={siteId} /> : <Text c="dimmed">No newsletters yet.</Text>}
    </Stack>
  );
}

function Issues({ newsletter, siteId }: { newsletter: Newsletter; siteId: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const [open, setOpen] = useState<string | null>(null);
  const [subject, setSubject] = useState('');
  const [intro, setIntro] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const picker = usePublishedPicker(siteId);
  const issues = useQuery({
    queryKey: ['newsroom', 'issues', newsletter.id],
    queryFn: () => call(api.GET('/api/v2/newsroom/issues/', { params: { query: { newsletter: newsletter.id, page_size: 100 } } })),
  });
  const compose = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/newsroom/issues/', { body: { newsletter: newsletter.id, subject, intro, story_ids: picked } })),
    onSuccess: (issue) => {
      setSubject('');
      setIntro('');
      setPicked([]);
      setOpen(issue.id);
      void qc.invalidateQueries({ queryKey: ['newsroom', 'issues'] });
    },
  });
  const counts = newsletter.subscribers;
  const current = issues.data?.results.find((i) => i.id === open);
  return (
    <Stack>
      <Group gap="xs">
        <Badge color="green" variant="light">
          {counts.confirmed} confirmed
        </Badge>
        <Badge color="gray" variant="light">
          {counts.pending} waiting to confirm
        </Badge>
        <Badge color="red" variant="light">
          {counts.unsubscribed} unsubscribed
        </Badge>
      </Group>
      <Card withBorder>
        <Stack gap="xs">
          <Title order={4}>Compose an issue</Title>
          <TextInput label="Subject" value={subject} onChange={(e) => setSubject(e.currentTarget.value)} />
          <Textarea label="Introduction" autosize minRows={2} value={intro} onChange={(e) => setIntro(e.currentTarget.value)} />
          <MultiSelect label="Stories, in order" {...picker} value={picked} onChange={setPicked} />
          {compose.error ? <Alert color="red">{errorText(compose.error)}</Alert> : null}
          <Button w="fit-content" disabled={!subject.trim()} loading={compose.isPending} onClick={() => compose.mutate()}>
            Save the issue
          </Button>
        </Stack>
      </Card>
      <Title order={4}>Issues</Title>
      {(issues.data?.results ?? []).map((issue) => (
        <Group key={issue.id} gap="xs">
          <Button variant={issue.id === open ? 'light' : 'subtle'} size="compact-sm" onClick={() => setOpen(issue.id)}>
            {issue.subject}
          </Button>
          <Badge color={COLOR[issue.status]} variant="light">
            {issue.status}
          </Badge>
          <Text size="xs" c="dimmed">
            {issue.status === 'sent' ? `to ${issue.recipients} on ${when(issue.sent_at)}` : `${issue.stories.length} stories`}
          </Text>
        </Group>
      ))}
      {current ? <IssueView key={`${current.id}:${current.updated_at}`} issue={current} confirmed={counts.confirmed} /> : null}
    </Stack>
  );
}

function IssueView({ issue, confirmed }: { issue: Issue; confirmed: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const path = { params: { path: { public_id: issue.id } } };
  const preview = useQuery({
    queryKey: ['newsroom', 'issue-preview', issue.id, issue.updated_at],
    queryFn: () => call(api.GET('/api/v2/newsroom/issues/{public_id}/preview/', path)),
  });
  const send = useMutation({
    mutationFn: () => call(api.POST('/api/v2/newsroom/issues/{public_id}/send/', path)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['newsroom', 'issues'] }),
  });
  const sendable = issue.status === 'draft' || issue.status === 'failed' || issue.status === 'sending';
  return (
    <Card withBorder aria-label="Issue preview">
      <Stack gap="xs">
        <Title order={4}>{issue.subject}</Title>
        {issue.error ? <Alert color="red">{issue.error}</Alert> : null}
        {issue.stories.map((s) => (
          <Text key={s.id} size="sm">
            <b>{s.headline}</b> {s.status === 'published' || s.status === 'updated' || s.status === 'corrected' ? '' : `(${s.status} — not published yet)`}
          </Text>
        ))}
        <Text size="sm" fw={500}>
          As it is sent (the text part):
        </Text>
        {preview.isPending ? <Loader size="sm" /> : preview.isError ? <Alert color="red">{errorText(preview.error)}</Alert> : <Code block>{preview.data.text}</Code>}
        {send.error ? <Alert color="red">{errorText(send.error)}</Alert> : null}
        {issue.status === 'sending' ? (
          <Text size="sm" c="dimmed">
            Being sent. If it has stopped part way, resume it: nobody gets it twice.
          </Text>
        ) : null}
        {sendable ? (
          <Button w="fit-content" color="green" variant={issue.status === 'sending' ? 'light' : 'filled'} loading={send.isPending} onClick={() => send.mutate()}>
            {issue.status === 'draft'
              ? `Send to ${confirmed} confirmed subscriber${confirmed === 1 ? '' : 's'}`
              : issue.status === 'failed'
                ? 'Send it again to those who have not had it'
                : 'Resume sending, if it has stopped'}
          </Button>
        ) : null}
      </Stack>
    </Card>
  );
}
