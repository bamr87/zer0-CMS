// What the AI workspaces share (PLAN G8): who may configure providers, the
// rows people pick from (sites, providers, assistants, pipelines, output
// schemas), the owner/site/visibility fields every owned row has, a run
// followed live to its end, a finished answer (Markdown rendered by TipTap
// read-only, JSON as JSON), export and import of documents, a table of rows,
// the platform's per-field errors, and the Idempotency-Key every request that
// starts a run carries. Everything reaches the platform through the host's
// client (useApi), so the extension renders it too.
import {
  Alert,
  Anchor,
  Button,
  Code,
  CopyButton,
  EmptyState,
  FileButton,
  Group,
  JsonInput,
  Loader,
  Modal,
  Popover,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
  Typography,
} from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Markdown } from '@tiptap/markdown';
import { EditorContent, useEditor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import type { Run, Visibility } from '@zer0/api';
import { useEffect, useRef, useState, type ReactNode } from 'react';

import { ApiError, call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { RunStatus, useLiveRun } from '../RunTimeline';

/** Every row of a list in one page: the AI lists are short. */
export const ALL = { page_size: 200 } as const;

/** A template or a schema typed in monospace — the field, not its label. */
export const MONO = { input: { fontFamily: 'var(--mantine-font-family-monospace)' } };

export const VISIBILITY: { value: Visibility; label: string }[] = [
  { value: 'private', label: 'Private — only you' },
  { value: 'site', label: 'Site — everyone who edits its site' },
  { value: 'shared', label: 'Shared — everyone signed in' },
];

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

/** The person signed in (the studio's own query, shared through its key). */
export function useMe() {
  const api = useApi();
  return useQuery({ queryKey: ['me'], queryFn: () => call(api.GET('/api/v2/me')), staleTime: 60_000 });
}

/** Whether the person may configure providers (`ai.change_providerconfig`). */
export function useCanConfigure(): boolean {
  return useMe().data?.permissions.includes('ai.change_providerconfig') ?? false;
}

export function useSites() {
  const api = useApi();
  return useQuery({ queryKey: ['sites'], queryFn: () => call(api.GET('/api/v2/sites/')) });
}

export function useProviders() {
  const api = useApi();
  return useQuery({ queryKey: ['ai', 'providers'], queryFn: () => call(api.GET('/api/v2/ai/providers/', { params: { query: ALL } })) });
}

export function useAssistants() {
  const api = useApi();
  const query = { ...ALL, ordering: 'name' };
  return useQuery({ queryKey: ['ai', 'assistants', query], queryFn: () => call(api.GET('/api/v2/ai/assistants/', { params: { query } })) });
}

export function usePipelines() {
  const api = useApi();
  const query = { ...ALL, ordering: 'name' };
  return useQuery({ queryKey: ['ai', 'pipelines', query], queryFn: () => call(api.GET('/api/v2/ai/pipelines/', { params: { query } })) });
}

export function useSchemas() {
  const api = useApi();
  const query = { ...ALL, ordering: 'name' };
  return useQuery({
    queryKey: ['ai', 'schemas', query],
    queryFn: () => call(api.GET('/api/v2/ai/output-schemas/', { params: { query } })),
  });
}

/** A run on a prompt alone — no page, nothing suggested (the request's defaults, which the client types as required). */
export const ON_A_PROMPT = { suggest: false, block_id: '', selection: '' } as const;

/**
 * A key for one thing a person asked for, made when they act and kept with the request (its mutation's
 * variables), so a repeat of that request is answered with the first run instead of starting another. A
 * request that starts a run sends it as `Idempotency-Key`; its control is also disabled while it is out.
 * `crypto.randomUUID` needs a secure context, so a page served over plain HTTP falls back to random bytes.
 */
export function newKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('');
}

/** The header that carries an action's key. */
export const once = (key: string) => ({ 'Idempotency-Key': key });

/**
 * A click handler that ignores the second click of a double click — and, on a submit button, the second submit:
 * a person who double-clicks a button that starts a run or makes a row asks once, however fast the platform
 * answers (a control waiting on its request covers a slow answer; this covers a quick one).
 */
export function oneClick(act?: () => void) {
  return (event: { detail: number; preventDefault: () => void }) => {
    if (event.detail > 1) event.preventDefault();
    else act?.();
  };
}

/** An imported document, checked for the one thing every document has (a name) before the platform reads the rest. */
export function documentOf<T extends { name: string }>(value: unknown): T {
  if (!isRecord(value) || typeof value.name !== 'string') throw new Error('The document is an object with a name');
  return value as T;
}

/** `{value, label}` for a Select, from rows with an id and a name. */
export const options = (rows: { id: string; name: string }[] | undefined) => (rows ?? []).map((r) => ({ value: r.id, label: r.name }));

/** What the platform said about one field of a refused request, if anything. */
export function fieldError(error: unknown, field: string): string | undefined {
  if (!(error instanceof ApiError)) return undefined;
  return error.details.find((d) => d.field === field || d.field?.startsWith(`${field}.`))?.message;
}

export interface Ownership {
  visibility: Visibility;
  site: number | null;
}

/** Who sees a row (visibility) and the site it belongs to, as every owned row has them. */
export function OwnerFields({ value, onChange, disabled, error }: { value: Ownership; onChange: (next: Ownership) => void; disabled?: boolean; error?: unknown }) {
  const sites = useSites();
  return (
    <Group grow align="start">
      <Select
        label="Who sees it"
        data={VISIBILITY}
        value={value.visibility}
        allowDeselect={false}
        disabled={disabled}
        error={fieldError(error, 'visibility')}
        onChange={(next) => onChange({ ...value, visibility: (next as Visibility | null) ?? 'private' })}
      />
      <Select
        label="Site"
        description="Optional: a site you edit"
        data={[{ value: '', label: 'No site' }, ...(sites.data ?? []).map((s) => ({ value: String(s.id), label: s.name }))]}
        value={value.site ? String(value.site) : ''}
        allowDeselect={false}
        disabled={disabled}
        error={fieldError(error, 'site')}
        onChange={(next) => onChange({ ...value, site: Number(next) || null })}
      />
    </Group>
  );
}

const markdownExtensions = [StarterKit, Markdown];

/** Markdown rendered for reading (TipTap, not editable; no injected HTML). */
export function MarkdownView({ markdown, label = 'Rendered Markdown' }: { markdown: string; label?: string }) {
  const editor = useEditor(
    {
      extensions: markdownExtensions,
      content: markdown,
      contentType: 'markdown',
      editable: false,
      injectCSS: false,
      editorProps: { attributes: { 'aria-label': label, role: 'document' } },
    },
    [markdown, label],
  );
  return (
    <Typography>
      <EditorContent editor={editor} />
    </Typography>
  );
}

export function JsonView({ value, label }: { value: unknown; label?: string }) {
  return (
    <Code block aria-label={label}>
      {JSON.stringify(value, null, 2)}
    </Code>
  );
}

/**
 * A run followed live — its status, the step it is on, a link to its
 * timeline — that tells `onFinal` once when it has finished, so the screen
 * that started it reads what the run produced.
 */
export function RunProgress({ runId, onFinal }: { runId: number; onFinal?: (run: Run) => void }) {
  const go = useGo();
  const { run, steps } = useLiveRun(runId);
  const done = run.data?.is_final ? run.data : undefined;
  const told = useRef<number | null>(null);
  useEffect(() => {
    if (done && told.current !== done.id) {
      told.current = done.id;
      onFinal?.(done);
    }
  }, [done, onFinal]);
  if (run.isError) return <Alert color="red">{errorText(run.error)}</Alert>;
  const last = steps.at(-1);
  return (
    <Group gap="xs" role="status" aria-label={`Run #${runId}`}>
      {run.data ? <RunStatus status={run.data.status} /> : null}
      {done ? null : <Loader size="xs" aria-label="Working" />}
      {last ? (
        <Text size="sm" c="dimmed">
          step {last.idx + 1}: {last.kind} · {last.name}
        </Text>
      ) : done ? null : (
        <Text size="sm" c="dimmed">
          Waiting for the first step…
        </Text>
      )}
      <Anchor component="button" type="button" size="sm" onClick={() => go({ to: 'run', id: runId })}>
        Run #{runId}
      </Anchor>
    </Group>
  );
}

/** What a finished assistant or pipeline run answered: its Markdown, and its JSON when it had a schema. */
export function Answer({ run }: { run: Run }) {
  if (run.status !== 'succeeded') {
    return (
      <Alert color="red" title={`The run ${run.status}`}>
        {run.error || 'It gave no answer.'}
      </Alert>
    );
  }
  const out = isRecord(run.output) ? run.output : {};
  const markdown = typeof out.markdown === 'string' ? out.markdown : typeof out.text === 'string' ? out.text : '';
  return (
    <Stack gap="xs">
      {markdown ? <MarkdownView markdown={markdown} label="The answer" /> : <Text c="dimmed">The answer is empty.</Text>}
      {out.json !== undefined ? <JsonView value={out.json} label="The structured answer" /> : null}
    </Stack>
  );
}

/** Try an assistant or a pipeline: a prompt, the run followed live, then its answer. `start` sends the action's key. */
export function RunBox({ start, promptRequired = true }: { start: (prompt: string, key: string) => Promise<number>; promptRequired?: boolean }) {
  const [prompt, setPrompt] = useState('');
  const [runId, setRunId] = useState<number | null>(null);
  const [answer, setAnswer] = useState<Run | null>(null);
  const begin = useMutation({
    mutationFn: (key: string) => start(prompt, key),
    onSuccess: (id) => {
      setAnswer(null);
      setRunId(id);
    },
  });
  return (
    <Stack gap="xs">
      <Textarea label="Prompt" autosize minRows={2} value={prompt} onChange={(e) => setPrompt(e.currentTarget.value)} />
      <Group>
        <Button disabled={promptRequired && !prompt.trim()} loading={begin.isPending} onClick={oneClick(() => begin.mutate(newKey()))}>
          Run
        </Button>
      </Group>
      {begin.isError ? <Alert color="red">{errorText(begin.error)}</Alert> : null}
      {runId ? <RunProgress key={runId} runId={runId} onFinal={setAnswer} /> : null}
      {answer ? <Answer run={answer} /> : null}
    </Stack>
  );
}

/** The format a document is exported and imported in: JSON, or YAML (automations), which travels as its text. */
export type DocumentFormat = 'json' | 'yaml';

const fileName = (name: string, format: DocumentFormat = 'json') =>
  `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'export'}.${format}`;

/** Export a row as a document: shown, copied, or saved as a file. A YAML document is the text `load` gives. */
export function ExportButton({ name, load, format = 'json' }: { name: string; load: () => Promise<unknown>; format?: DocumentFormat }) {
  const [text, setText] = useState<string | null>(null);
  const exported = useMutation({ mutationFn: load, onSuccess: (data) => setText(typeof data === 'string' ? data : JSON.stringify(data, null, 2)) });
  return (
    <>
      <Button variant="default" loading={exported.isPending} onClick={() => exported.mutate()}>
        Export
      </Button>
      {exported.isError ? <Alert color="red">{errorText(exported.error)}</Alert> : null}
      <Modal opened={text !== null} onClose={() => setText(null)} title={`Export ${name}`} size="lg">
        <Stack>
          <Code block aria-label="The exported document">
            {text}
          </Code>
          <Group>
            <CopyButton value={text ?? ''}>{({ copied, copy }) => <Button onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>}</CopyButton>
            <Button component="a" variant="light" href={`data:application/${format};charset=utf-8,${encodeURIComponent(text ?? '')}`} download={fileName(name, format)}>
              Download {fileName(name, format)}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

/** Import a document someone exported: pasted, or read from a file. A YAML document is handed over as its text. */
export function ImportButton(props: { label: string; onImport: (document: unknown) => Promise<unknown>; format?: DocumentFormat }) {
  const { label, onImport, format = 'json' } = props;
  const [opened, setOpened] = useState(false);
  const [text, setText] = useState('');
  const imported = useMutation({
    mutationFn: () => onImport(format === 'yaml' ? text : JSON.parse(text)),
    onSuccess: () => {
      setOpened(false);
      setText('');
    },
  });
  return (
    <>
      <Button variant="default" onClick={() => setOpened(true)}>
        {label}
      </Button>
      <Modal opened={opened} onClose={() => setOpened(false)} title={label} size="lg">
        <Stack>
          <FileButton accept={format === 'yaml' ? 'application/yaml,.yaml,.yml' : 'application/json,.json'} onChange={(file) => void file?.text().then(setText)}>
            {(button) => (
              <Button variant="default" {...button}>
                Read a file…
              </Button>
            )}
          </FileButton>
          {format === 'yaml' ? (
            <Textarea label="The document" description="Paste an exported document, or read one from a file" autosize minRows={8} maxRows={20} styles={MONO} value={text} onChange={(e) => setText(e.currentTarget.value)} />
          ) : (
            <JsonInput label="The document" description="Paste an exported document, or read one from a file" autosize minRows={8} maxRows={20} value={text} onChange={setText} validationError="This is not valid JSON" />
          )}
          {imported.isError ? <Alert color="red">{errorText(imported.error)}</Alert> : null}
          <Group justify="end">
            <Button disabled={!text.trim()} loading={imported.isPending} onClick={oneClick(() => imported.mutate())}>
              Import
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

export interface Column<T> {
  title: string;
  cell: (row: T) => ReactNode;
}

/** Rows in a table whose first cell opens the row; loading, failing and empty states included. */
export function Rows<T extends { id: string }>(props: {
  label: string;
  query: { isPending: boolean; isError: boolean; error: unknown; data?: { results: T[] } };
  columns: Column<T>[];
  name: (row: T) => string;
  onOpen: (row: T) => void;
  empty: { title: string; description: string; action?: ReactNode };
}) {
  const { query, columns, name, onOpen, empty, label } = props;
  if (query.isPending) return <Loader aria-label={`Loading ${label}`} />;
  if (query.isError) return <Alert color="red">{errorText(query.error)}</Alert>;
  const rows = query.data?.results ?? [];
  if (rows.length === 0) {
    return (
      <EmptyState title={empty.title} description={empty.description}>
        {empty.action}
      </EmptyState>
    );
  }
  return (
    <Table highlightOnHover aria-label={label}>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Name</Table.Th>
          {columns.map((c) => (
            <Table.Th key={c.title}>{c.title}</Table.Th>
          ))}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <Anchor component="button" type="button" onClick={() => onOpen(row)}>
                {name(row)}
              </Anchor>
            </Table.Td>
            {columns.map((c) => (
              <Table.Td key={c.title}>{c.cell(row)}</Table.Td>
            ))}
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

/** A destructive action behind a second, explicit confirmation. */
export function ConfirmButton({ label, question, busy, onConfirm }: { label: string; question: string; busy?: boolean; onConfirm: () => void }) {
  const [opened, setOpened] = useState(false);
  return (
    <Popover opened={opened} onChange={setOpened} trapFocus withArrow position="bottom-end">
      <Popover.Target>
        <Button variant="subtle" color="red" loading={busy} onClick={() => setOpened((o) => !o)}>
          {label}
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="xs">
          <Text size="sm">{question}</Text>
          <Group gap="xs" justify="end">
            <Button size="xs" variant="default" onClick={() => setOpened(false)}>
              Keep it
            </Button>
            <Button
              size="xs"
              color="red"
              onClick={() => {
                setOpened(false);
                onConfirm();
              }}
            >
              {label}
            </Button>
          </Group>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

/** A sentence for an owned row that the person may use but not change. */
export function ReadOnlyNote({ owner, can }: { owner: string | null; can: boolean }) {
  if (can) return null;
  return (
    <Alert color="gray">
      {owner ? `${owner} shares this with you` : 'This is shared with you'}: you can use it; only its owner or staff change it.
    </Alert>
  );
}
