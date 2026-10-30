// An automation's run history: every firing, newest first and by cursor —
// what fired it, whether the condition matched, how it ended — and, opened,
// the payload it got and each action's outcome: what it was asked (its
// templates rendered) and what it made, with a link to the agent run, the
// brief, the idea or the story. A run that was limited or skipped says why.
// Runs are their automation's owner's (and staff's): what it heard, it heard
// with the owner's permissions, so someone it is shared with is told so.
import { Accordion, Alert, Anchor, Badge, Button, Group, Loader, Stack, Text } from '@mantine/core';
import { useInfiniteQuery } from '@tanstack/react-query';
import type { AutomationRun, AutomationRunStatus } from '@zer0/api';
import type { ReactNode } from 'react';

import { JsonView } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { shortId } from '../RunTimeline';

const COLOR: Record<AutomationRunStatus, string> = {
  queued: 'blue',
  running: 'blue',
  succeeded: 'green',
  failed: 'red',
  skipped: 'gray',
  limited: 'orange',
};
const OUTCOME_COLOR = { succeeded: 'green', failed: 'red', not_run: 'gray' } as const;

/** The cursor in a next-page link, if there is one. */
const cursorOf = (next: string | null | undefined) => (next ? (new URL(next, 'http://studio.invalid').searchParams.get('cursor') ?? undefined) : undefined);

export function useAutomationRuns(automation: string) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: ['automations', 'runs', automation],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      call(api.GET('/api/v2/automations/runs/', { params: { query: { automation, page_size: 20, ...(pageParam ? { cursor: pageParam } : {}) } } })),
    getNextPageParam: (last) => cursorOf(last.next),
  });
}

export function AutomationRuns({ automation, owner }: { automation: string; owner?: string | null }) {
  const runs = useAutomationRuns(automation);
  if (runs.isPending) return <Loader aria-label="Loading the runs" />;
  if (runs.isError) return <Alert color="red">{errorText(runs.error)}</Alert>;
  const shown = runs.data.pages.flatMap((page) => page.results);
  if (shown.length === 0 && owner !== undefined) {
    return <Text c="dimmed">Its runs are {owner ?? 'its owner'}’s to see: what it hears and does, it hears and does as them.</Text>;
  }
  if (shown.length === 0) return <Text c="dimmed">No runs yet: enable it, or test it with a sample payload.</Text>;
  return (
    <Stack gap="xs">
      <Accordion variant="separated" aria-label="Runs">
        {shown.map((run) => (
          <Accordion.Item key={run.id} value={run.id}>
            <Accordion.Control aria-label={`Run of ${new Date(run.created_at).toLocaleString()}: ${run.status}`}>
              <Group gap="xs">
                <Badge color={COLOR[run.status]}>{run.status}</Badge>
                <Text size="sm">{run.trigger}</Text>
                <Text size="sm" c="dimmed">
                  {new Date(run.created_at).toLocaleString()}
                </Text>
                {run.error ? (
                  <Text size="sm" c="dimmed">
                    — {run.error}
                  </Text>
                ) : null}
              </Group>
            </Accordion.Control>
            <Accordion.Panel>
              <RunDetail run={run} />
            </Accordion.Panel>
          </Accordion.Item>
        ))}
      </Accordion>
      {runs.hasNextPage ? (
        <Button variant="default" loading={runs.isFetchingNextPage} onClick={() => void runs.fetchNextPage()}>
          Earlier runs
        </Button>
      ) : null}
    </Stack>
  );
}

function RunDetail({ run }: { run: AutomationRun }) {
  const verdict = run.matched === null ? 'The condition was not evaluated.' : run.matched ? 'The condition matched.' : 'The condition did not match.';
  return (
    <Stack gap="xs">
      <Text size="sm">{verdict}</Text>
      {run.outcomes.length ? (
        <Stack component="ol" gap="xs" p={0} m={0} aria-label="Outcomes">
          {run.outcomes.map((outcome) => (
            <Stack component="li" key={outcome.index} gap={4} style={{ listStyle: 'none' }} aria-label={`Action ${outcome.index + 1}`}>
              <Group gap="xs">
                <Text fw={600}>{outcome.index + 1}.</Text>
                <Text>{outcome.kind}</Text>
                <Badge color={OUTCOME_COLOR[outcome.status]} variant="light">
                  {outcome.status.replace('_', ' ')}
                </Badge>
                {outcome.ms !== undefined ? (
                  <Text size="xs" c="dimmed">
                    {outcome.ms} ms
                  </Text>
                ) : null}
                <Made result={outcome.result} />
              </Group>
              {outcome.error ? <Text size="sm" c="red">{outcome.error}</Text> : null}
              {outcome.input ? <JsonView value={outcome.input} label={`What action ${outcome.index + 1} was asked`} /> : null}
            </Stack>
          ))}
        </Stack>
      ) : null}
      <Text size="sm" fw={600}>
        The payload
      </Text>
      <JsonView value={run.payload} label="The payload" />
    </Stack>
  );
}

/** Links to what an action made. */
function Made({ result }: { result: AutomationRun['outcomes'][number]['result'] }) {
  const go = useGo();
  if (!result) return null;
  const links: ReactNode[] = [];
  const link = (label: string, open: () => void) => (
    <Anchor key={label} component="button" type="button" size="sm" onClick={open}>
      {label}
    </Anchor>
  );
  const { run, brief, idea, story } = result;
  if (run) links.push(link(`Run ${shortId(run)}`, () => go({ to: 'run', id: run })));
  if (brief) links.push(link('The brief', () => go({ to: 'brief', id: brief })));
  if (idea) links.push(link('The idea', () => go({ to: 'ideas' })));
  if (story) links.push(link(`The story${result.status ? ` (${result.status})` : ''}`, () => go({ to: 'story', id: story })));
  if (result.http_status !== undefined) links.push(<Text key="http" size="sm">HTTP {result.http_status}</Text>);
  if (result.to) links.push(<Text key="to" size="sm">to {result.to.join(', ')}</Text>);
  return <>{links}</>;
}
