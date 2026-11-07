// The editor: a page's latest revision — blocks, fields, SEO, settings and,
// for a page that is a file of its site, that file (its path and its raw front
// matter: the File tab) — with its suggestions and revisions beside it. Save writes a draft revision and
// sends only what changed plus the revision it was edited from, so a save
// over someone else's newer one is refused (409) rather than replacing it.
// Publish, schedule (a time to go live, a time to come down, or both) and
// unpublish save first when there are unsaved edits; nothing reaches the live
// site except through those buttons. A page a Wagtail lock keeps from this
// person (`page.lock`: someone else's, a workflow's, a schedule's) opens
// read-only and says why; cancelling a schedule is the one thing it allows.
// The AI panel opens beside the editor: an assistant or a pipeline run on the
// page, whose answer arrives in the Suggestions tab (ai/AiPanel.tsx). The
// Citability tab scores the page with AIEO and lands an optimize or scrub
// rewrite there as suggestions too (aieo/PageScore.tsx).
// Distribute drafts a post of the live page for one of its site's channels
// (distribution/Compose.tsx); a person approves it in the queue.
// Unsaved edits are never thrown away behind a person's back (#64): the draft
// keeps the revision it was edited from as its baseline. A newer revision
// (someone else's save, an accepted suggestion, a pipeline) replaces a clean
// draft at once; over a dirty one it raises a notice to keep the edits (a
// save is then refused, 409) or discard them and load the latest. While the
// draft is dirty the browser asks before leaving, and the host is told
// (useSetDirty) so it can ask before navigating away.
import { Alert, Anchor, Badge, Button, Grid, Group, Loader, Paper, Popover, Stack, Tabs, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Block, PageDetail } from '@zer0/api';
import { useEffect, useState } from 'react';

import { AiPanel } from './ai/AiPanel';
import { PageScore } from './aieo/PageScore';
import { BodyEditor } from './BodyEditor';
import { call, errorText } from './call';
import { useApi, useSetDirty } from './context';
import { Distribute } from './distribution/Compose';
import { FieldsPanel, fromLocalInput, type FieldValues } from './FieldsPanel';
import { PageResearch } from './research/PageResearch';
import { RevisionHistory } from './RevisionHistory';
import { StatusBadge } from './StatusBadge';
import { SuggestionInbox } from './SuggestionInbox';

export type PageAction = 'save' | 'publish' | 'unpublish' | 'schedule' | 'unschedule';

interface Changes {
  base_revision_id: number | null;
  fields: FieldValues;
  body?: Block[];
}

interface Schedule {
  go_live_at: string | null;
  expire_at: string | null;
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const DONE: Record<PageAction, string> = {
  save: 'Draft saved',
  publish: 'Published',
  unpublish: 'Unpublished',
  schedule: 'Scheduled',
  unschedule: 'Schedule cancelled',
};

export function PageEditor({ pageId, tab }: { pageId: number; tab?: 'suggestions' }) {
  const api = useApi();
  const qc = useQueryClient();
  const path = { path: { id: pageId } };
  const page = useQuery({
    queryKey: ['page', pageId],
    queryFn: () => call(api.GET('/api/v2/content/pages/{id}/', { params: path })),
  });
  // The revision this editor's own last action made: the draft takes it as its new baseline.
  const [own, setOwn] = useState<number | null>(null);
  const act = useMutation({
    mutationFn: async ({ action, changes, at }: { action: PageAction; changes: Changes | null; at?: Schedule }) => {
      let saved: PageDetail | undefined;
      if (changes) saved = await call(api.PATCH('/api/v2/content/pages/{id}/', { params: path, body: changes }));
      switch (action) {
        case 'save':
          return saved ?? call(api.GET('/api/v2/content/pages/{id}/', { params: path }));
        case 'publish':
          return call(api.POST('/api/v2/content/pages/{id}/publish/', { params: path }));
        case 'unpublish':
          return call(api.POST('/api/v2/content/pages/{id}/unpublish/', { params: path }));
        case 'unschedule':
          return call(api.POST('/api/v2/content/pages/{id}/unschedule/', { params: path }));
        case 'schedule':
          return call(api.POST('/api/v2/content/pages/{id}/schedule/', { params: path, body: at }));
      }
    },
    onSuccess: (data, { action }) => {
      setOwn(data.latest_revision?.id ?? null);
      qc.setQueryData(['page', pageId], data);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'page' });
      notifications.show({ message: DONE[action] });
    },
  });

  if (page.isPending) return <Loader />;
  if (page.isError) return <Alert color="red">{errorText(page.error)}</Alert>;
  return (
    <Draft
      page={page.data}
      own={own}
      tab={tab}
      busy={act.isPending}
      failure={act.isError ? errorText(act.error) : null}
      run={(action, changes, at) => act.mutate({ action, changes, at })}
    />
  );
}

