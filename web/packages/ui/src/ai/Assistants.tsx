// Assistants: the personas people write — instructions, a prompt template,
// a provider and model, parameters, an output schema and the read-only tools
// it may use — listed, created, edited, exported and imported as documents,
// and tried on a prompt with the run followed live. An assistant only
// proposes: what it answers is something a person reads, accepts or drops.
import { Alert, Badge, Button, Card, Group, Loader, MultiSelect, NumberInput, Select, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Assistant, components, Visibility } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import {
  ALL,
  ConfirmButton,
  documentOf,
  ExportButton,
  fieldError,
  ImportButton,
  isRecord,
  MONO,
  ON_A_PROMPT,
  options,
  OwnerFields,
  ReadOnlyNote,
  Rows,
  RunBox,
  useAssistants,
  useProviders,
  useSchemas,
  type Ownership,
} from './shared';

const EFFORT = ['low', 'medium', 'high', 'xhigh', 'max'];

export function AssistantList() {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const assistants = useAssistants();
  const schemas = useSchemas();
  const schemaName = (id: string | null | undefined) => schemas.data?.results.find((s) => s.id === id)?.name ?? '—';
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Personas that write for you. Every answer is a suggestion or a draft someone reviews.
        </Text>
        <Group gap="xs">
          <ImportButton
            label="Import an assistant"
            onImport={async (document) => {
              const body = documentOf<components['schemas']['AssistantDocumentRequest']>(document);
              const made = await call(api.POST('/api/v2/ai/assistants/import/', { body }));
              void qc.invalidateQueries({ queryKey: ['ai'] });
              go({ to: 'assistant', id: made.id });
            }}
          />
          <Button onClick={() => go({ to: 'assistant' })}>New assistant</Button>
        </Group>
      </Group>
      <Rows
        label="Assistants"
        query={assistants}
        name={(a) => a.name}
        onOpen={(a) => go({ to: 'assistant', id: a.id })}
        columns={[
          { title: 'Model', cell: (a) => a.provider ?? 'the default provider' },
          { title: 'Output schema', cell: (a) => schemaName(a.output_schema) },
          { title: 'Who sees it', cell: (a) => <Badge variant="light">{a.visibility}</Badge> },
          { title: 'Owner', cell: (a) => a.owner ?? '—' },
        ]}
        empty={{ title: 'No assistants yet', description: 'Write one, or import one someone exported.', action: <Button onClick={() => go({ to: 'assistant' })}>New assistant</Button> }}
      />
    </Stack>
  );
}

/** One assistant to edit and try, or a new one (no id). */
export function AssistantEditor({ id }: { id?: string }) {
  const api = useApi();
  const existing = useQuery({
    queryKey: ['ai', 'assistant', id],
    enabled: id !== undefined,
    queryFn: () => call(api.GET('/api/v2/ai/assistants/{public_id}/', { params: { path: { public_id: id ?? '' } } })),
  });
  if (id && existing.isPending) return <Loader aria-label="Loading the assistant" />;
  if (id && existing.isError) return <Alert color="red">{errorText(existing.error)}</Alert>;
  return <AssistantForm key={existing.data?.updated_at ?? 'new'} assistant={existing.data} />;
}

interface Draft extends Ownership {
  name: string;
  description: string;
  instructions: string;
  prompt_template: string;
  provider: string | null;
  model: string | null;
  output_schema: string | null;
  tools: string[];
  temperature: number | string;
  top_p: number | string;
  max_tokens: number | string;
  effort: string | null;
}

function draftOf(a: Assistant | undefined): Draft {
  const params = isRecord(a?.params) ? a.params : {};
  const num = (v: unknown) => (typeof v === 'number' ? v : '');
  return {
    name: a?.name ?? '',
    description: a?.description ?? '',
    instructions: a?.instructions ?? '',
    prompt_template: a?.prompt_template ?? '',
    provider: a?.provider ?? null,
    model: a?.model ?? null,
    output_schema: a?.output_schema ?? null,
    tools: Array.isArray(a?.tools) ? a.tools.filter((t): t is string => typeof t === 'string') : [],
    temperature: num(params.temperature),
    top_p: num(params.top_p),
    max_tokens: num(params.max_tokens),
    effort: typeof params.effort === 'string' ? params.effort : null,
    visibility: (a?.visibility ?? 'private') as Visibility,
    site: a?.site ?? null,
  };
}

/** The request: the draft with its four parameters folded into `params`, leaving out the ones not set. */
function bodyOf({ temperature, top_p, max_tokens, effort, ...rest }: Draft) {
  const params = Object.fromEntries(Object.entries({ temperature, top_p, max_tokens, effort }).filter(([, v]) => v !== '' && v !== null));
  return { ...rest, params };
}

