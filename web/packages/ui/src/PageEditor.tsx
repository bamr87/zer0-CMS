// The editor: a page's latest revision — blocks, fields, SEO, settings — with
// its suggestions and revisions beside it. Save writes a draft revision and
// sends only what changed plus the revision it was edited from, so a save
// over someone else's newer one is refused (409) rather than replacing it.
// Publish, schedule and unpublish save first when there are unsaved edits;
// nothing reaches the live site except through those buttons.
import { Alert, Anchor, Badge, Button, Group, Loader, Popover, Stack, Tabs, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Block, PageDetail } from '@zer0/api';
import { useState } from 'react';

import { BodyEditor } from './BodyEditor';
import { call, errorText } from './call';
import { useApi } from './context';
import { FieldsPanel, fromLocalInput, type FieldValues } from './FieldsPanel';
import { RevisionHistory } from './RevisionHistory';
import { StatusBadge } from './StatusBadge';
import { SuggestionInbox } from './SuggestionInbox';

export type PageAction = 'save' | 'publish' | 'unpublish' | 'schedule' | 'unschedule';

interface Changes {
  base_revision_id: number | null;
  fields: FieldValues;
  body?: Block[];
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const DONE: Record<PageAction, string> = {
  save: 'Draft saved',
  publish: 'Published',
  unpublish: 'Unpublished',
  schedule: 'Scheduled',
  unschedule: 'Schedule cancelled',
};

export function PageEditor({ pageId }: { pageId: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const path = { path: { id: pageId } };
  const page = useQuery({
    queryKey: ['page', pageId],
    queryFn: () => call(api.GET('/api/v2/content/pages/{id}/', { params: path })),
  });
  const act = useMutation({
    mutationFn: async ({ action, changes, at }: { action: PageAction; changes: Changes | null; at?: string }) => {
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
          return call(api.POST('/api/v2/content/pages/{id}/schedule/', { params: path, body: { go_live_at: at ?? '' } }));
      }
    },
    onSuccess: (data, { action }) => {
      qc.setQueryData(['page', pageId], data);
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'page' });
      notifications.show({ message: DONE[action] });
    },
  });

  if (page.isPending) return <Loader />;
  if (page.isError) return <Alert color="red">{errorText(page.error)}</Alert>;
  return (
    <Draft
      key={page.data.latest_revision?.id ?? 'none'}
      page={page.data}
      busy={act.isPending}
      failure={act.isError ? errorText(act.error) : null}
      run={(action, changes, at) => act.mutate({ action, changes, at })}
    />
  );
}

interface DraftProps {
  page: PageDetail;
  busy: boolean;
  failure: string | null;
  run: (action: PageAction, changes: Changes | null, at?: string) => void;
}

function Draft({ page, busy, failure, run }: DraftProps) {
  const [fields, setFields] = useState<FieldValues>(page.fields);
  const [body, setBody] = useState<Block[]>(page.body);
  const [when, setWhen] = useState('');
  const changed = Object.fromEntries(Object.entries(fields).filter(([name, value]) => !same(value, page.fields[name])));
  const bodyChanged = !same(body, page.body);
  const dirty = Object.keys(changed).length > 0 || bodyChanged;
  const changes: Changes | null = dirty
    ? { base_revision_id: page.latest_revision?.id ?? null, fields: changed, ...(bodyChanged ? { body } : {}) }
    : null;
  const can = page.permissions;
  const setField = (name: string, value: unknown) => setFields((current) => ({ ...current, [name]: value }));
  // Accepting a suggestion or reverting makes a new revision, which would replace these edits.
  const hold = dirty ? 'You have unsaved edits: save them before accepting a suggestion or reverting.' : undefined;

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
          <Anchor href={page.preview_url} target="_blank" rel="noreferrer" size="sm">
            Preview
          </Anchor>
          <Button variant="default" disabled={!dirty || !can.edit} loading={busy} onClick={() => run('save', changes)}>
            Save draft
          </Button>
          {can.publish ? (
            <>
              <Button loading={busy} onClick={() => run('publish', changes)}>
                Publish
              </Button>
              <Popover position="bottom-end" withArrow>
                <Popover.Target>
                  <Button variant="light" disabled={busy}>
                    Schedule…
                  </Button>
                </Popover.Target>
                <Popover.Dropdown>
                  <Stack gap="xs">
                    <TextInput label="Publish at" type="datetime-local" value={when} onChange={(e) => setWhen(e.currentTarget.value)} />
                    <Button size="xs" disabled={!when} onClick={() => run('schedule', changes, fromLocalInput(when) ?? '')}>
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
      {page.go_live_at && page.status === 'scheduled' ? (
        <Alert color="blue">Goes live {new Date(page.go_live_at).toLocaleString()}.</Alert>
      ) : null}
      {failure ? <Alert color="red">{failure}</Alert> : null}
      <Tabs defaultValue="content" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="content">Content</Tabs.Tab>
          <Tabs.Tab value="seo">SEO</Tabs.Tab>
          <Tabs.Tab value="settings">Settings</Tabs.Tab>
          <Tabs.Tab value="suggestions">Suggestions ({page.pending_suggestions})</Tabs.Tab>
          <Tabs.Tab value="revisions">Revisions</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="content" pt="md">
          <Stack>
            <FieldsPanel specs={page.field_specs} values={fields} group="content" disabled={!can.edit} onChange={setField} />
            <BodyEditor blocks={body} onChange={setBody} disabled={!can.edit} />
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="seo" pt="md">
          <FieldsPanel specs={page.field_specs} values={fields} group="seo" disabled={!can.edit} onChange={setField} />
        </Tabs.Panel>
        <Tabs.Panel value="settings" pt="md">
          <FieldsPanel specs={page.field_specs} values={fields} group="settings" disabled={!can.edit} onChange={setField} />
        </Tabs.Panel>
        <Tabs.Panel value="suggestions" pt="md">
          <SuggestionInbox targetId={page.id} holdAccept={hold} />
        </Tabs.Panel>
        <Tabs.Panel value="revisions" pt="md">
          {hold ? (
            <Alert color="yellow" mb="sm">
              {hold}
            </Alert>
          ) : null}
          <RevisionHistory pageId={page.id} canEdit={can.edit && !dirty} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