interface DraftProps {
  page: PageDetail;
  /** The revision this editor's own last action made, or null. */
  own: number | null;
  tab?: string;
  busy: boolean;
  failure: string | null;
  run: (action: PageAction, changes: Changes | null, at?: Schedule) => void;
}

function Draft({ page, own, tab: firstTab, busy, failure, run }: DraftProps) {
  // The page as it was when these edits began: what they are compared with and saved against.
  const [base, setBase] = useState<PageDetail>(page);
  const [fields, setFields] = useState<FieldValues>(page.fields);
  const [body, setBody] = useState<Block[]>(page.body);
  // Bumped on every re-baseline, so the editors drop any state of their own.
  const [generation, setGeneration] = useState(0);
  // The newer revision the person chose to keep their edits over.
  const [kept, setKept] = useState<number | null>(null);
  const [goLive, setGoLive] = useState('');
  const [comeDown, setComeDown] = useState('');
  const [tab, setTab] = useState<string | null>(firstTab ?? 'content');
  const [askingAi, setAskingAi] = useState(false);
  const changed = Object.fromEntries(Object.entries(fields).filter(([name, value]) => !same(value, base.fields[name])));
  const bodyChanged = !same(body, base.body);
  const dirty = Object.keys(changed).length > 0 || bodyChanged;
  const changes: Changes | null = dirty
    ? { base_revision_id: base.latest_revision?.id ?? null, fields: changed, ...(bodyChanged ? { body } : {}) }
    : null;

  const latest = page.latest_revision?.id ?? null;
  const moved = latest !== (base.latest_revision?.id ?? null);
  const loadLatest = () => {
    setBase(page);
    setFields(page.fields);
    setBody(page.body);
    setKept(null);
    setGeneration((n) => n + 1);
  };
  // A newer revision replaces a clean draft, or one this editor just saved; never other edits.
  if (moved && (!dirty || latest === own)) loadLatest();
  const conflict = moved && dirty && latest !== own && kept !== latest;

  const setDirty = useSetDirty();
  useEffect(() => setDirty?.(dirty), [setDirty, dirty]);
  useEffect(() => () => setDirty?.(false), [setDirty]);
  useEffect(() => {
    if (!dirty) return;
    const ask = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', ask);
    return () => window.removeEventListener('beforeunload', ask);
  }, [dirty]);
  const can = page.permissions;
  const editable = can.edit && !page.lock;
  const hasFile = page.field_specs.some((spec) => spec.group === 'file');
  const setField = (name: string, value: unknown) => setFields((current) => ({ ...current, [name]: value }));
  // Accepting a suggestion or reverting makes a new revision, which would replace these edits.
  const hold = page.lock ?? (dirty ? 'You have unsaved edits: save them before accepting a suggestion or reverting.' : undefined);

  return (
    <Stack>
      <Group justify="space-between" align="start">
        <Stack gap={2}>
          <Group gap="xs">
            <Title order={2}>{String(fields.title ?? page.title)}</Title>
            <StatusBadge status={page.status} />
            {dirty ? <Badge color="orange" variant="dot">unsaved</Badge> : null}
          </Group>
          <Text size="sm" c="dimmed">
            {page.type_label} · {page.url_path}
            {page.parent ? ` · in ${page.parent.title}` : ''}
          </Text>
        </Stack>
        <Group gap="xs">
          <Button variant={askingAi ? 'filled' : 'light'} aria-expanded={askingAi} aria-controls="zer0-ai-panel" onClick={() => setAskingAi((open) => !open)}>
            AI
          </Button>
          <Anchor href={page.preview_url} target="_blank" rel="noreferrer" size="sm">
            Preview
          </Anchor>
          <Distribute pageId={page.id} siteId={page.site_id ?? undefined} disabled={!page.live} />
          <Button variant="default" disabled={!dirty || !editable} loading={busy} onClick={() => run('save', changes)}>
            Save draft
          </Button>
          {can.publish ? (
            <>
              <Button disabled={!!page.lock} loading={busy} onClick={() => run('publish', changes)}>
                Publish
              </Button>
              <Popover position="bottom-end" withArrow>
                <Popover.Target>
                  <Button variant="light" disabled={busy || !!page.lock}>
                    Schedule…
                  </Button>
                </Popover.Target>
                <Popover.Dropdown>
                  <Stack gap="xs">
                    <TextInput
                      label="Publish at"
                      description="Leave it empty to publish now"
                      type="datetime-local"
                      value={goLive}
                      onChange={(e) => setGoLive(e.currentTarget.value)}
                    />
                    <TextInput
                      label="Take down at"
                      description="Optional"
                      type="datetime-local"
                      value={comeDown}
                      onChange={(e) => setComeDown(e.currentTarget.value)}
                    />
                    <Button
                      size="xs"
                      disabled={!goLive && !comeDown}
                      onClick={() => run('schedule', changes, { go_live_at: fromLocalInput(goLive), expire_at: fromLocalInput(comeDown) })}
                    >
                      Schedule
                    </Button>
                  </Stack>
                </Popover.Dropdown>
              </Popover>
            </>
          ) : null}
          {page.status === 'scheduled' && can.publish ? (
            <Button variant="subtle" disabled={busy} onClick={() => run('unschedule', null)}>
              Cancel schedule
            </Button>
          ) : null}
          {page.live && can.unpublish ? (
            <Button variant="subtle" color="red" disabled={busy} onClick={() => run('unpublish', null)}>
              Unpublish
            </Button>
          ) : null}
        </Group>
      </Group>
      {page.lock ? (
        <Alert color="gray" title="Locked">
          {page.lock}
        </Alert>
      ) : null}
      {page.go_live_at && page.status === 'scheduled' ? (
        <Alert color="blue">Goes live {new Date(page.go_live_at).toLocaleString()}.</Alert>
      ) : null}
      {page.expire_at && (page.live || page.status === 'scheduled') ? (
        <Alert color="blue">Comes down {new Date(page.expire_at).toLocaleString()}.</Alert>
      ) : null}
      {conflict ? (
        <Alert color="orange" title="This page changed while you were editing">
          <Stack gap="xs">
            <Text size="sm">
              Someone saved a newer revision. Your edits are still here, but saving them over it will be refused until you load the latest.
            </Text>
            <Group gap="xs">
              <Button size="xs" variant="default" onClick={() => setKept(latest)}>
                Keep my edits
              </Button>
              <Button size="xs" color="red" variant="light" onClick={loadLatest}>
                Discard and load latest
              </Button>
            </Group>
          </Stack>
        </Alert>
      ) : null}
      {failure ? <Alert color="red">{failure}</Alert> : null}
      <Grid>
        <Grid.Col span={{ base: 12, md: askingAi ? 8 : 12 }}>
          <Tabs value={tab} onChange={setTab} keepMounted={false}>
            <Tabs.List>
              <Tabs.Tab value="content">Content</Tabs.Tab>
              <Tabs.Tab value="seo">SEO</Tabs.Tab>
              {hasFile ? <Tabs.Tab value="file">File</Tabs.Tab> : null}
              <Tabs.Tab value="settings">Settings</Tabs.Tab>
              <Tabs.Tab value="suggestions">Suggestions ({page.pending_suggestions})</Tabs.Tab>
              <Tabs.Tab value="revisions">Revisions</Tabs.Tab>
              <Tabs.Tab value="research">Research</Tabs.Tab>
              <Tabs.Tab value="citability">Citability</Tabs.Tab>
            </Tabs.List>
            <Tabs.Panel value="content" pt="md">
              <Stack key={generation}>
                <FieldsPanel specs={page.field_specs} values={fields} group="content" disabled={!editable} onChange={setField} />
                <BodyEditor blocks={body} onChange={setBody} disabled={!editable} />
              </Stack>
            </Tabs.Panel>
            <Tabs.Panel value="seo" pt="md">
              <FieldsPanel key={generation} specs={page.field_specs} values={fields} group="seo" disabled={!editable} onChange={setField} />
            </Tabs.Panel>
            {hasFile ? (
              <Tabs.Panel value="file" pt="md">
                <FieldsPanel key={generation} specs={page.field_specs} values={fields} group="file" disabled={!editable} onChange={setField} />
              </Tabs.Panel>
            ) : null}
            <Tabs.Panel value="settings" pt="md">
              <FieldsPanel key={generation} specs={page.field_specs} values={fields} group="settings" disabled={!editable} onChange={setField} />
            </Tabs.Panel>
            <Tabs.Panel value="suggestions" pt="md">
              <SuggestionInbox pageId={page.id} holdAccept={hold} />
            </Tabs.Panel>
            <Tabs.Panel value="revisions" pt="md">
              {hold ? (
                <Alert color="yellow" mb="sm">
                  {hold}
                </Alert>
              ) : null}
              <RevisionHistory pageId={page.id} canEdit={editable && !dirty} />
            </Tabs.Panel>
            <Tabs.Panel value="research" pt="md">
              <PageResearch pageId={page.id} pageTitle={page.title} />
            </Tabs.Panel>
            <Tabs.Panel value="citability" pt="md">
              <PageScore pageId={page.id} dirty={dirty} held={editable ? null : (page.lock ?? 'You cannot change this page.')} onReview={() => setTab('suggestions')} />
            </Tabs.Panel>
          </Tabs>
        </Grid.Col>
        {askingAi ? (
          <Grid.Col span={{ base: 12, md: 4 }}>
            <Paper withBorder p="md" component="aside" id="zer0-ai-panel" aria-label="AI panel">
              <AiPanel page={page} dirty={dirty} held={editable ? null : (page.lock ?? 'You cannot change this page.')} onReview={() => setTab('suggestions')} />
            </Paper>
          </Grid.Col>
        ) : null}
      </Grid>
    </Stack>
  );
}
