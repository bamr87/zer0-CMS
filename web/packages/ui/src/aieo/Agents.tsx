// The ten AIEO agents — SEO optimizer, meta creator, keyword mapper, human
// editor, headline generator, internal linker, content analyzer, CRO analyst,
// landing page optimizer, performance analyst — run on a pasted text or a
// page, with the site's brand context. Each is a bundled assistant (AI →
// Assistants) and only proposes: its structured answer is shown here, and in
// the editor's AI panel an answer lands on the page as suggestions.
import { Alert, Button, Group, Select, Stack, Text, Textarea } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { Run } from '@zer0/api';
import { useState } from 'react';

import { Answer, newKey, once, oneClick, RunProgress } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';
import { PagePicker } from '../PagePicker';

export function Agents({ siteId }: { siteId?: number }) {
  const api = useApi();
  const agents = useQuery({ queryKey: ['aieo', 'agents'], queryFn: () => call(api.GET('/api/v2/aieo/agents/')) });
  const listed = (agents.data ?? []).filter((a) => a.group === 'agent');
  const [agent, setAgent] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [pageId, setPageId] = useState<number | null>(null);
  const [notes, setNotes] = useState('');
  const [runId, setRunId] = useState<number | null>(null);
  const [done, setDone] = useState<Run | null>(null);
  const chosen = listed.find((a) => a.key === agent);
  const run = useMutation({
    mutationFn: (key: string) =>
      call(
        api.POST('/api/v2/aieo/agents/run/', {
          params: { header: once(key) },
          body: { agent: agent ?? '', content, page_id: pageId, site: siteId ?? null, inputs: notes.trim() ? { notes } : {} },
        }),
      ),
    onSuccess: (made) => {
      setDone(null);
      setRunId(made.run.id);
    },
  });
  return (
    <Stack gap="sm">
      {agents.isError ? <Alert color="red">{errorText(agents.error)}</Alert> : null}
      <Select
        label="Agent"
        placeholder="Choose an agent"
        data={listed.map((a) => ({ value: a.key, label: a.name }))}
        value={agent}
        onChange={setAgent}
      />
      {chosen ? (
        <Text size="sm" c="dimmed">
          {chosen.description}
        </Text>
      ) : null}
      <PagePicker label="On a page" value={pageId} onChange={setPageId} siteId={siteId} description="Or paste a text below." />
      <Textarea label="Text" autosize minRows={3} maxRows={12} value={content} onChange={(e) => setContent(e.currentTarget.value)} disabled={pageId !== null} />
      <Textarea
        label="What else it should know"
        description="A topic, an audience, keywords, analytics — whatever its prompt names."
        autosize
        minRows={2}
        value={notes}
        onChange={(e) => setNotes(e.currentTarget.value)}
      />
      <Group>
        <Button disabled={!agent || !(pageId || content.trim() || notes.trim())} loading={run.isPending} onClick={oneClick(() => run.mutate(newKey()))}>
          Run the agent
        </Button>
      </Group>
      {run.isError ? <Alert color="red">{errorText(run.error)}</Alert> : null}
      {runId ? <RunProgress key={runId} runId={runId} onFinal={setDone} /> : null}
      {done ? <Answer run={done} /> : null}
    </Stack>
  );
}
