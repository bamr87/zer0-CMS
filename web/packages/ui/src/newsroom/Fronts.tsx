// Fronts: a site's home front and its desks' section fronts. Each is a list of
// slots in order — a story pinned there, or the latest published story of a
// desk (any desk on the site, without one) — edited here, saved as a whole, and
// shown beside the editor as a reader would find it.
import { ActionIcon, Alert, Button, Card, Group, List, Loader, Select, Stack, Text, TextInput, Title } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Front, FrontSlot } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { PUBLISHED, useDesks, useStories } from './shared';

export const slugify = (text: string) =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'front';

export function Fronts({ siteId, deskId }: { siteId?: number; deskId?: string }) {
  return siteId ? <SiteFronts siteId={siteId} deskId={deskId} /> : <Text c="dimmed">Pick a site in the header to curate its fronts.</Text>;
}

function SiteFronts({ siteId, deskId }: { siteId: number; deskId?: string }) {
  const api = useApi();
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<string | null>(null);
  const [name, setName] = useState('');
  const fronts = useQuery({
    queryKey: ['newsroom', 'fronts', siteId],
    queryFn: () => call(api.GET('/api/v2/newsroom/fronts/', { params: { query: { site: siteId, page_size: 200 } } })),
  });
  const create = useMutation({
    mutationFn: () =>
      call(api.POST('/api/v2/newsroom/fronts/', { body: { site: siteId, name, slug: slugify(name), desk: deskId ?? null, slots: [] } })),
    onSuccess: (front) => {
      setName('');
      setChosen(front.id);
      void qc.invalidateQueries({ queryKey: ['newsroom', 'fronts'] });
    },
  });
  if (fronts.isPending) return <Loader />;
  if (fronts.isError) return <Alert color="red">{errorText(fronts.error)}</Alert>;
  const all = fronts.data.results;
  const front = all.find((f) => f.id === chosen) ?? all[0];
  return (
    <Stack>
      <Group align="flex-end">
        <Select label="Front" data={all.map((f) => ({ value: f.id, label: f.name }))} value={front?.id ?? null} onChange={setChosen} w={260} />
        <TextInput label="New front" placeholder={deskId ? 'A section front for this desk' : 'The home front'} value={name} onChange={(e) => setName(e.currentTarget.value)} />
        <Button variant="default" disabled={!name.trim()} loading={create.isPending} onClick={() => create.mutate()}>
          Add the front
        </Button>
      </Group>
      {create.error ? <Alert color="red">{errorText(create.error)}</Alert> : null}
      {front ? <FrontEditor key={`${front.id}:${front.updated_at}`} front={front} siteId={siteId} /> : <Text c="dimmed">No fronts yet.</Text>}
    </Stack>
  );
}

function FrontEditor({ front, siteId }: { front: Front; siteId: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const [slots, setSlots] = useState<FrontSlot[]>(front.slots ?? []);
  const published = useStories({ site: siteId, status: PUBLISHED });
  const desks = useDesks(siteId);
  const path = { params: { path: { public_id: front.id } } };
  const shown = useQuery({
    queryKey: ['newsroom', 'front', front.id, front.updated_at],
    queryFn: () => call(api.GET('/api/v2/newsroom/fronts/{public_id}/stories/', path)),
  });
  const save = useMutation({
    mutationFn: () => call(api.PATCH('/api/v2/newsroom/fronts/{public_id}/', { ...path, body: { slots } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['newsroom', 'fronts'] }),
  });
  const change = (i: number, slot: FrontSlot) => setSlots(slots.map((s, at) => (at === i ? slot : s)));
  const swap = (i: number, j: number) => {
    const next = [...slots];
    const [a, b] = [next[i], next[j]];
    if (a && b) [next[i], next[j]] = [b, a];
    setSlots(next);
  };
  const stories = (published.data?.results ?? []).map((s) => ({ value: s.id, label: s.headline ?? '' }));
  const deskOptions = [{ value: '', label: 'Any desk' }, ...(desks.data?.results ?? []).map((d) => ({ value: d.id, label: d.name }))];

  return (
    <Group align="flex-start" grow>
      <Stack>
        <Title order={4}>Slots</Title>
        {slots.map((slot, i) => (
          <Card key={i} withBorder padding="xs" aria-label={`Slot ${i + 1}`}>
            <Group align="flex-end" wrap="nowrap">
              <Text fw={600} w={24}>
                {i + 1}
              </Text>
              <Select
                label="Filled by"
                w={150}
                allowDeselect={false}
                data={[
                  { value: 'pinned', label: 'A pinned story' },
                  { value: 'latest', label: 'The latest' },
                ]}
                value={slot.rule ?? 'pinned'}
                onChange={(rule) => change(i, rule === 'latest' ? { rule: 'latest', desk: null } : { rule: 'pinned', story: null })}
              />
              {slot.rule === 'latest' ? (
                <Select label="From" data={deskOptions} value={slot.desk ?? ''} allowDeselect={false} onChange={(desk) => change(i, { ...slot, desk: desk || null })} />
              ) : (
                <Select label="Story" searchable data={stories} value={slot.story ?? null} onChange={(story) => change(i, { ...slot, story })} />
              )}
              <ActionIcon variant="default" aria-label={`Move slot ${i + 1} up`} disabled={i === 0} onClick={() => swap(i, i - 1)}>
                ↑
              </ActionIcon>
              <ActionIcon variant="default" aria-label={`Move slot ${i + 1} down`} disabled={i === slots.length - 1} onClick={() => swap(i, i + 1)}>
                ↓
              </ActionIcon>
              <ActionIcon variant="default" color="red" aria-label={`Remove slot ${i + 1}`} onClick={() => setSlots(slots.filter((_, at) => at !== i))}>
                ×
              </ActionIcon>
            </Group>
          </Card>
        ))}
        <Group>
          <Button variant="default" onClick={() => setSlots([...slots, { rule: 'latest', desk: null }])}>
            Add a slot
          </Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save the front
          </Button>
        </Group>
        {save.error ? <Alert color="red">{errorText(save.error)}</Alert> : null}
      </Stack>
      <Stack>
        <Title order={4}>As readers see it</Title>
        {shown.isPending ? (
          <Loader size="sm" />
        ) : shown.isError ? (
          <Alert color="red">{errorText(shown.error)}</Alert>
        ) : (
          <List type="ordered" aria-label="The front as readers see it">
            {shown.data.map((slot) => (
              <List.Item key={slot.position}>{slot.story ? slot.story.headline : <Text c="dimmed">nothing to show yet</Text>}</List.Item>
            ))}
          </List>
        )}
      </Stack>
    </Group>
  );
}
