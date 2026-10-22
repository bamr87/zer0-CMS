// Moving a story where the move needs a word from the person first: whom to
// assign it to, a comment when sending it back, when to schedule it (its
// embargo, unless they say otherwise), why breaking news skips copy, or the
// correction's or update's note. The platform decides; a refusal is shown
// here, and nothing moves until it agrees.
import { Alert, Button, Group, Modal, Select, Stack, Text, Textarea, TextInput } from '@mantine/core';
import { useQuery } from '@tanstack/react-query';
import type { Story, StoryStatus } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { fromLocalInput, toLocalInput } from '../FieldsPanel';
import { moveLabel, needOf, useMove, type MoveBody } from './shared';

const PROMPT = {
  assignee: 'Who writes it?',
  comment: 'What needs changing? The reporter sees this.',
  when: 'When does it go live? Not before its embargo.',
  reason: 'Breaking news skips the copy desk. Say why — it is kept with the story.',
  note: 'The note readers see on the story.',
};

export function MoveDialog({ story, to, onClose }: { story: Story; to: StoryStatus | null; onClose: () => void }) {
  const need = to ? needOf(story.status, to) : null;
  return (
    <Modal
      opened={to !== null && need !== null}
      onClose={onClose}
      title={to ? `${moveLabel(story.status, to)}: ${story.headline}` : ''}
      closeButtonProps={{ 'aria-label': 'Close' }}
    >
      {to && need ? <MoveForm story={story} to={to} need={need} onDone={onClose} /> : null}
    </Modal>
  );
}

function MoveForm({ story, to, need, onDone }: { story: Story; to: StoryStatus; need: keyof typeof PROMPT; onDone: () => void }) {
  const api = useApi();
  const move = useMove();
  const [value, setValue] = useState(need === 'when' ? toLocalInput(story.embargo) : '');
  const people = useQuery({
    queryKey: ['newsroom', 'people', story.desk],
    queryFn: () => call(api.GET('/api/v2/newsroom/desks/{public_id}/people/', { params: { path: { public_id: story.desk } } })),
    enabled: need === 'assignee',
  });
  const body: MoveBody = { status: to };
  if (need === 'assignee') body.assignee = Number(value);
  else if (need === 'when') body.go_live_at = fromLocalInput(value);
  else if (need === 'reason') body.reason = value;
  else if (need === 'note') body.text = value;
  else body.comment = value;
  const required = need !== 'comment';
  return (
    <Stack>
      <Text size="sm">{PROMPT[need]}</Text>
      {need === 'assignee' ? (
        <Select
          label="Assignee"
          searchable
          data={(people.data ?? []).map((p) => ({ value: String(p.id), label: p.name }))}
          value={value || null}
          onChange={(v) => setValue(v ?? '')}
        />
      ) : need === 'when' ? (
        <TextInput label="Go live at" type="datetime-local" value={value} onChange={(e) => setValue(e.currentTarget.value)} />
      ) : (
        <Textarea
          label={need === 'note' ? 'Note' : need === 'reason' ? 'Reason' : 'Comment'}
          autosize
          minRows={2}
          value={value}
          onChange={(e) => setValue(e.currentTarget.value)}
        />
      )}
      {move.error ? <Alert color="red">{errorText(move.error)}</Alert> : null}
      <Group justify="flex-end">
        <Button variant="default" onClick={onDone}>
          Cancel
        </Button>
        <Button
          loading={move.isPending}
          disabled={required && !value.trim()}
          onClick={() => move.mutate({ story: story.id, body }, { onSuccess: onDone })}
        >
          {moveLabel(story.status, to)}
        </Button>
      </Group>
    </Stack>
  );
}
