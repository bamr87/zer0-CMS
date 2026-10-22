// An automation's actions, in order: each one a kind — run an assistant or a
// pipeline, start an agent run, create a brief or an idea, notify by email or
// a webhook, move a newsroom story — and the fields that kind takes, many of
// them templates over the payload ({{ data.url }}). Reordered by dragging
// (@dnd-kit, the one drag-and-drop library: the pointer, or the keyboard —
// space picks an action up, the arrows move it, space drops it) or with the
// move buttons; saved with the automation as a whole. The fields are data
// (KINDS), so a kind is one entry here and its schema on the platform.
import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ActionIcon, Group, JsonInput, Paper, Select, Stack, Switch, TagsInput, Text, Textarea, TextInput } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import type { AutomationAction } from '@zer0/api';
import { useState } from 'react';

import { call } from '../call';
import { useApi } from '../context';
import { ALL, isRecord, MONO, options, useAssistants, usePipelines, useSchemas } from '../ai/shared';

export type ActionKind = AutomationAction['kind'];

/** One action as the form holds it: its kind, and its other fields as they are typed. */
export interface ActionDraft {
  key: string;
  kind: ActionKind;
  fields: Record<string, unknown>;
}

type Input = 'text' | 'long' | 'assistant' | 'pipeline' | 'schema' | 'board' | 'agent' | 'stage' | 'json' | 'tags' | 'emails' | 'switch';
interface Field {
  name: string;
  label: string;
  input: Input;
  required?: boolean;
  description?: string;
}

const PAGE: Field = { name: 'page', label: 'Page id', input: 'text', description: 'Optional: a page it reads, e.g. {{ data.page_id }}' };
const PROMPT: Field = { name: 'prompt', label: 'Prompt', input: 'long', required: true, description: 'A template over the payload: {{ data.url }}' };

export const KINDS: Record<ActionKind, { label: string; fields: Field[] }> = {
  assistant: { label: 'Run an assistant', fields: [{ name: 'assistant', label: 'Assistant', input: 'assistant', required: true }, PROMPT, PAGE] },
  pipeline: { label: 'Run a pipeline', fields: [{ name: 'pipeline', label: 'Pipeline', input: 'pipeline', required: true }, { ...PROMPT, required: false }, PAGE] },
  agent: {
    label: 'Start an agent run',
    fields: [
      { name: 'agent', label: 'Agent', input: 'agent', required: true, description: 'Live agents that publish nothing' },
      PAGE,
      { name: 'input', label: 'Input', input: 'json', description: 'JSON; its strings are templates' },
    ],
  },
  brief: {
    label: 'Create a brief',
    fields: [
      { name: 'title', label: 'Title', input: 'text' },
      PROMPT,
      { name: 'assistant', label: 'Assistant', input: 'assistant' },
      { name: 'pipeline', label: 'Pipeline', input: 'pipeline' },
      { name: 'output_schema', label: 'Output schema', input: 'schema' },
      { name: 'generate', label: 'Write it now (a person still applies it)', input: 'switch' },
    ],
  },
  idea: {
    label: 'Capture an idea',
    fields: [
      { name: 'title', label: 'Title', input: 'text', required: true, description: 'A template, e.g. {{ source.title }}' },
      { name: 'notes', label: 'Notes', input: 'long' },
      { name: 'url', label: 'Link', input: 'text' },
      { name: 'board', label: 'Board', input: 'board', description: 'Else your inbox' },
      { name: 'tags', label: 'Tags', input: 'tags' },
    ],
  },
  email: {
    label: 'Send an email',
    fields: [
      { name: 'to', label: 'To', input: 'emails', required: true, description: 'Addresses, typed here: a payload never chooses them' },
      { name: 'subject', label: 'Subject', input: 'text', required: true },
      { name: 'body', label: 'Body', input: 'long' },
    ],
  },
  webhook: {
    label: 'Call a webhook',
    fields: [{ name: 'url', label: 'URL', input: 'text', required: true, description: 'Gets the run as JSON, signed with this automation’s secret' }],
  },
  story: {
    label: 'Move a newsroom story',
    fields: [
      { name: 'story', label: 'Story id', input: 'text', required: true, description: 'Usually from the payload, e.g. {{ data.story }}' },
      { name: 'to', label: 'To', input: 'stage', required: true, description: 'Stages that publish nothing' },
      { name: 'assignee', label: 'Assignee (username)', input: 'text', description: 'When it moves to assigned' },
      { name: 'comment', label: 'Comment', input: 'text' },
    ],
  },
};

