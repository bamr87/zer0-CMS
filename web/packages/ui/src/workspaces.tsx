// The workspace registry: the workspaces @zer0/ui offers, as data a host
// renders without knowing any of them (PLAN G10, ADR 0006 decision 9). The
// VS Code extension's dashboard shows one tab per entry and its AI view opens
// `ai`, so a workspace added here reaches the extension with no host code; the
// studio places the same components on its routes (web/studio/src/App.tsx).
// A workspace says which destinations it shows, so a host turns `go(to)` into
// "this workspace, at that destination" without a router of its own.
import { Button, Group, Stack } from '@mantine/core';
import type { ReactNode } from 'react';

import { useGo, type Destination } from './context';
import { CreatePage } from './CreatePage';
import { Overview } from './Overview';
import { PageEditor } from './PageEditor';
import { PageList } from './PageList';
import { RunList, RunTimeline } from './RunTimeline';
import { SuggestionInbox } from './SuggestionInbox';

export interface WorkspaceProps {
  /** The site the host works in; undefined is every site. */
  siteId?: number;
  /** What to show; undefined is where the workspace starts. */
  at?: Destination;
}

export interface Workspace {
  id: string;
  label: string;
  summary: string;
  /** Whether this workspace is where `to` is shown. */
  shows: (to: Destination) => boolean;
  View: (props: WorkspaceProps) => ReactNode;
}

function Write({ siteId, at }: WorkspaceProps) {
  const go = useGo();
  if (at?.to === 'page') return <PageEditor key={at.id} pageId={at.id} />;
  return (
    <Stack>
      <Group justify="flex-end">
        <Button onClick={() => go({ to: 'create' })}>New page</Button>
      </Group>
      <PageList siteId={siteId} />
    </Stack>
  );
}

function Review({ siteId, at }: WorkspaceProps) {
  const runId = at?.to === 'review' ? at.runId : undefined;
  return <SuggestionInbox key={runId} siteId={runId ? undefined : siteId} runId={runId} />;
}

function Ai({ at }: WorkspaceProps) {
  return at?.to === 'run' ? <RunTimeline key={at.id} runId={at.id} /> : <RunList />;
}

export const WORKSPACES: readonly Workspace[] = [
  { id: 'home', label: 'Home', summary: 'What needs attention.', shows: () => false, View: ({ siteId }) => <Overview siteId={siteId} /> },
  {
    id: 'write',
    label: 'Write',
    summary: 'Pages across your sites, the editor, revisions.',
    shows: (to) => to.to === 'page' || to.to === 'pages',
    View: Write,
  },
  {
    id: 'create',
    label: 'Create',
    summary: 'A new page of any type, from a brief if you like.',
    shows: (to) => to.to === 'create',
    View: ({ siteId }) => <CreatePage siteId={siteId} />,
  },
  {
    id: 'review',
    label: 'Review',
    summary: 'Suggestions with their diffs: accept, reject, accept a whole run.',
    shows: (to) => to.to === 'review',
    View: Review,
  },
  { id: 'ai', label: 'AI', summary: 'Agent runs and their step timelines.', shows: (to) => to.to === 'run', View: Ai },
];

/** The workspace that shows `to`, if one does. */
export function workspaceFor(to: Destination): Workspace | undefined {
  return WORKSPACES.find((workspace) => workspace.shows(to));
}
