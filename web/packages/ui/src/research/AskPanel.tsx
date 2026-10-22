// Ask the sources: a question answered by a run from the closest sources (a
// collection's, or all a person sees), every claim marked with its source and
// every quote checked against the source's own text — shown as checked or
// not, so a reader knows which to trust.
import { Alert, Anchor, Badge, Button, Card, Group, Loader, Stack, Text, Textarea } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo } from '../context';

export function AskPanel({ collection }: { collection: string | null }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [text, setText] = useState('');
  const query = { collection: collection ?? undefined, page_size: 20 };
  const questions = useQuery({
    queryKey: ['questions', query],
    queryFn: () => call(api.GET('/api/v2/research/questions/', { params: { query } })),
    refetchInterval: (q) => (q.state.data?.results.some((question) => question.status === 'pending') ? 1500 : false),
  });
  const ask = useMutation({
    mutationFn: () => call(api.POST('/api/v2/research/questions/', { body: { text, collection } })),
    onSuccess: () => {
      setText('');
      void qc.invalidateQueries({ queryKey: ['questions'] });
    },
  });

  return (
    <Stack>
      <Textarea
        label="Ask your sources"
        description="Answered only from the sources, each claim cited."
        autosize
        minRows={2}
        value={text}
        onChange={(e) => setText(e.currentTarget.value)}
      />
      <Group>
        <Button disabled={!text.trim()} loading={ask.isPending} onClick={() => ask.mutate()}>
          Ask
        </Button>
      </Group>
      {ask.isError ? <Alert color="red">{errorText(ask.error)}</Alert> : null}
      {questions.isPending ? <Loader /> : null}
      {(questions.data?.results ?? []).map((question) => (
        <Card key={question.id} withBorder padding="sm" component="article" aria-label={question.text}>
          <Text fw={600}>{question.text}</Text>
          {question.status === 'pending' ? (
            <Group gap="xs" mt="xs">
              <Loader size="xs" />
              <Text size="sm" c="dimmed">
                Reading the sources…
              </Text>
            </Group>
          ) : null}
          {question.status === 'failed' ? <Alert color="red" mt="xs">{question.error}</Alert> : null}
          {question.answer ? (
            <Text size="sm" mt="xs" style={{ whiteSpace: 'pre-wrap' }}>
              {question.answer}
            </Text>
          ) : null}
          {question.citations.length ? (
            <Stack gap={4} mt="xs" aria-label="Citations">
              {question.citations.map((cited, i) => (
                <Group key={`${cited.label}-${i}`} gap="xs" wrap="nowrap" align="start">
                  <Badge size="sm" variant="outline">
                    {cited.label}
                  </Badge>
                  <Text size="sm">
                    <Anchor component="button" type="button" size="sm" onClick={() => go({ to: 'source', id: cited.source })}>
                      {cited.title}
                    </Anchor>{' '}
                    — “{cited.quote}”
                  </Text>
                  <Badge size="xs" color={cited.verified ? 'teal' : 'orange'} variant="light">
                    {cited.verified ? 'quote checked' : 'not found in the source'}
                  </Badge>
                </Group>
              ))}
            </Stack>
          ) : null}
        </Card>
      ))}
    </Stack>
  );
}