function AssistantForm({ assistant }: { assistant?: Assistant }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [draft, setDraft] = useState(() => draftOf(assistant));
  const providers = useProviders();
  const schemas = useSchemas();
  const modelQuery = { ...ALL, active: true, ...(draft.provider ? { provider: draft.provider } : {}) };
  const models = useQuery({ queryKey: ['ai', 'models', modelQuery], queryFn: () => call(api.GET('/api/v2/ai/models/', { params: { query: modelQuery } })) });
  const tools = useQuery({ queryKey: ['ai', 'tools'], queryFn: () => call(api.GET('/api/v2/ai/assistants/tools/')) });
  const editable = assistant?.can_edit ?? true;
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      assistant
        ? call(api.PATCH('/api/v2/ai/assistants/{public_id}/', { params: { path: { public_id: assistant.id } }, body: bodyOf(draft) }))
        : call(api.POST('/api/v2/ai/assistants/', { body: bodyOf(draft) })),
    onSuccess: (saved) => {
      notifications.show({ message: `${saved.name} saved` });
      void qc.invalidateQueries({ queryKey: ['ai'] });
      if (!assistant) go({ to: 'assistant', id: saved.id });
    },
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/v2/ai/assistants/{public_id}/', { params: { path: { public_id: assistant?.id ?? '' } } })),
    onSuccess: () => {
      notifications.show({ message: 'Assistant deleted' });
      void qc.invalidateQueries({ queryKey: ['ai'] });
      go({ to: 'ai', section: 'assistants' });
    },
  });
  const error = save.error;
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{assistant ? assistant.name : 'New assistant'}</Title>
        {assistant ? (
          <Group gap="xs">
            <ExportButton
              name={assistant.name}
              load={() => call(api.GET('/api/v2/ai/assistants/{public_id}/export/', { params: { path: { public_id: assistant.id } } }))}
            />
            {editable ? <ConfirmButton label="Delete" question={`Delete ${assistant.name}? Pipelines that use it keep it from going.`} busy={remove.isPending} onConfirm={() => remove.mutate()} /> : null}
          </Group>
        ) : null}
      </Group>
      {assistant ? <ReadOnlyNote owner={assistant.owner} can={editable} /> : null}
      {remove.isError ? <Alert color="red">{errorText(remove.error)}</Alert> : null}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <Stack>
          <TextInput label="Name" required value={draft.name} disabled={!editable} onChange={(e) => set('name', e.currentTarget.value)} error={fieldError(error, 'name')} />
          <TextInput label="Description" value={draft.description} disabled={!editable} onChange={(e) => set('description', e.currentTarget.value)} />
          <Textarea
            label="Instructions"
            description="The system prompt: who it is and how it writes."
            autosize
            minRows={4}
            value={draft.instructions}
            disabled={!editable}
            onChange={(e) => set('instructions', e.currentTarget.value)}
            error={fieldError(error, 'instructions')}
          />
          <Textarea
            label="Prompt template"
            description="Optional. A Django template around each request, which it reads as {{ prompt }}."
            autosize
            minRows={2}
            styles={MONO}
            value={draft.prompt_template}
            disabled={!editable}
            onChange={(e) => set('prompt_template', e.currentTarget.value)}
            error={fieldError(error, 'prompt_template')}
          />
          <Group grow align="start">
            <Select
              label="Provider"
              data={[{ value: '', label: 'The default provider' }, ...(providers.data?.results ?? []).map((p) => ({ value: p.slug, label: p.display_name || p.slug }))]}
              value={draft.provider ?? ''}
              allowDeselect={false}
              disabled={!editable}
              onChange={(next) => setDraft((current) => ({ ...current, provider: next || null, model: null }))}
              error={fieldError(error, 'provider')}
            />
            <Select
              label="Model"
              searchable
              data={[{ value: '', label: "The provider's default" }, ...(models.data?.results ?? []).map((m) => ({ value: m.id, label: `${m.display_name || m.model_id} (${m.provider})` }))]}
              value={draft.model ?? ''}
              allowDeselect={false}
              disabled={!editable}
              onChange={(next) => set('model', next || null)}
              error={fieldError(error, 'model')}
            />
          </Group>
          <Group grow align="start">
            <NumberInput label="Temperature" min={0} max={2} step={0.1} decimalScale={2} value={draft.temperature} disabled={!editable} onChange={(v) => set('temperature', v)} />
            <NumberInput label="Top p" min={0} max={1} step={0.05} decimalScale={2} value={draft.top_p} disabled={!editable} onChange={(v) => set('top_p', v)} />
            <NumberInput label="Max tokens" min={1} max={128000} step={256} allowDecimal={false} value={draft.max_tokens} disabled={!editable} onChange={(v) => set('max_tokens', v)} />
            <Select label="Effort" data={EFFORT} value={draft.effort} clearable placeholder="default" disabled={!editable} onChange={(v) => set('effort', v)} />
          </Group>
          {fieldError(error, 'params') ? <Text c="red" size="sm">{fieldError(error, 'params')}</Text> : null}
          <Select
            label="Output schema"
            description="Optional. The answer must match it, and is rendered to Markdown through its template."
            data={[{ value: '', label: 'None: a plain answer' }, ...options(schemas.data?.results)]}
            value={draft.output_schema ?? ''}
            allowDeselect={false}
            disabled={!editable}
            onChange={(next) => set('output_schema', next || null)}
            error={fieldError(error, 'output_schema')}
          />
          <MultiSelect
            label="Tools"
            description="Read-only tools it may use while it writes."
            data={(tools.data ?? []).map((t) => ({ value: t.name, label: t.name }))}
            value={draft.tools}
            disabled={!editable}
            onChange={(next) => set('tools', next)}
            error={fieldError(error, 'tools')}
          />
          <OwnerFields value={draft} disabled={!editable} error={error} onChange={(next) => setDraft((current) => ({ ...current, ...next }))} />
          {error ? <Alert color="red">{errorText(error)}</Alert> : null}
          {editable ? (
            <Group>
              <Button type="submit" loading={save.isPending} disabled={!draft.name.trim()}>
                {assistant ? 'Save' : 'Create'}
              </Button>
            </Group>
          ) : null}
        </Stack>
      </form>
      {assistant ? (
        <Card withBorder>
          <Title order={4} mb="xs">
            Try it
          </Title>
          <RunBox
            start={async (prompt) =>
              (await call(api.POST('/api/v2/ai/assistants/{public_id}/run/', { params: { path: { public_id: assistant.id } }, body: { prompt, ...ON_A_PROMPT } }))).run.id
            }
          />
        </Card>
      ) : null}
    </Stack>
  );
}
