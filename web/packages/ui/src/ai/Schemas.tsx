// Output schemas: the JSON Schemas a structured answer must match, each with
// the Django template that renders an answer to Markdown — listed, edited
// with feedback as the schema is typed (is it JSON, is it an object) and the
// platform's own verdict on save (is it a valid JSON Schema that refers only
// to itself), exported and imported as documents; staff add the bundled ones
// (barodybroject's parody article, news article and content detail).
import { Alert, Badge, Button, Group, JsonInput, Loader, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components, OutputSchema, Visibility } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { ConfirmButton, documentOf, ExportButton, fieldError, ImportButton, isRecord, OwnerFields, ReadOnlyNote, Rows, useMe, useSchemas, type Ownership } from './shared';

const STARTER = '{\n  "type": "object",\n  "properties": {\n    "headline": { "type": "string" },\n    "body": { "type": "string" }\n  },\n  "required": ["headline", "body"]\n}';

/** What is wrong with the schema as typed, before the platform checks it as a JSON Schema. */
export function schemaProblem(text: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    return `Not JSON yet: ${e instanceof Error ? e.message : String(e)}`;
  }
  if (!isRecord(parsed)) return 'A JSON Schema is an object: { … }';
  const refs = JSON.stringify(parsed).match(/"\$ref"\s*:\s*"([^"]*)"/g) ?? [];
  if (refs.some((ref) => !/"#/.test(ref.replace(/^"\$ref"\s*:\s*/, '')))) return "A schema refers only to itself ('#/…'), never to another file or URL";
  return null;
}

export function SchemaList() {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const me = useMe();
  const schemas = useSchemas();
  const bundled = useMutation({
    mutationFn: () => call(api.POST('/api/v2/ai/output-schemas/import-bundled/')),
    onSuccess: (found) => {
      notifications.show({ message: `${found.schemas.length} bundled schema(s) and ${found.assistants.length} assistant(s) are in the library` });
      void qc.invalidateQueries({ queryKey: ['ai'] });
    },
  });
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          The shapes structured answers take, and how each renders to Markdown.
        </Text>
        <Group gap="xs">
          {me.data?.user?.is_staff ? (
            <Button variant="default" loading={bundled.isPending} onClick={() => bundled.mutate()}>
              Add the bundled schemas
            </Button>
          ) : null}
          <ImportButton
            label="Import a schema"
            onImport={async (document) => {
              const body = documentOf<components['schemas']['OutputSchemaRequest']>(document);
              const made = await call(api.POST('/api/v2/ai/output-schemas/', { body }));
              void qc.invalidateQueries({ queryKey: ['ai'] });
              go({ to: 'schema', id: made.id });
            }}
          />
          <Button onClick={() => go({ to: 'schema' })}>New schema</Button>
        </Group>
      </Group>
      {bundled.isError ? <Alert color="red">{errorText(bundled.error)}</Alert> : null}
      <Rows
        label="Output schemas"
        query={schemas}
        name={(s) => s.name}
        onOpen={(s) => go({ to: 'schema', id: s.id })}
        columns={[
          { title: 'Version', cell: (s) => `v${s.version}` },
          { title: 'Kind', cell: (s) => (s.bundled ? <Badge variant="light">bundled</Badge> : 'written here') },
          { title: 'Who sees it', cell: (s) => <Badge variant="light">{s.visibility}</Badge> },
        ]}
        empty={{ title: 'No output schemas yet', description: 'Write one, import one, or add the bundled ones.', action: <Button onClick={() => go({ to: 'schema' })}>New schema</Button> }}
      />
    </Stack>
  );
}

/** One schema to edit, or a new one (no id). */
export function SchemaEditor({ id }: { id?: string }) {
  const api = useApi();
  const existing = useQuery({
    queryKey: ['ai', 'schema', id],
    enabled: id !== undefined,
    queryFn: () => call(api.GET('/api/v2/ai/output-schemas/{public_id}/', { params: { path: { public_id: id ?? '' } } })),
  });
  if (id && existing.isPending) return <Loader aria-label="Loading the schema" />;
  if (id && existing.isError) return <Alert color="red">{errorText(existing.error)}</Alert>;
  return <SchemaForm key={existing.data?.updated_at ?? 'new'} schema={existing.data} />;
}

