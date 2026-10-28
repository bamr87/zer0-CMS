// A story's panel: where it stands and where it may go next; its planning (the
// pitch, priority, reporter, deadline, slot, embargo — the last four the desk
// editors' to set) and bylines, saved as what changed; its page; the AI's help
// — a pitch from its wire item, a draft from its pitch, headlines and a
// summary, a correction note — each something the person applies or accepts;
// its corrections and updates, which publish nothing else; its history; and,
// once it is live, Distribute — a draft post of it for one of its site's
// channels, a newsletter among them.
// Every change is a request the platform checks again; nothing here publishes
// without the person saying so.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Code,
  Divider,
  Group,
  Loader,
  MultiSelect,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Timeline,
  Title,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { components, StoryDetail, StoryStatus } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { fromLocalInput, toLocalInput } from '../FieldsPanel';
import { Distribute } from '../distribution/Compose';
import { RunStatus } from '../RunTimeline';
import { MoveDialog } from './MoveDialog';
import { moveLabel, needOf, PRIORITIES, PUBLISHED, statusOf, useDesks, useMove, when } from './shared';

const FINAL = ['succeeded', 'failed', 'refused', 'cancelled'];
const AI_LABEL = { pitch: 'Pitch', draft: 'Draft', headlines: 'Headlines', correction: 'Correction note' };
type Kind = keyof typeof AI_LABEL;

interface Pitch {
  headline?: string;
  angle?: string;
  why_now?: string;
}

type PatchedStory = components['schemas']['PatchedStoryRequest'];

function planOf(story: StoryDetail) {
  return {
    headline: story.headline ?? '',
    summary: story.summary ?? '',
    priority: String(story.priority ?? 3),
    deadline: toLocalInput(story.deadline),
    slot_date: story.slot_date ?? '',
    embargo: toLocalInput(story.embargo),
    byline_ids: story.bylines.map((b) => b.id),
  };
}

/** What the person changed in the plan, as the PATCH body — nothing they left alone. */
function planChanges(plan: ReturnType<typeof planOf>, was: ReturnType<typeof planOf>): PatchedStory {
  const body: PatchedStory = {};
  if (plan.headline !== was.headline) body.headline = plan.headline;
  if (plan.summary !== was.summary) body.summary = plan.summary;
  if (plan.priority !== was.priority) body.priority = Number(plan.priority) as 1 | 2 | 3 | 4;
  if (plan.deadline !== was.deadline) body.deadline = fromLocalInput(plan.deadline);
  if (plan.slot_date !== was.slot_date) body.slot_date = plan.slot_date || null;
  if (plan.embargo !== was.embargo) body.embargo = fromLocalInput(plan.embargo);
  if (plan.byline_ids.join() !== was.byline_ids.join()) body.byline_ids = plan.byline_ids;
  return body;
}

export function StoryPanel({ storyId, notice }: { storyId: string; notice?: string }) {
  const api = useApi();
  const story = useQuery({
    queryKey: ['newsroom', 'story', storyId],
    queryFn: () => call(api.GET('/api/v2/newsroom/stories/{public_id}/', { params: { path: { public_id: storyId } } })),
    refetchInterval: (query) => (query.state.data?.ai_runs.some((r) => !FINAL.includes(r.run.status)) ? 1500 : false),
  });
  if (story.isPending) return <Loader />;
  if (story.isError) return <Alert color="red">{errorText(story.error)}</Alert>;
  return (
    <Stack>
      {notice ? <Alert color="yellow">{notice}</Alert> : null}
      <Panel key={story.data.updated_at} story={story.data} />
    </Stack>
  );
}

