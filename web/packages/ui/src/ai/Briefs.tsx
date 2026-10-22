// Briefs (Create): a request to create — a prompt, or a text to use as it
// is; the site and where the draft goes (a parent page and a page type); who
// writes it (an assistant or a pipeline) and its shape (an output schema).
// Generating it is a run, followed live; then a person reviews the structured
// result, its rendered Markdown and the metadata, and applies it: a draft page
// opens in the editor with the brief's text waiting as suggestions to accept.
// Nothing here publishes.
import { Alert, Badge, Button, Card, Group, Loader, SegmentedControl, Select, SimpleGrid, Stack, Table, Text, Textarea, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Brief, BriefStatus, Visibility } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import {
  ALL,
  fieldError,
  isRecord,
  JsonView,
  MarkdownView,
  options,
  OwnerFields,
  ReadOnlyNote,
  Rows,
  RunProgress,
  useAssistants,
  usePipelines,
  useSchemas,
  type Ownership,
} from './shared';

const STATUS_COLOR: Record<BriefStatus, string> = { draft: 'gray', generating: 'blue', ready: 'teal', applied: 'grape', failed: 'red' };

export function BriefStatusBadge({ status }: { status: BriefStatus }) {
  return (
    <Badge color={STATUS_COLOR[status]} variant="light">
      {status}
    </Badge>
  );
}

const nameOf = (brief: Brief) => brief.title || brief.prompt?.slice(0, 80) || brief.source_text?.slice(0, 80) || 'Untitled brief';

export function BriefList({ siteId }: { siteId?: number }) {
  const api = useApi();
  const go = useGo();
  const query = { ...ALL, ordering: '-updated_at', ...(siteId ? { site: siteId } : {}) };
  const briefs = useQuery({ queryKey: ['ai', 'briefs', query], queryFn: () => call(api.GET('/api/v2/ai/briefs/', { params: { query } })) });
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Ask an assistant or a pipeline for a draft, review what it wrote, and apply it as a page with suggestions.
        </Text>
        <Button onClick={() => go({ to: 'brief' })}>New brief</Button>
      </Group>
      <Rows
        label="Briefs"
        query={briefs}
        name={nameOf}
        onOpen={(b) => go({ to: 'brief', id: b.id })}
        columns={[
          { title: 'Status', cell: (b) => <BriefStatusBadge status={b.status} /> },
          { title: 'Updated', cell: (b) => new Date(b.updated_at).toLocaleString() },
          { title: 'Owner', cell: (b) => b.owner ?? '—' },
        ]}
        empty={{ title: 'No briefs yet', description: 'Write a brief and let an assistant draft it.', action: <Button onClick={() => go({ to: 'brief' })}>New brief</Button> }}
      />
    </Stack>
  );
}

/** One brief — written, generated, reviewed and applied — or a new one (no id). */
export function BriefWorkspace({ id, siteId }: { id?: string; siteId?: number }) {
  const api = useApi();
  const brief = useQuery({
    queryKey: ['ai', 'brief', id],
    enabled: id !== undefined,
    queryFn: () => call(api.GET('/api/v2/ai/briefs/{public_id}/', { params: { path: { public_id: id ?? '' } } })),
  });
  if (!id) return <BriefForm siteId={siteId} />;
  if (brief.isPending) return <Loader aria-label="Loading the brief" />;
  if (brief.isError) return <Alert color="red">{errorText(brief.error)}</Alert>;
  return <BriefView brief={brief.data} />;
}

interface Draft extends Ownership {
  title: string;
  mode: 'prompt' | 'text';
  prompt: string;
  source_text: string;
  writer: 'assistant' | 'pipeline';
  assistant: string | null;
  pipeline: string | null;
  output_schema: string | null;
  parent: number | null;
  page_type: string;
}

function draftOf(brief: Brief | undefined, siteId: number | undefined): Draft {
  return {
    title: brief?.title ?? '',
    mode: brief?.source_text && !brief.prompt ? 'text' : 'prompt',
    prompt: brief?.prompt ?? '',
    source_text: brief?.source_text ?? '',
    writer: brief?.pipeline ? 'pipeline' : 'assistant',
    assistant: brief?.assistant ?? null,
    pipeline: brief?.pipeline ?? null,
    output_schema: brief?.output_schema ?? null,
    parent: brief?.parent ?? null,
    page_type: brief?.page_type ?? 'cms.ArticlePage',
    visibility: (brief?.visibility ?? 'private') as Visibility,
    site: brief?.site ?? siteId ?? null,
  };
}

