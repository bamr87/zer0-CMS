// Pipelines: ordered steps, each an assistant and what it reads — the previous
// step's answer, the run so far, the brief, a field of the page — built here,
// reordered by dragging (@dnd-kit: with the pointer, or from the keyboard —
// space to pick a step up, the arrows to move it, space to drop) or with the
// move buttons, saved as a whole, and run on a prompt with the run (a parent
// run with a child run per step) followed live.
import { closestCenter, DndContext, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { arrayMove, SortableContext, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { ActionIcon, Alert, Badge, Button, Card, Group, Loader, Paper, Select, Stack, Text, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Pipeline, StepSource, Visibility } from '@zer0/api';
import { useRef, useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { ConfirmButton, fieldError, ON_A_PROMPT, options, OwnerFields, ReadOnlyNote, Rows, RunBox, useAssistants, usePipelines, type Ownership } from './shared';

const SOURCES: { value: StepSource; label: string }[] = [
  { value: 'previous', label: "The previous step's answer" },
  { value: 'conversation', label: 'The run so far' },
  { value: 'brief', label: "The brief's prompt" },
  { value: 'page', label: 'A field of the page' },
];

export function PipelineList() {
  const go = useGo();
  const pipelines = usePipelines();
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          Assistants in order, each reading what the one before wrote.
        </Text>
        <Button onClick={() => go({ to: 'pipeline' })}>New pipeline</Button>
      </Group>
      <Rows
        label="Pipelines"
        query={pipelines}
        name={(p) => p.name}
        onOpen={(p) => go({ to: 'pipeline', id: p.id })}
        columns={[
          { title: 'Steps', cell: (p) => p.steps?.length ?? 0 },
          { title: 'Who sees it', cell: (p) => <Badge variant="light">{p.visibility}</Badge> },
          { title: 'Owner', cell: (p) => p.owner ?? '—' },
        ]}
        empty={{ title: 'No pipelines yet', description: 'Chain assistants: a drafter, then an editor, then a headline writer.', action: <Button onClick={() => go({ to: 'pipeline' })}>New pipeline</Button> }}
      />
    </Stack>
  );
}

/** One pipeline to build and run, or a new one (no id). */
export function PipelineEditor({ id }: { id?: string }) {
  const api = useApi();
  const existing = useQuery({
    queryKey: ['ai', 'pipeline', id],
    enabled: id !== undefined,
    queryFn: () => call(api.GET('/api/v2/ai/pipelines/{public_id}/', { params: { path: { public_id: id ?? '' } } })),
  });
  if (id && existing.isPending) return <Loader aria-label="Loading the pipeline" />;
  if (id && existing.isError) return <Alert color="red">{errorText(existing.error)}</Alert>;
  return <PipelineForm key={existing.data?.updated_at ?? 'new'} pipeline={existing.data} />;
}

interface StepDraft {
  key: string;
  assistant: string | null;
  source: StepSource;
  source_field: string;
}

function PipelineForm({ pipeline }: { pipeline?: Pipeline }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const assistants = useAssistants();
  const [draft, setDraft] = useState<Ownership & { name: string; description: string }>(() => ({
    name: pipeline?.name ?? '',
    description: pipeline?.description ?? '',
    visibility: (pipeline?.visibility ?? 'private') as Visibility,
    site: pipeline?.site ?? null,
  }));
  const [steps, setSteps] = useState<StepDraft[]>(() =>
    (pipeline?.steps ?? []).map((s, i) => ({ key: `step-${i}`, assistant: s.assistant, source: s.source ?? 'previous', source_field: s.source_field ?? '' })),
  );
  const made = useRef(0);
  const editable = pipeline?.can_edit ?? true;
  const sensors = useSensors(useSensor(PointerSensor), useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }));
  const move = (from: number, to: number) => setSteps((current) => arrayMove(current, from, to));
  const dropped = ({ active, over }: DragEndEvent) => {
    if (over && active.id !== over.id) {
      setSteps((current) => arrayMove(current, current.findIndex((s) => s.key === active.id), current.findIndex((s) => s.key === over.id)));
    }
  };
  const add = () => {
    made.current += 1;
    setSteps((current) => [...current, { key: `new-${made.current}`, assistant: null, source: 'previous', source_field: '' }]);
  };
  const change = (key: string, next: Partial<StepDraft>) => setSteps((current) => current.map((s) => (s.key === key ? { ...s, ...next } : s)));
  const body = () => ({ ...draft, steps: steps.map(({ assistant, source, source_field }) => ({ assistant: assistant ?? '', source, source_field })) });
  const save = useMutation({
    mutationFn: () =>
      pipeline
        ? call(api.PATCH('/api/v2/ai/pipelines/{public_id}/', { params: { path: { public_id: pipeline.id } }, body: body() }))
        : call(api.POST('/api/v2/ai/pipelines/', { body: body() })),
    onSuccess: (saved) => {
      notifications.show({ message: `${saved.name} saved` });
      void qc.invalidateQueries({ queryKey: ['ai'] });
      if (!pipeline) go({ to: 'pipeline', id: saved.id });
    },
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/v2/ai/pipelines/{public_id}/', { params: { path: { public_id: pipeline?.id ?? '' } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['ai'] });
      go({ to: 'ai', section: 'pipelines' });
    },
  });
  const error = save.error;
  const choices = options(assistants.data?.results);

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{pipeline ? pipeline.name : 'New pipeline'}</Title>
        {pipeline && editable ? <ConfirmButton label="Delete" question={`Delete ${pipeline.name}?`} busy={remove.isPending} onConfirm={() => remove.mutate()} /> : null}
      </Group>
      {pipeline ? <ReadOnlyNote owner={pipeline.owner} can={editable} /> : null}
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
          <OwnerFields value={draft} disabled={!editable} error={error} onChange={(next) => setDraft({ ...draft, ...next })} />
          <Title order={4}>Steps</Title>
          {steps.length === 0 ? <Text c="dimmed">No steps yet: add the first assistant.</Text> : null}
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={dropped}>
            <SortableContext items={steps.map((s) => s.key)} strategy={verticalListSortingStrategy}>
              <Stack component="ol" gap="xs" p={0} m={0} aria-label="Steps">
                {steps.map((step, i) => (
                  <StepRow
                    key={step.key}
                    step={step}
                    index={i}
                    count={steps.length}
                    choices={choices}
                    editable={editable}
                    onChange={(next) => change(step.key, next)}
                    onMove={(by) => move(i, i + by)}
                    onRemove={() => setSteps((current) => current.filter((s) => s.key !== step.key))}
                  />
                ))}
              </Stack>
            </SortableContext>
          </DndContext>
          {fieldError(error, 'steps') ? <Text c="red" size="sm">{fieldError(error, 'steps')}</Text> : null}
          {error ? <Alert color="red">{errorText(error)}</Alert> : null}
          {editable ? (
            <Group>
              <Button variant="default" onClick={add}>
                Add a step
              </Button>
              <Button type="submit" loading={save.isPending} disabled={!draft.name.trim() || steps.some((s) => !s.assistant)}>
                {pipeline ? 'Save' : 'Create'}
              </Button>
            </Group>
          ) : null}
        </Stack>
      </form>
      {pipeline ? (
        <Card withBorder>
          <Title order={4} mb="xs">
            Run it
          </Title>
          <RunBox
            promptRequired={false}
            start={async (prompt) =>
              (await call(api.POST('/api/v2/ai/pipelines/{public_id}/run/', { params: { path: { public_id: pipeline.id } }, body: { prompt, ...ON_A_PROMPT } }))).run.id
            }
          />
        </Card>
      ) : null}
    </Stack>
  );
}

