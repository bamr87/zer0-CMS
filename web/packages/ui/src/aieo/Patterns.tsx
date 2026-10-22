// The pattern library: every citability pattern with its category, weight,
// maximum and citation boost; one opened shows the criteria the evaluator
// reads. People with `aieo.change_pattern` change a pattern's weight,
// maximum, criteria or whether it is scored — the scorer reads the change —
// and anyone may apply a pattern to a page (suggestions) or a text (a draft).
import { Alert, Badge, Button, Group, NumberInput, Paper, Stack, Switch, Table, Text, Textarea, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AieoPattern } from '@zer0/api';
import { useState } from 'react';

import { MarkdownView, useMe } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';
import { Rewrite } from './Rewrite';

export function Patterns({ siteId }: { siteId?: number }) {
  const api = useApi();
  const patterns = useQuery({ queryKey: ['aieo', 'patterns'], queryFn: () => call(api.GET('/api/v2/aieo/patterns/')) });
  const [open, setOpen] = useState<string | null>(null);
  const chosen = patterns.data?.find((p) => p.name === open);
  return (
    <Stack>
      {patterns.isError ? <Alert color="red">{errorText(patterns.error)}</Alert> : null}
      <Table aria-label="Pattern library" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Pattern</Table.Th>
            <Table.Th>Category</Table.Th>
            <Table.Th>Weight</Table.Th>
            <Table.Th>Max</Table.Th>
            <Table.Th>Citation boost</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {(patterns.data ?? []).map((p) => (
            <Table.Tr key={p.name}>
              <Table.Td>
                <Button variant="subtle" size="compact-sm" onClick={() => setOpen(p.name)}>
                  {p.display_name}
                </Button>
                {p.enabled ? null : <Badge color="gray" size="xs">off</Badge>}
              </Table.Td>
              <Table.Td>{p.category}</Table.Td>
              <Table.Td>{p.weight}</Table.Td>
              <Table.Td>{p.max_score}</Table.Td>
              <Table.Td>{p.boost_min !== null && p.boost_max !== null ? `${p.boost_min}–${p.boost_max}%` : '—'}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
      {chosen ? <PatternView key={chosen.name} pattern={chosen} siteId={siteId} /> : null}
    </Stack>
  );
}

function PatternView({ pattern, siteId }: { pattern: AieoPattern; siteId?: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const keeper = useMe().data?.permissions.includes('aieo.change_pattern') ?? false;
  const [weight, setWeight] = useState<number | string>(pattern.weight);
  const [max, setMax] = useState<number | string>(pattern.max_score);
  const [enabled, setEnabled] = useState(pattern.enabled ?? true);
  const [body, setBody] = useState(pattern.body);
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH('/api/v2/aieo/patterns/{name}/', {
          params: { path: { name: pattern.name } },
          body: { weight: Number(weight), max_score: Number(max), enabled, body },
        }),
      ),
    onSuccess: () => {
      notifications.show({ message: `${pattern.display_name} saved` });
      void qc.invalidateQueries({ queryKey: ['aieo', 'patterns'] });
    },
  });
  return (
    <Paper withBorder p="md" aria-label={pattern.display_name}>
      <Stack gap="sm">
        <Title order={4}>{pattern.display_name}</Title>
        <Text size="sm" c="dimmed">
          {pattern.description}
        </Text>
        {keeper ? (
          <Stack gap="sm" component="form" aria-label="Change the pattern" onSubmit={(e) => e.preventDefault()}>
            <Group>
              <NumberInput label="Weight" min={1} max={100} w={120} value={weight} onChange={setWeight} />
              <NumberInput label="Most it earns" min={1} max={100} w={140} value={max} onChange={setMax} />
              <Switch label="Scored" checked={enabled} onChange={(e) => setEnabled(e.currentTarget.checked)} mt="lg" />
            </Group>
            <Textarea label="What the evaluator reads (Markdown)" autosize minRows={6} maxRows={20} value={body} onChange={(e) => setBody(e.currentTarget.value)} />
            <Group>
              <Button loading={save.isPending} disabled={!Number(weight) || !Number(max)} onClick={() => save.mutate()}>
                Save the pattern
              </Button>
            </Group>
            {save.isError ? <Alert color="red">{errorText(save.error)}</Alert> : null}
          </Stack>
        ) : (
          <MarkdownView markdown={pattern.body} label="The pattern's criteria" />
        )}
        <Title order={5}>Apply it</Title>
        <Rewrite siteId={siteId} pattern={pattern} />
      </Stack>
    </Paper>
  );
}