function bodyOf(d: Draft) {
  return {
    title: d.title,
    prompt: d.mode === 'prompt' ? d.prompt : '',
    source_text: d.mode === 'text' ? d.source_text : '',
    assistant: d.writer === 'assistant' ? d.assistant : null,
    pipeline: d.writer === 'pipeline' ? d.pipeline : null,
    output_schema: d.output_schema,
    parent: d.parent,
    page_type: d.page_type,
    visibility: d.visibility,
    site: d.site,
  };
}

/** Where a draft goes: a page in the site that can have children, and a type it allows. */
function PlaceFields({ site, parent, type, onChange, error, disabled }: { site: number | null; parent: number | null; type: string; onChange: (next: { parent: number | null; page_type: string }) => void; error?: unknown; disabled?: boolean }) {
  const api = useApi();
  const query = { ...(site ? { site } : {}), can_have_children: true, ordering: 'path', page_size: 100 };
  const parents = useQuery({ queryKey: ['pages', query], queryFn: () => call(api.GET('/api/v2/content/pages/', { params: { query } })) });
  const types = useQuery({
    queryKey: ['types', parent],
    enabled: parent !== null,
    queryFn: () => call(api.GET('/api/v2/content/pages/{id}/types/', { params: { path: { id: parent ?? 0 } } })),
  });
  return (
    <Group grow align="start">
      <Select
        label="Where the draft goes"
        placeholder={parents.isPending ? 'Loading pages…' : "The site's home"}
        data={(parents.data?.results ?? []).map((p) => ({ value: String(p.id), label: `${p.title} (${p.type_label})` }))}
        value={parent ? String(parent) : null}
        clearable
        searchable
        disabled={disabled}
        error={fieldError(error, 'parent')}
        onChange={(next) => onChange({ parent: Number(next) || null, page_type: type })}
      />
      <Select
        label="Page type"
        data={types.data?.length ? types.data.map((t) => ({ value: t.type, label: t.label })) : [{ value: type, label: type }]}
        value={type}
        allowDeselect={false}
        disabled={disabled}
        error={fieldError(error, 'page_type')}
        onChange={(next) => onChange({ parent, page_type: next ?? type })}
      />
    </Group>
  );
}

