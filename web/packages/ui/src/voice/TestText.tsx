// Test a text against a site's voice: the brand guard's findings on it under
// the resolution for the page or the channel chosen, at once and without a
// model (POST /api/v2/sites/<id>/voice/test/). The findings belong to the
// scope they were found under — change the page or the channel and they go —
// and arrive in a live region, so a screen reader announces the verdict.
// Ctrl+Enter (⌘+Enter) tests, as it sends elsewhere in the studio.
import { Alert, Button, Group, Paper, Stack, Text, Textarea, Title } from '@mantine/core';
import { useMutation } from '@tanstack/react-query';
import type { VoiceFinding } from '@zer0/api';
import { useState } from 'react';

import { oneClick } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';
import { LevelBadge } from '../LevelBadge';
import { plural } from './Layers';

export function TestText({ siteId, page, channel }: { siteId: number; page: number | null; channel: string | null }) {
  const api = useApi();
  const [text, setText] = useState('');
  const test = useMutation({
    mutationFn: (scope: { page: number | null; channel: string | null }) =>
      call(api.POST('/api/v2/sites/{id}/voice/test/', { params: { path: { id: siteId } }, body: { text, page: scope.page ?? undefined, channel: scope.channel ?? undefined } })),
  });
  const current = test.variables?.page === page && test.variables.channel === channel;
  const ready = Boolean(text.trim()) && !test.isPending;
  const run = () => {
    if (ready) test.mutate({ page, channel });
  };
  return (
    <Paper withBorder p="md" component="form" aria-label="Test a text" onSubmit={(e) => e.preventDefault()}>
      <Stack gap="xs">
        <Title order={4}>Test a text</Title>
        <Text size="sm" c="dimmed">
          The brand guard’s findings under this voice{channel ? ', as a post to the channel' : page ? ', as text on the page' : ''}. No model is asked. The guard is a floor: it cannot see a voice, an invented claim
          or a second call to action.
        </Text>
        <Textarea
          label="Text"
          description="Ctrl+Enter tests it"
          autosize
          minRows={4}
          maxLength={20000}
          value={text}
          onChange={(e) => setText(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              run();
            }
          }}
        />
        <Group>
          <Button onClick={oneClick(run)} loading={test.isPending} disabled={!text.trim()}>
            Test it
          </Button>
        </Group>
        <div role="status">
          {test.isError && current ? <Alert color="red">{errorText(test.error)}</Alert> : null}
          {test.data && current ? <Findings findings={test.data.findings} /> : null}
        </div>
      </Stack>
    </Paper>
  );
}

function Findings({ findings }: { findings: VoiceFinding[] }) {
  const errors = findings.filter((f) => f.level === 'error').length;
  return (
    <Stack gap={4} aria-label="Findings">
      <Text size="sm" fw={600}>
        {errors ? `${plural(errors, 'error', 'errors')} — the guard would refuse it` : 'No errors — the guard would let it through'}
      </Text>
      {findings.map((f, at) => (
        <Group key={at} gap="xs" wrap="nowrap" align="start">
          <LevelBadge size="sm" level={f.level} />
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {f.message}
          </Text>
        </Group>
      ))}
    </Stack>
  );
}