const KIND_OPTIONS = Object.entries(KINDS).map(([value, kind]) => ({ value, label: kind.label }));

let made = 0;
/** A key for an action in the list (the drag handle and React both need one). */
const actionKey = () => `action-${(made += 1)}`;

export function toDraft(action: AutomationAction): ActionDraft {
  const { kind, ...fields } = action;
  return { key: actionKey(), kind, fields };
}

/** What the platform is sent: the kind and every field that says something (an empty choice is no choice). */
export function toAction({ kind, fields }: ActionDraft): AutomationAction {
  const said = Object.entries(fields).filter(([, value]) => value !== '' && value !== null && value !== undefined && !(Array.isArray(value) && !value.length));
  return { kind, ...Object.fromEntries(said) } as AutomationAction;
}

type Choices = Partial<Record<Input, { value: string; label: string }[]>>;

function useBoards() {
  const api = useApi();
  return useQuery({ queryKey: ['ideas', 'boards', 'all'], queryFn: () => call(api.GET('/api/v2/ideas/boards/', { params: { query: ALL } })) });
}

/** What the fields that pick a row pick from: read once for the whole list. */
function useChoices(agents: { slug: string; name: string }[], stages: string[]): Choices {
  const assistants = useAssistants();
  const pipelines = usePipelines();
  const schemas = useSchemas();
  const boards = useBoards();
  return {
    assistant: options(assistants.data?.results),
    pipeline: options(pipelines.data?.results),
    schema: options(schemas.data?.results),
    board: options(boards.data?.results),
    agent: agents.map((a) => ({ value: a.slug, label: a.name })),
    stage: stages.map((s) => ({ value: s, label: s })),
  };
}

export function ActionList(props: { actions: ActionDraft[]; onChange: (next: ActionDraft[]) => void; editable: boolean; agents: { slug: string; name: string }[]; stages: string[] }) {
  const { actions, onChange, editable } = props;
  const choices = useChoices(props.agents, props.stages);
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const dropped = ({ active, over }: DragEndEvent) => {
    if (over && active.id !== over.id) {
      onChange(arrayMove(actions, actions.findIndex((a) => a.key === active.id), actions.findIndex((a) => a.key === over.id)));
    }
  };
  const change = (key: string, next: Partial<ActionDraft>) => onChange(actions.map((a) => (a.key === key ? { ...a, ...next } : a)));
  return (
    <Stack gap="xs">
      {actions.length === 0 ? <Text c="dimmed">No actions yet: add the first.</Text> : null}
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={dropped}>
        <SortableContext items={actions.map((a) => a.key)} strategy={verticalListSortingStrategy}>
          <Stack component="ol" gap="xs" p={0} m={0} aria-label="Actions">
            {actions.map((action, i) => (
              <ActionRow
                key={action.key}
                action={action}
                index={i}
                count={actions.length}
                editable={editable}
                choices={choices}
                onChange={(next) => change(action.key, next)}
                onMove={(by) => onChange(arrayMove(actions, i, i + by))}
                onRemove={() => onChange(actions.filter((a) => a.key !== action.key))}
              />
            ))}
          </Stack>
        </SortableContext>
      </DndContext>
      {editable ? (
        <Select
          aria-label="Add an action"
          placeholder="Add an action…"
          data={KIND_OPTIONS}
          value={null}
          onChange={(kind) => kind && onChange([...actions, { key: actionKey(), kind: kind as ActionKind, fields: {} }])}
        />
      ) : null}
    </Stack>
  );
}

