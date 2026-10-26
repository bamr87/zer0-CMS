// Pitching a story: a headline and an angle by hand, or a wire or feed item to
// pitch from (its link, title and text) — with one, the AI may be asked for a
// pitch from it, which the panel then offers to apply. The story starts at
// pitch on the chosen desk and its panel opens. Once the story exists the pitch
// has worked: if asking the AI then fails, the panel says so, and the form is
// never left open to make the story twice.
import { Alert, Button, Checkbox, Group, Select, Stack, Textarea, TextInput } from '@mantine/core';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { Desk } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';

export function PitchForm({ desks, deskId, onDone }: { desks: Desk[]; deskId?: string; onDone: (storyId: string, notice?: string) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const [desk, setDesk] = useState<string | null>(deskId ?? desks[0]?.id ?? null);
  const [headline, setHeadline] = useState('');
  const [summary, setSummary] = useState('');
  const [item, setItem] = useState({ url: '', title: '', text: '' });
  const [withAi, setWithAi] = useState(true);
  const fromItem = item.url.trim() !== '';
  const pitch = useMutation({
    mutationFn: async () => {
      const story = await call(
        api.POST('/api/v2/newsroom/stories/', {
          body: { desk: desk ?? '', headline, summary, ...(fromItem ? { source: item } : {}) },
        }),
      );
      let notice: string | undefined;
      if (fromItem && withAi) {
        try {
          await call(api.POST('/api/v2/newsroom/stories/{public_id}/ai/', { params: { path: { public_id: story.id } }, body: { kind: 'pitch' } }));
        } catch (error) {
          notice = `The story is pitched, but the AI was not asked for its pitch: ${errorText(error)}`;
        }
      }
      return { story, notice };
    },
    onSuccess: ({ story, notice }) => {
      void qc.invalidateQueries({ queryKey: ['newsroom'] });
      onDone(story.id, notice);
    },
  });
  const set = (name: keyof typeof item) => (e: { currentTarget: { value: string } }) => setItem({ ...item, [name]: e.currentTarget.value });
  return (
    <Stack>
      <Select label="Desk" data={desks.map((d) => ({ value: d.id, label: d.name }))} value={desk} onChange={setDesk} allowDeselect={false} />
      <TextInput label="Headline" description={fromItem ? 'Leave it empty to take the item’s title.' : undefined} value={headline} onChange={(e) => setHeadline(e.currentTarget.value)} />
      <Textarea label="The pitch" description="The angle, and why it matters now." autosize minRows={2} value={summary} onChange={(e) => setSummary(e.currentTarget.value)} />
      <TextInput label="From a wire or feed item: its link" placeholder="https://" value={item.url} onChange={set('url')} />
      {fromItem ? (
        <>
          <TextInput label="Its title" value={item.title} onChange={set('title')} />
          <Textarea label="Its text" autosize minRows={3} value={item.text} onChange={set('text')} />
          <Checkbox label="Ask the AI for a pitch from the item" checked={withAi} onChange={(e) => setWithAi(e.currentTarget.checked)} />
        </>
      ) : null}
      {pitch.error ? <Alert color="red">{errorText(pitch.error)}</Alert> : null}
      <Group justify="flex-end">
        <Button loading={pitch.isPending} disabled={!desk || !(headline.trim() || fromItem)} onClick={() => pitch.mutate()}>
          Pitch it
        </Button>
      </Group>
    </Stack>
  );
}