function BriefForm({ brief, siteId, onSaved }: { brief?: Brief; siteId?: number; onSaved?: () => void }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const assistants = useAssistants();
  const pipelines = usePipelines();
  const schemas = useSchemas();
  const [draft, setDraft] = useState(() => draftOf(brief, siteId));
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const save = useMutation({
    mutationFn: async ({ generate }: { generate: boolean }) => {
      const saved = brief
        ? await call(api.PATCH('/api/v2/ai/briefs/{public_id}/', { params: { path: { public_id: brief.id } }, body: bodyOf(draft) }))
        : await call(api.POST('/api/v2/ai/briefs/', { body: bodyOf(draft) }));
      if (generate) await call(api.POST('/api/v2/ai/briefs/{public_id}/generate/', { params: { path: { public_id: saved.id } } }));
      return saved;
    },
    onSuccess: (saved, { generate }) => {
      notifications.show({ message: generate ? 'Generating the brief' : 'Brief saved' });
      void qc.invalidateQueries({ queryKey: ['ai'] });
      onSaved?.();
      if (!brief) go({ to: 'brief', id: saved.id });
    },
  });
  const error = save.error;
  const text = draft.mode === 'prompt' ? draft.prompt : draft.source_text;
  const writer = draft.writer === 'assistant' ? draft.assistant : draft.pipeline;
  const ready = text.trim() !== '' && (draft.mode === 'text' || writer !== null);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate({ generate: true });
      }}
    >
      <Stack maw={760}>
        {brief ? null : <Title order={3}>New brief</Title>}
        <TextInput label="Title" description="Optional: the metadata step proposes one." value={draft.title} onChange={(e) => set('title', e.currentTarget.value)} error={fieldError(error, 'title')} />
        <SegmentedControl
          aria-label="What the brief starts from"
          value={draft.mode}
          onChange={(mode) => set('mode', mode === 'text' ? 'text' : 'prompt')}
          data={[
            { value: 'prompt', label: 'Write from a prompt' },
            { value: 'text', label: 'Use my text as it is' },
          ]}
        />
        {draft.mode === 'prompt' ? (
          <Textarea label="Prompt" description="What to write: the topic, the angle, the audience, what to include." autosize minRows={4} value={draft.prompt} onChange={(e) => set('prompt', e.currentTarget.value)} error={fieldError(error, 'prompt')} />
        ) : (
          <Textarea label="Text" description="Used as it is; the platform only extracts its title, description and keywords." autosize minRows={6} value={draft.source_text} onChange={(e) => set('source_text', e.currentTarget.value)} error={fieldError(error, 'source_text')} />
        )}
        <Group align="end" grow>
          <SegmentedControl
            aria-label="Who writes it"
            value={draft.writer}
            onChange={(writerKind) => set('writer', writerKind === 'pipeline' ? 'pipeline' : 'assistant')}
            data={[
              { value: 'assistant', label: 'An assistant' },
              { value: 'pipeline', label: 'A pipeline' },
            ]}
          />
          {draft.writer === 'assistant' ? (
            <Select label="Assistant" placeholder="Choose one" data={options(assistants.data?.results)} value={draft.assistant} searchable onChange={(next) => set('assistant', next)} error={fieldError(error, 'assistant')} />
          ) : (
            <Select label="Pipeline" placeholder="Choose one" data={options(pipelines.data?.results)} value={draft.pipeline} searchable onChange={(next) => set('pipeline', next)} error={fieldError(error, 'pipeline')} />
          )}
        </Group>
        <Select
          label="Output schema"
          description="Optional: the shape of the result; else the assistant's own."
          data={[{ value: '', label: "The assistant's own" }, ...options(schemas.data?.results)]}
          value={draft.output_schema ?? ''}
          allowDeselect={false}
          onChange={(next) => set('output_schema', next || null)}
          error={fieldError(error, 'output_schema')}
        />
        <OwnerFields value={draft} error={error} onChange={(next) => setDraft((current) => ({ ...current, ...next, parent: next.site === current.site ? current.parent : null }))} />
        <PlaceFields site={draft.site} parent={draft.parent} type={draft.page_type} error={error} onChange={(next) => setDraft((current) => ({ ...current, ...next }))} />
        {error ? <Alert color="red">{errorText(error)}</Alert> : null}
        <Group>
          <Button variant="default" loading={save.isPending && !save.variables?.generate} disabled={!text.trim()} onClick={() => save.mutate({ generate: false })}>
            Save the brief
          </Button>
          <Button type="submit" loading={save.isPending && save.variables?.generate} disabled={!ready}>
            {brief ? 'Save and generate again' : 'Save and generate'}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}