interface RowProps {
  action: ActionDraft;
  index: number;
  count: number;
  editable: boolean;
  choices: Choices;
  onChange: (next: Partial<ActionDraft>) => void;
  onMove: (by: number) => void;
  onRemove: () => void;
}

function ActionRow({ action, index, count, editable, choices, onChange, onMove, onRemove }: RowProps) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: action.key, disabled: !editable });
  const n = index + 1;
  const set = (name: string, value: unknown) => onChange({ fields: { ...action.fields, [name]: value } });
  return (
    <Paper ref={setNodeRef} component="li" withBorder p="xs" style={{ transform: CSS.Transform.toString(transform), transition, listStyle: 'none' }} aria-label={`Action ${n}`}>
      <Stack gap="xs">
        <Group wrap="nowrap" gap="xs">
          <ActionIcon variant="subtle" size="lg" aria-label={`Drag action ${n}`} disabled={!editable} {...attributes} {...listeners}>
            ⠿
          </ActionIcon>
          <Text fw={600} w={24}>
            {n}
          </Text>
          <Select
            flex={1}
            aria-label={`Action ${n}: what it does`}
            data={KIND_OPTIONS}
            value={action.kind}
            disabled={!editable}
            allowDeselect={false}
            onChange={(kind) => kind && kind !== action.kind && onChange({ kind: kind as ActionKind, fields: {} })}
          />
          <ActionIcon variant="subtle" aria-label={`Move action ${n} up`} disabled={!editable || index === 0} onClick={() => onMove(-1)}>
            ↑
          </ActionIcon>
          <ActionIcon variant="subtle" aria-label={`Move action ${n} down`} disabled={!editable || index === count - 1} onClick={() => onMove(1)}>
            ↓
          </ActionIcon>
          <ActionIcon variant="subtle" color="red" aria-label={`Remove action ${n}`} disabled={!editable} onClick={onRemove}>
            ×
          </ActionIcon>
        </Group>
        {KINDS[action.kind].fields.map((field) => (
          <FieldInput key={field.name} field={field} value={action.fields[field.name]} disabled={!editable} choices={choices[field.input] ?? []} onChange={(value) => set(field.name, value)} />
        ))}
      </Stack>
    </Paper>
  );
}

const text = (value: unknown) => (typeof value === 'string' ? value : '');
const list = (value: unknown) => (Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []);

/** The object typed so far, or undefined while it is not one (the field shows why). */
function objectOf(typed: string): Record<string, unknown> | undefined {
  try {
    const parsed: unknown = typed.trim() ? JSON.parse(typed) : {};
    return isRecord(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function FieldInput(props: { field: Field; value: unknown; disabled: boolean; choices: { value: string; label: string }[]; onChange: (value: unknown) => void }) {
  const { field, value, disabled, choices, onChange } = props;
  const common = { label: field.label, description: field.description, required: field.required, disabled };
  const [json, setJson] = useState(() => (isRecord(value) ? JSON.stringify(value, null, 2) : ''));
  switch (field.input) {
    case 'long':
      return <Textarea {...common} autosize minRows={2} styles={MONO} value={text(value)} onChange={(e) => onChange(e.currentTarget.value)} />;
    case 'switch':
      return <Switch label={field.label} disabled={disabled} checked={value === true} onChange={(e) => onChange(e.currentTarget.checked)} />;
    case 'tags':
    case 'emails':
      return <TagsInput {...common} value={list(value)} onChange={onChange} />;
    case 'json':
      return (
        <JsonInput
          {...common}
          autosize
          minRows={2}
          value={json}
          validationError="This is not valid JSON"
          onChange={(next) => {
            setJson(next);
            const parsed = objectOf(next);
            if (parsed) onChange(parsed);
          }}
        />
      );
    case 'text':
      return <TextInput {...common} styles={MONO} value={text(value)} onChange={(e) => onChange(e.currentTarget.value)} />;
    default:
      return <Select {...common} data={choices} value={text(value) || null} clearable={!field.required} onChange={(next) => onChange(next ?? '')} />;
  }
}
