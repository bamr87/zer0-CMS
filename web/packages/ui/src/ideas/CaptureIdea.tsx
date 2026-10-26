// Capture an idea from anywhere — the Ideas workspace, the editor's research
// tab, later the extension — through the one capture endpoint: a title and
// notes (or AIEO's topic template), tags, onto a board or into the inbox.
import { Button, Checkbox, Group, Stack, TagsInput, Textarea, TextInput } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { Idea } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';

interface Props {
  /** A board's id; none puts the idea in the inbox. */
  boardId?: string | null;
  /** A line added to the notes, saying where the idea came up. */
  context?: string;
  onCaptured?: (idea: Idea) => void;
}

export function CaptureIdea({ boardId, context, onCaptured }: Props) {
  const api = useApi();
  const qc = useQueryClient();
  const [title, setTitle] = useState('');
  const [notes, setNotes] = useState('');
  const [tags, setTags] = useState<string[]>([]);
  const [topic, setTopic] = useState(false);
  const capture = useMutation({
    mutationFn: () => {
      const extra = topic ? [] : [notes.trim(), context ?? ''].filter(Boolean);
      const text = [title.trim(), ...extra].join('\n');
      return call(api.POST('/api/v2/ideas/capture/', { body: { text, board: boardId ?? null, tags, template: topic ? 'topic' : '' } }));
    },
    onSuccess: (idea) => {
      notifications.show({ message: `Captured “${idea.title}”` });
      setTitle('');
      setNotes('');
      setTags([]);
      void qc.invalidateQueries({ queryKey: ['ideas'] });
      onCaptured?.(idea);
    },
    onError: (error) => notifications.show({ color: 'red', message: errorText(error) }),
  });
  return (
    <Stack
      gap="xs"
      component="form"
      aria-label="Capture an idea"
      onSubmit={(e) => {
        e.preventDefault();
        capture.mutate();
      }}
    >
      <TextInput label="Idea" required value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
      <Textarea label="Notes" autosize minRows={2} disabled={topic} value={notes} onChange={(e) => setNotes(e.currentTarget.value)} />
      <TagsInput label="Tags" value={tags} onChange={setTags} />
      <Group justify="space-between">
        <Checkbox label="Start from the topic template" checked={topic} onChange={(e) => setTopic(e.currentTarget.checked)} />
        <Button type="submit" disabled={!title.trim()} loading={capture.isPending}>
          Capture
        </Button>
      </Group>
    </Stack>
  );
}