function Panel({ story }: { story: StoryDetail }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const move = useMove();
  const site = useDesks().data?.results.find((d) => d.id === story.desk)?.site; // the story's site: its channels
  const [asking, setAsking] = useState<StoryStatus | null>(null);
  const path = { params: { path: { public_id: story.id } } };
  const refresh = () => qc.invalidateQueries({ queryKey: ['newsroom'] });
  const save = useMutation({
    mutationFn: (body: PatchedStory) => call(api.PATCH('/api/v2/newsroom/stories/{public_id}/', { ...path, body })),
    onSuccess: refresh,
  });
  const assign = useMutation({
    mutationFn: (assignee: number) => call(api.POST('/api/v2/newsroom/stories/{public_id}/assign/', { ...path, body: { assignee } })),
    onSuccess: refresh,
  });
  const ask = useMutation({
    mutationFn: ({ kind, text }: { kind: Kind; text?: string }) =>
      call(api.POST('/api/v2/newsroom/stories/{public_id}/ai/', { ...path, body: { kind, text } })),
    onSuccess: refresh,
  });
  const applyDraft = useMutation({
    mutationFn: () => call(api.POST('/api/v2/newsroom/stories/{public_id}/apply-draft/', path)),
    onSuccess: refresh,
  });
  const people = useQuery({
    queryKey: ['newsroom', 'people', story.desk],
    queryFn: () => call(api.GET('/api/v2/newsroom/desks/{public_id}/people/', { params: { path: { public_id: story.desk } } })),
  });
  const authors = useQuery({
    queryKey: ['newsroom', 'authors'],
    queryFn: () => call(api.GET('/api/v2/newsroom/authors/', { params: { query: { page_size: 200 } } })),
  });
  const [plan, setPlan] = useState(() => planOf(story));
  const changes = planChanges(plan, planOf(story));
  const set = (name: keyof typeof plan) => (value: string | string[]) => setPlan((p) => ({ ...p, [name]: value }));
  const desks = story.is_editor ? undefined : "Set by the desk's editors";
  const runs = new Map(story.ai_runs.map((r) => [r.kind as Kind, r]));
  const published = PUBLISHED.includes(story.status);
  const failure = move.error ?? save.error ?? assign.error ?? ask.error ?? applyDraft.error;

  const request = (to: StoryStatus) => {
    if (needOf(story.status, to)) setAsking(to);
    else move.mutate({ story: story.id, body: { status: to } });
  };
  const pitch = runs.get('pitch')?.result as Pitch | null | undefined;

  return (
    <Stack>
      <Group gap="xs">
        <Badge color={statusOf(story.status).color}>{statusOf(story.status).label}</Badge>
        {story.breaking ? <Badge color="red">Breaking — copy skipped: {story.fast_path_reason}</Badge> : null}
        <Text size="sm" c="dimmed">
          {story.desk_name}
        </Text>
      </Group>
      <Title order={3}>{story.headline}</Title>
      {failure ? <Alert color="red">{errorText(failure)}</Alert> : null}

      <Group gap="xs" aria-label="Moves">
        {story.moves
          .filter((to) => to !== 'updated' && to !== 'corrected')
          .map((to) => (
            <Button key={to} size="xs" variant="light" loading={move.isPending} onClick={() => request(to)}>
              {moveLabel(story.status, to)}
            </Button>
          ))}
      </Group>

      <Divider label="Planning" labelPosition="left" />
      <TextInput label="Headline" value={plan.headline} onChange={(e) => set('headline')(e.currentTarget.value)} />
      <Textarea label="Pitch" autosize minRows={2} value={plan.summary} onChange={(e) => set('summary')(e.currentTarget.value)} />
      <Group grow>
        <Select
          label="Priority"
          description={desks}
          disabled={!story.is_editor}
          data={PRIORITIES}
          value={plan.priority}
          allowDeselect={false}
          onChange={(v) => set('priority')(v ?? '3')}
        />
        <Select
          label="Reporter"
          searchable
          data={(people.data ?? []).map((p) => ({ value: String(p.id), label: p.name }))}
          value={story.assignee ? String(story.assignee.id) : null}
          onChange={(v) => (v ? assign.mutate(Number(v)) : undefined)}
        />
      </Group>
      <Group grow align="flex-start">
        <TextInput
          label="Deadline"
          description={desks}
          disabled={!story.is_editor}
          type="datetime-local"
          value={plan.deadline}
          onChange={(e) => set('deadline')(e.currentTarget.value)}
        />
        <TextInput
          label="Runs on"
          description={desks}
          disabled={!story.is_editor}
          type="date"
          value={plan.slot_date}
          onChange={(e) => set('slot_date')(e.currentTarget.value)}
        />
        <TextInput
          label="Embargo"
          description={desks ?? 'It goes live no earlier, by any route.'}
          type="datetime-local"
          value={plan.embargo}
          disabled={!story.is_editor || story.status === 'scheduled' || published}
          onChange={(e) => set('embargo')(e.currentTarget.value)}
        />
      </Group>
      <MultiSelect
        label="Bylines"
        searchable
        data={(authors.data?.results ?? []).map((a) => ({ value: a.id, label: a.name }))}
        value={plan.byline_ids}
        onChange={set('byline_ids')}
      />
      <Group justify="flex-end">
        <Button loading={save.isPending} disabled={Object.keys(changes).length === 0} onClick={() => save.mutate(changes)}>
          Save the plan
        </Button>
      </Group>

      <Divider label="The page" labelPosition="left" />
      {story.page ? (
        <Group>
          <Anchor component="button" type="button" onClick={() => story.page && go({ to: 'page', id: story.page.id })}>
            Open “{story.page.title}” in the editor
          </Anchor>
          <Badge variant="light" color={story.page.live ? 'green' : 'gray'}>
            {story.page.live ? 'live' : 'not live'}
          </Badge>
          <Distribute storyId={story.id} siteId={site} disabled={!story.page.live} />
        </Group>
      ) : (
        <Text size="sm" c="dimmed">
          No page yet: it is made when the story moves to drafting — empty, or from the AI's draft.
        </Text>
      )}

      <Divider label="AI help" labelPosition="left" />
      <Group gap="xs">
        <Button size="xs" variant="default" loading={ask.isPending} onClick={() => ask.mutate({ kind: 'pitch' })}>
          Suggest a pitch
        </Button>
        {!story.page ? (
          <Button size="xs" variant="default" loading={ask.isPending} onClick={() => ask.mutate({ kind: 'draft' })}>
            Draft it from the pitch
          </Button>
        ) : (
          <Button size="xs" variant="default" loading={ask.isPending} onClick={() => ask.mutate({ kind: 'headlines' })}>
            Suggest headlines and a summary
          </Button>
        )}
      </Group>
      {story.ai_runs.map((r) => (
        <Stack key={r.kind} gap={4}>
          <Group gap="xs">
            <Text size="sm" fw={500}>
              {AI_LABEL[r.kind as Kind]}
            </Text>
            <RunStatus status={r.run.status} />
            <Anchor component="button" type="button" size="xs" onClick={() => go({ to: 'run', id: r.run.id })}>
              run #{r.run.id}
            </Anchor>
          </Group>
          {r.error ? (
            <Text size="xs" c="red">
              {r.error}
            </Text>
          ) : null}
          {r.kind === 'pitch' && pitch?.headline ? (
            <Group gap="xs">
              <Text size="sm">
                <b>{pitch.headline}</b> — {pitch.angle} {pitch.why_now}
              </Text>
              <Button
                size="xs"
                onClick={() =>
                  save.mutate({ headline: pitch.headline, summary: [pitch.angle, pitch.why_now].filter(Boolean).join(' ') })
                }
              >
                Use this pitch
              </Button>
            </Group>
          ) : null}
          {r.kind === 'draft' && r.run.status === 'succeeded' && !story.page ? (
            <Button size="xs" w="fit-content" loading={applyDraft.isPending} onClick={() => applyDraft.mutate()}>
              Make the AI's draft the story's page
            </Button>
          ) : null}
          {r.kind === 'headlines' && r.run.status === 'succeeded' ? (
            <Button size="xs" w="fit-content" variant="light" onClick={() => go({ to: 'review', runId: r.run.id })}>
              Review the suggested headline and summary
            </Button>
          ) : null}
        </Stack>
      ))}

      {published ? <Corrections story={story} /> : null}

      <Divider label="History" labelPosition="left" />
      <Timeline bulletSize={12} lineWidth={2}>
        {story.events.map((e, i) => (
          <Timeline.Item
            key={i}
            title={e.to_status && e.to_status !== e.action ? `${e.action} → ${statusOf(e.to_status).label.toLowerCase()}` : e.action}
          >
            <Text size="xs" c="dimmed">
              {when(e.created_at)}
              {e.actor ? ` · ${e.actor.name}` : ''}
              {e.assignee ? ` · to ${e.assignee.name}` : ''}
            </Text>
            {e.note ? <Text size="sm">{e.note}</Text> : null}
          </Timeline.Item>
        ))}
      </Timeline>
      {asking ? <MoveDialog story={story} to={asking} onClose={() => setAsking(null)} /> : null}
    </Stack>
  );
}