function Metadata({ metadata }: { metadata: unknown }) {
  const meta = isRecord(metadata) ? metadata : {};
  const rows = Object.entries(meta).filter(([, v]) => v !== '' && !(Array.isArray(v) && v.length === 0));
  if (rows.length === 0) return <Text c="dimmed">No metadata.</Text>;
  return (
    <Table aria-label="Metadata">
      <Table.Tbody>
        {rows.map(([key, value]) => (
          <Table.Tr key={key}>
            <Table.Th>{key}</Table.Th>
            <Table.Td>{Array.isArray(value) ? value.join(', ') : String(value)}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

function BriefView({ brief }: { brief: Brief }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const refresh = () => void qc.invalidateQueries({ queryKey: ['ai'] });
  const generate = useMutation({
    mutationFn: () => call(api.POST('/api/v2/ai/briefs/{public_id}/generate/', { params: { path: { public_id: brief.id } } })),
    onSuccess: refresh,
  });
  const talk = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/ai/conversations/', { body: { title: `About: ${nameOf(brief)}`.slice(0, 200), from_brief: brief.id, assistant: brief.assistant ?? null, site: brief.site ?? null } })),
    onSuccess: (conversation) => go({ to: 'conversation', id: conversation.id }),
  });
  const editable = brief.can_edit;
  const canChange = editable && (brief.status === 'failed' || brief.status === 'ready');
  return (
    <Stack>
      <Group justify="space-between" align="start">
        <Stack gap={2}>
          <Group gap="xs">
            <Title order={3}>{nameOf(brief)}</Title>
            <BriefStatusBadge status={brief.status} />
          </Group>
          <Text size="sm" c="dimmed">
            {brief.owner ? `by ${brief.owner} · ` : ''}updated {new Date(brief.updated_at).toLocaleString()}
          </Text>
        </Stack>
        <Group gap="xs">
          {canChange ? (
            <Button variant="default" onClick={() => setEditing((e) => !e)}>
              {editing ? 'Close the brief' : 'Edit the brief'}
            </Button>
          ) : null}
          <Button variant="default" loading={talk.isPending} disabled={!(brief.markdown || brief.source_text || brief.prompt)} onClick={() => talk.mutate()}>
            Talk it over
          </Button>
        </Group>
      </Group>
      <ReadOnlyNote owner={brief.owner} can={editable} />
      {talk.isError ? <Alert color="red">{errorText(talk.error)}</Alert> : null}
      {editing || (brief.status === 'draft' && editable) ? <BriefForm brief={brief} onSaved={() => setEditing(false)} /> : null}
      {brief.status === 'draft' && !editable ? <Text c="dimmed">This brief has not been generated yet.</Text> : null}
      {brief.status === 'generating' && brief.run ? (
        <Card withBorder>
          <Text fw={600} mb="xs">
            Writing…
          </Text>
          <RunProgress runId={brief.run.id} onFinal={refresh} />
        </Card>
      ) : null}
      {brief.status === 'failed' ? (
        <Alert color="red" title="Generating it failed">
          <Stack gap="xs">
            <Text size="sm">{brief.error || 'The run ended without a result.'}</Text>
            {editable ? (
              <Group>
                <Button size="xs" loading={generate.isPending} onClick={() => generate.mutate()}>
                  Generate again
                </Button>
              </Group>
            ) : null}
          </Stack>
        </Alert>
      ) : null}
      {generate.isError ? <Alert color="red">{errorText(generate.error)}</Alert> : null}
      {brief.status === 'ready' || brief.status === 'applied' ? <Review brief={brief} /> : null}
      {brief.status === 'ready' ? <Apply brief={brief} /> : null}
      {brief.status === 'applied' && brief.page ? (
        <Alert color="grape" title="Applied as a draft">
          <Group gap="xs">
            <Text size="sm">Its text waits on the draft as suggestions.</Text>
            <Button size="xs" variant="light" onClick={() => go({ to: 'page', id: brief.page ?? 0, tab: 'suggestions' })}>
              Open the draft
            </Button>
          </Group>
        </Alert>
      ) : null}
    </Stack>
  );
}

function Review({ brief }: { brief: Brief }) {
  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }}>
      <Card withBorder>
        <Title order={4} mb="xs">
          The draft, rendered
        </Title>
        {brief.markdown ? <MarkdownView markdown={brief.markdown} label="The brief's Markdown, rendered" /> : <Text c="dimmed">No text.</Text>}
      </Card>
      <Stack>
        <Card withBorder>
          <Title order={4} mb="xs">
            Metadata
          </Title>
          <Metadata metadata={brief.metadata} />
        </Card>
        {brief.result !== null && brief.result !== undefined ? (
          <Card withBorder>
            <Title order={4} mb="xs">
              The structured result
            </Title>
            <JsonView value={brief.result} label="The structured result" />
          </Card>
        ) : null}
      </Stack>
    </SimpleGrid>
  );
}

function Apply({ brief }: { brief: Brief }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [place, setPlace] = useState({ parent: brief.parent ?? null, page_type: brief.page_type ?? 'cms.ArticlePage' });
  const apply = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/ai/briefs/{public_id}/apply/', { params: { path: { public_id: brief.id } }, body: { ...(place.parent ? { parent: place.parent } : {}), page_type: place.page_type } })),
    onSuccess: (applied) => {
      notifications.show({ message: `A draft with ${applied.suggestions.length} suggestion(s) to review` });
      void qc.invalidateQueries();
      go({ to: 'page', id: applied.page_id, tab: 'suggestions' });
    },
  });
  return (
    <Card withBorder>
      <Stack>
        <Title order={4}>Apply it as a draft</Title>
        <Text size="sm" c="dimmed">
          A new draft page, never published: the text, its description and keywords arrive on it as suggestions you accept or reject in the editor.
        </Text>
        <PlaceFields site={brief.site ?? null} parent={place.parent} type={place.page_type} error={apply.error} onChange={setPlace} />
        {apply.isError ? <Alert color="red">{errorText(apply.error)}</Alert> : null}
        <Group>
          <Button loading={apply.isPending} onClick={() => apply.mutate()}>
            Apply as a draft
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
