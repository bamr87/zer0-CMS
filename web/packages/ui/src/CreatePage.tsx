// Create: a new page of a type its parent allows, as a draft — optionally
// with a brief (topic, audience, notes), and optionally handed to the drafter
// agent, whose first draft comes back as suggestions to review rather than
// as an edit (the agent only proposes).
import { Alert, Button, Checkbox, Group, Loader, Select, Stack, Textarea, TextInput } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from './call';
import { useApi, useGo, type Destination } from './context';

export function CreatePage({ siteId }: { siteId?: number }) {
  const api = useApi();
  const go = useGo();
  const [parent, setParent] = useState<string | null>(null);
  const [type, setType] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [brief, setBrief] = useState({ topic: '', audience: '', notes: '' });
  const [draft, setDraft] = useState(false);
  const parentQuery = { site: siteId, can_have_children: true, ordering: 'path', page_size: 100 };
  const parents = useQuery({
    queryKey: ['pages', parentQuery],
    queryFn: () => call(api.GET('/api/v2/content/pages/', { params: { query: parentQuery } })),
  });
  const parentId = Number(parent ?? parents.data?.results[0]?.id ?? 0) || null;
  const types = useQuery({
    queryKey: ['types', parentId],
    enabled: parentId !== null,
    queryFn: () => call(api.GET('/api/v2/content/pages/{id}/types/', { params: { path: { id: parentId ?? 0 } } })),
  });
  const chosenType = type ?? (types.data?.length === 1 ? (types.data[0]?.type ?? null) : null);
  // The drafter writes from the brief: no topic, no run — whatever the box said before the topic was cleared.
  const drafting = draft && brief.topic.trim() !== '';
  const create = useMutation({
    mutationFn: async (): Promise<Destination> => {
      const body = brief.topic ? [{ type: 'brief', value: brief }] : [];
      const page = await call(
        api.POST('/api/v2/content/pages/', { body: { parent: parentId ?? 0, type: chosenType ?? '', fields: { title }, body } }),
      );
      if (!drafting) return { to: 'page', id: page.id };
      const run = await call(api.POST('/api/v2/agent-runs/', { body: { agent: 'drafter', page_id: page.id } }));
      return { to: 'run', id: run.id };
    },
    onSuccess: (to) => go(to),
  });

  if (parents.isPending) return <Loader />;
  if (parents.isError) return <Alert color="red">{errorText(parents.error)}</Alert>;

  return (
    <Stack maw={640}>
      <Select
        label="Where"
        description="The section or page the new page goes under"
        data={parents.data.results.map((p) => ({ value: String(p.id), label: `${p.title} (${p.type_label})` }))}
        value={parentId ? String(parentId) : null}
        allowDeselect={false}
        onChange={(value) => {
          setParent(value);
          setType(null);
        }}
      />
      <Select
        label="Type"
        data={(types.data ?? []).map((t) => ({ value: t.type, label: t.label }))}
        value={chosenType}
        allowDeselect={false}
        disabled={!types.data?.length}
        placeholder={types.data && !types.data.length ? 'Nothing can be created here' : 'Pick a type'}
        onChange={setType}
      />
      <TextInput label="Title" required value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
      <TextInput
        label="Brief: what is it about?"
        description="Optional. The drafter writes from the brief."
        value={brief.topic}
        onChange={(e) => setBrief({ ...brief, topic: e.currentTarget.value })}
      />
      {brief.topic ? (
        <>
          <TextInput label="Who is it for?" value={brief.audience} onChange={(e) => setBrief({ ...brief, audience: e.currentTarget.value })} />
          <Textarea label="Notes" autosize value={brief.notes} onChange={(e) => setBrief({ ...brief, notes: e.currentTarget.value })} />
          <Checkbox
            label="Draft with the drafter agent (its draft arrives as suggestions to review)"
            checked={draft}
            onChange={(e) => setDraft(e.currentTarget.checked)}
          />
        </>
      ) : null}
      {create.isError ? <Alert color="red">{errorText(create.error)}</Alert> : null}
      <Group>
        <Button disabled={!title.trim() || !chosenType || !parentId} loading={create.isPending} onClick={() => create.mutate()}>
          {drafting ? 'Create and draft' : 'Create draft'}
        </Button>
      </Group>
    </Stack>
  );
}