function Corrections({ story }: { story: StoryDetail }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const move = useMove();
  const [kind, setKind] = useState<'corrected' | 'updated'>('corrected');
  const [changed, setChanged] = useState('');
  const [note, setNote] = useState('');
  const ask = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/newsroom/stories/{public_id}/ai/', { params: { path: { public_id: story.id } }, body: { kind: 'correction', text: changed } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['newsroom'] }),
  });
  const drafted = story.ai_runs.find((r) => r.kind === 'correction');
  const draftText = (drafted?.result as { text?: string } | null | undefined)?.text;
  return (
    <Stack gap="xs">
      <Divider label="Corrections and updates" labelPosition="left" />
      {story.page && !story.page.live ? (
        <Alert color="gray">The page is not live: a note goes on its log, and is shown if the page goes live again.</Alert>
      ) : story.page?.has_unpublished_changes ? (
        <Alert color="yellow" title="Changes saved since the page went live">
          A note publishes nothing else. Review those changes in the editor and publish them there if they should go live.{' '}
          <Anchor component="button" type="button" size="sm" onClick={() => story.page && go({ to: 'page', id: story.page.id })}>
            Review them in the editor
          </Anchor>
        </Alert>
      ) : null}
      {story.corrections.length ? (
        story.corrections.map((c) => (
          <Text key={c.id} size="sm">
            <Badge size="xs" variant="light" color={c.kind === 'correction' ? 'orange' : 'lime'}>
              {c.kind}
            </Badge>{' '}
            {when(c.created_at)} — {c.text}
          </Text>
        ))
      ) : (
        <Text size="sm" c="dimmed">
          None yet. The log is shown on the story wherever it is published.
        </Text>
      )}
      <SegmentedControl
        w="fit-content"
        value={kind}
        onChange={(v) => setKind(v === 'updated' ? 'updated' : 'corrected')}
        data={[
          { value: 'corrected', label: 'Correction' },
          { value: 'updated', label: 'Update' },
        ]}
      />
      <Group align="flex-end">
        <TextInput label="What changed?" description="For the AI to write the note from." value={changed} onChange={(e) => setChanged(e.currentTarget.value)} flex={1} />
        <Button variant="default" disabled={!changed.trim()} loading={ask.isPending} onClick={() => ask.mutate()}>
          Draft the note with AI
        </Button>
      </Group>
      {draftText ? (
        <Group gap="xs">
          <Code>{draftText}</Code>
          <Button size="xs" variant="light" onClick={() => setNote(draftText)}>
            Use the AI's note
          </Button>
        </Group>
      ) : null}
      <Textarea label="Note" autosize minRows={2} value={note} onChange={(e) => setNote(e.currentTarget.value)} />
      {move.error ?? ask.error ? <Alert color="red">{errorText(move.error ?? ask.error)}</Alert> : null}
      <Button
        w="fit-content"
        disabled={!note.trim()}
        loading={move.isPending}
        onClick={() => move.mutate({ story: story.id, body: { status: kind, text: note } }, { onSuccess: () => setNote('') })}
      >
        {moveLabel(story.status, kind)}
      </Button>
    </Stack>
  );
}