interface StepProps {
  step: StepDraft;
  index: number;
  count: number;
  choices: { value: string; label: string }[];
  editable: boolean;
  onChange: (next: Partial<StepDraft>) => void;
  onMove: (by: number) => void;
  onRemove: () => void;
}

function StepRow({ step, index, count, choices, editable, onChange, onMove, onRemove }: StepProps) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: step.key, disabled: !editable });
  const n = index + 1;
  return (
    <Paper ref={setNodeRef} component="li" withBorder p="xs" style={{ transform: CSS.Transform.toString(transform), transition, listStyle: 'none' }} aria-label={`Step ${n}`}>
      <Group align="end" wrap="nowrap" gap="xs">
        <ActionIcon variant="subtle" size="lg" aria-label={`Drag step ${n}`} disabled={!editable} {...attributes} {...listeners}>
          ⠿
        </ActionIcon>
        <Text fw={600} w={24}>
          {n}
        </Text>
        <Select label="Assistant" placeholder="Choose one" data={choices} value={step.assistant} disabled={!editable} allowDeselect={false} onChange={(assistant) => onChange({ assistant })} />
        <Select label="Reads" data={SOURCES} value={step.source} disabled={!editable} allowDeselect={false} onChange={(source) => onChange({ source: (source as StepSource | null) ?? 'previous' })} />
        {step.source === 'page' ? (
          <TextInput label="Field" placeholder="body" value={step.source_field} disabled={!editable} onChange={(e) => onChange({ source_field: e.currentTarget.value })} />
        ) : null}
        <ActionIcon variant="subtle" aria-label={`Move step ${n} up`} disabled={!editable || index === 0} onClick={() => onMove(-1)}>
          ↑
        </ActionIcon>
        <ActionIcon variant="subtle" aria-label={`Move step ${n} down`} disabled={!editable || index === count - 1} onClick={() => onMove(1)}>
          ↓
        </ActionIcon>
        <ActionIcon variant="subtle" color="red" aria-label={`Remove step ${n}`} disabled={!editable} onClick={onRemove}>
          ×
        </ActionIcon>
      </Group>
    </Paper>
  );
}