function SchemaForm({ schema }: { schema?: OutputSchema }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Ownership & { name: string; description: string; render_template: string }>(() => ({
    name: schema?.name ?? '',
    description: schema?.description ?? '',
    render_template: schema?.render_template ?? '',
    visibility: (schema?.visibility ?? 'private') as Visibility,
    site: schema?.site ?? null,
  }));
  const [text, setText] = useState(() => (schema ? JSON.stringify(schema.schema, null, 2) : STARTER));
  const problem = schemaProblem(text);
  const editable = schema?.can_edit ?? true;
  const save = useMutation({
    mutationFn: () => {
      const body = { ...draft, schema: JSON.parse(text) as unknown };
      return schema
        ? call(api.PATCH('/api/v2/ai/output-schemas/{public_id}/', { params: { path: { public_id: schema.id } }, body }))
        : call(api.POST('/api/v2/ai/output-schemas/', { body }));
    },
    onSuccess: (saved) => {
      notifications.show({ message: `${saved.name} saved (v${saved.version})` });
      void qc.invalidateQueries({ queryKey: ['ai'] });
      if (!schema) go({ to: 'schema', id: saved.id });
    },
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/v2/ai/output-schemas/{public_id}/', { params: { path: { public_id: schema?.id ?? '' } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['ai'] });
      go({ to: 'ai', section: 'schemas' });
    },
  });
  const error = save.error;
  return (
    <Stack>
      <Group justify="space-between">
        <Group gap="xs">
          <Title order={3}>{schema ? schema.name : 'New output schema'}</Title>
          {schema ? <Badge variant="light">v{schema.version}</Badge> : null}
          {schema?.bundled ? <Badge variant="light">bundled</Badge> : null}
        </Group>
        {schema ? (
          <Group gap="xs">
            <ExportButton name={schema.name} load={() => call(api.GET('/api/v2/ai/output-schemas/{public_id}/export/', { params: { path: { public_id: schema.id } } }))} />
            {editable ? <ConfirmButton label="Delete" question={`Delete ${schema.name}? Assistants that use it lose it.`} busy={remove.isPending} onConfirm={() => remove.mutate()} /> : null}
          </Group>
        ) : null}
      </Group>
      {schema ? <ReadOnlyNote owner={schema.owner} can={editable} /> : null}
      {remove.isError ? <Alert color="red">{errorText(remove.error)}</Alert> : null}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <Stack>
          <TextInput label="Name" required value={draft.name} disabled={!editable} onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })} error={fieldError(error, 'name')} />
          <TextInput label="Description" value={draft.description} disabled={!editable} onChange={(e) => setDraft({ ...draft, description: e.currentTarget.value })} />
          <JsonInput
            label="JSON Schema"
            description="What an answer must match. Changing it makes a new version."
            autosize
            minRows={8}
            maxRows={30}
            value={text}
            disabled={!editable}
            onChange={setText}
            formatOnBlur
            error={problem ?? fieldError(error, 'schema')}
          />
          {problem ? null : (
            <Text size="sm" c="teal" role="status">
              Valid JSON. The platform checks it as a JSON Schema when you save.
            </Text>
          )}
          <Textarea
            label="Render template"
            description="A Django template that turns an answer into Markdown, e.g. ## {{ headline }}. Empty renders every field."
            autosize
            minRows={3}
            ff="monospace"
            value={draft.render_template}
            disabled={!editable}
            onChange={(e) => setDraft({ ...draft, render_template: e.currentTarget.value })}
            error={fieldError(error, 'render_template')}
          />
          <OwnerFields value={draft} disabled={!editable} error={error} onChange={(next) => setDraft({ ...draft, ...next })} />
          {error ? <Alert color="red">{errorText(error)}</Alert> : null}
          {editable ? (
            <Group>
              <Button type="submit" loading={save.isPending} disabled={!draft.name.trim() || problem !== null}>
                {schema ? 'Save' : 'Create'}
              </Button>
            </Group>
          ) : null}
        </Stack>
      </form>
    </Stack>
  );
}
