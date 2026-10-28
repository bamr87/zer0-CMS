// The workspace registry: the workspaces @zer0/ui offers, as data a host
// renders without knowing any of them (PLAN G10, ADR 0006 decision 9). The
// VS Code extension's dashboard shows one tab per entry and its AI view opens
// `ai`, so a workspace added here reaches the extension with no host code; the
// studio places the same components on its routes (web/studio/src/App.tsx).
// Every destination a workspace can ask for has a home here (`HOME`, which the
// type checker holds to the whole `Destination` union), so a host turns
// `go(to)` into "this workspace, at that destination" without a router of its
// own — and a destination added to context.tsx without a home fails the build.
import { Button, Group, Stack, Tabs } from '@mantine/core';
import { useState, type ReactNode } from 'react';

import {
  AssistantEditor,
  AssistantList,
  BriefList,
  BriefWorkspace,
  ConversationList,
  ConversationThread,
  ModelCatalog,
  PipelineEditor,
  PipelineList,
  ProviderList,
  SchemaEditor,
  SchemaList,
} from './ai';
import { BookShelf } from './books/BookShelf';
import { BookView } from './books/BookView';
import { ChapterWriter } from './books/ChapterWriter';
import { useGo, type AiSection, type Destination } from './context';
import { CreatePage } from './CreatePage';
import { Distribution } from './distribution/Distribution';
import { IdeasWorkspace } from './ideas/IdeasWorkspace';
import { Newsroom } from './newsroom/Newsroom';
import { ClaimCheckView } from './outbox/ClaimCheckView';
import { OutboxDesk } from './outbox/OutboxDesk';
import { TrialView } from './outbox/TrialView';
import { Overview } from './Overview';
import { PageEditor } from './PageEditor';
import { PageList } from './PageList';
import { ResearchWorkspace } from './research/ResearchWorkspace';
import { SourceView } from './research/SourceView';
import { RunList, RunTimeline } from './RunTimeline';
import { JobLog } from './sites/JobLog';
import { SitesWorkspace } from './sites/SitesWorkspace';
import { SiteView } from './sites/SiteView';
import { SuggestionInbox } from './SuggestionInbox';

export interface WorkspaceProps {
  /** The site the host works in; undefined is every site. */
  siteId?: number;
  /** What to show; undefined is where the workspace starts. */
  at?: Destination;
}

export type WorkspaceId =
  | 'home'
  | 'write'
  | 'create'
  | 'ideas'
  | 'research'
  | 'newsroom'
  | 'books'
  | 'review'
  | 'ai'
  | 'outbox'
  | 'sites'
  | 'distribution';

export interface Workspace {
  id: WorkspaceId;
  label: string;
  summary: string;
  /** Whether this workspace is where `to` is shown. */
  shows: (to: Destination) => boolean;
  View: (props: WorkspaceProps) => ReactNode;
}

/** The workspace each destination is shown in — the studio's area for the same path (web/studio/src/App.tsx). */
export const HOME: { readonly [To in Destination['to']]: WorkspaceId } = {
  page: 'write',
  pages: 'write',
  create: 'create',
  briefs: 'create',
  brief: 'create',
  ideas: 'ideas',
  research: 'research',
  source: 'research',
  newsroom: 'newsroom',
  story: 'newsroom',
  books: 'books',
  book: 'books',
  chapter: 'books',
  review: 'review',
  run: 'ai',
  ai: 'ai',
  assistant: 'ai',
  pipeline: 'ai',
  schema: 'ai',
  conversation: 'ai',
  outbox: 'outbox',
  trial: 'outbox',
  'claim-check': 'outbox',
  sites: 'sites',
  site: 'sites',
  job: 'sites',
  distribution: 'distribution',
  'distribution-post': 'distribution',
  channel: 'distribution',
};

/**
 * A workspace's own sections as tabs, as the studio's areas have them (each a
 * route there). The section follows the destination the host hands the
 * workspace — each `go` is a new destination — and a tab switches it in place.
 */
function useSection<T extends string>(at: Destination | undefined, sectionOf: (to: Destination) => T | undefined, first: T) {
  const [section, setSection] = useState<T>((at && sectionOf(at)) ?? first);
  const [seen, setSeen] = useState(at);
  if (at !== seen) {
    setSeen(at);
    const next = at && sectionOf(at);
    if (next) setSection(next);
  }
  return [section, setSection] as const;
}

function Sections<T extends string>(props: {
  label: string;
  sections: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  children: ReactNode;
}) {
  const { label, sections, value, onChange, children } = props;
  return (
    <Tabs value={value} onChange={(next) => next && onChange(next as T)} keepMounted={false}>
      <Tabs.List aria-label={label}>
        {sections.map((s) => (
          <Tabs.Tab key={s.value} value={s.value}>
            {s.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      <Tabs.Panel value={value} pt="md">
        {children}
      </Tabs.Panel>
    </Tabs>
  );
}

function Write({ siteId, at }: WorkspaceProps) {
  const go = useGo();
  if (at?.to === 'page') return <PageEditor key={at.id} pageId={at.id} tab={at.tab} />;
  return (
    <Stack>
      <Group justify="flex-end">
        <Button onClick={() => go({ to: 'create' })}>New page</Button>
      </Group>
      <PageList siteId={siteId} />
    </Stack>
  );
}

type CreateSection = 'page' | 'briefs' | 'conversations';
const CREATE_SECTIONS: readonly { value: CreateSection; label: string }[] = [
  { value: 'page', label: 'A page' },
  { value: 'briefs', label: 'Briefs' },
  { value: 'conversations', label: 'Conversations' },
];
const createSection = (to: Destination): CreateSection | undefined =>
  to.to === 'create' ? 'page' : to.to === 'briefs' || to.to === 'brief' ? 'briefs' : undefined;

/** Create (studio: /create): a page of a type, a brief for AI to write (G8), and conversations to think a piece through. */
function Create({ siteId, at }: WorkspaceProps) {
  const [section, setSection] = useSection(at, createSection, 'page');
  const brief = at?.to === 'brief' && section === 'briefs' ? at : undefined;
  return (
    <Sections label="What to create" sections={CREATE_SECTIONS} value={section} onChange={setSection}>
      {section === 'page' ? <CreatePage siteId={siteId} /> : null}
      {section === 'briefs' ? brief ? <BriefWorkspace key={brief.id ?? 'new'} id={brief.id} siteId={siteId} /> : <BriefList siteId={siteId} /> : null}
      {section === 'conversations' ? <ConversationList siteId={siteId} /> : null}
    </Sections>
  );
}

function Review({ siteId, at }: WorkspaceProps) {
  const runId = at?.to === 'review' ? at.runId : undefined;
  return <SuggestionInbox key={runId} siteId={runId ? undefined : siteId} runId={runId} />;
}

const AI_SECTIONS: readonly { value: AiSection; label: string }[] = [
  { value: 'runs', label: 'Runs' },
  { value: 'assistants', label: 'Assistants' },
  { value: 'pipelines', label: 'Pipelines' },
  { value: 'schemas', label: 'Output schemas' },
  { value: 'conversations', label: 'Conversations' },
  { value: 'providers', label: 'Providers' },
  { value: 'models', label: 'Models' },
];
const AI_ROWS: Partial<Record<Destination['to'], AiSection>> = {
  run: 'runs',
  assistant: 'assistants',
  pipeline: 'pipelines',
  schema: 'schemas',
  conversation: 'conversations',
};
const aiSection = (to: Destination): AiSection | undefined => (to.to === 'ai' ? (to.section ?? 'runs') : AI_ROWS[to.to]);

/** The AI area (G8): agent runs, assistants, pipelines, output schemas, conversations, providers and models, a row of each opened in its section. */
function Ai({ siteId, at }: WorkspaceProps) {
  const [section, setSection] = useSection(at, aiSection, 'runs');
  // A row is shown while its section is: a tab away and back is the section's list.
  const row = at && at.to !== 'ai' && aiSection(at) === section ? at : undefined;
  let view: ReactNode;
  if (row?.to === 'run') view = <RunTimeline key={row.id} runId={row.id} />;
  else if (row?.to === 'assistant') view = <AssistantEditor key={row.id ?? 'new'} id={row.id} />;
  else if (row?.to === 'pipeline') view = <PipelineEditor key={row.id ?? 'new'} id={row.id} />;
  else if (row?.to === 'schema') view = <SchemaEditor key={row.id ?? 'new'} id={row.id} />;
  else if (row?.to === 'conversation') view = <ConversationThread key={row.id} id={row.id} />;
  else if (section === 'assistants') view = <AssistantList />;
  else if (section === 'pipelines') view = <PipelineList />;
  else if (section === 'schemas') view = <SchemaList />;
  else if (section === 'conversations') view = <ConversationList siteId={siteId} />;
  else if (section === 'providers') view = <ProviderList />;
  else if (section === 'models') view = <ModelCatalog />;
  else view = <RunList />;
  return (
    <Sections label="AI sections" sections={AI_SECTIONS} value={section} onChange={setSection}>
      {view}
    </Sections>
  );
}

function Research({ siteId, at }: WorkspaceProps) {
  // No bookmarklet: it opens the studio in a browser, and only the studio knows its own address.
  if (at?.to === 'source') return <SourceView key={at.id} sourceId={at.id} />;
  return <ResearchWorkspace siteId={siteId} />;
}

function Books({ at }: WorkspaceProps) {
  if (at?.to === 'chapter') return <ChapterWriter key={at.id} bookId={at.book} chapterId={at.id} />;
  if (at?.to === 'book') return <BookView key={at.id} bookId={at.id} />;
  return <BookShelf />;
}

function Outbox({ at }: WorkspaceProps) {
  if (at?.to === 'trial') return <TrialView key={at.id} trialId={at.id} />;
  if (at?.to === 'claim-check') return <ClaimCheckView key={at.id} checkId={at.id} />;
  return <OutboxDesk tab={at?.to === 'outbox' ? at.tab : undefined} />;
}

function Sites({ at }: WorkspaceProps) {
  if (at?.to === 'site') return <SiteView key={at.id} siteId={at.id} />;
  if (at?.to === 'job') return <JobLog key={at.id} jobId={at.id} />;
  return <SitesWorkspace />;
}

function DistributionWorkspace({ siteId, at }: WorkspaceProps) {
  // `connecting` is the studio's: LinkedIn's consent screen returns the person to the studio in their browser.
  return (
    <Distribution
      siteId={siteId}
      tab={at?.to === 'distribution' ? at.tab : undefined}
      postId={at?.to === 'distribution-post' ? at.id : undefined}
      channelId={at?.to === 'channel' ? at.id : undefined}
    />
  );
}

const showing = (id: WorkspaceId) => (to: Destination) => HOME[to.to] === id;

/** In the studio's navigation order (web/studio/src/areas.ts), less the areas a later milestone builds. */
export const WORKSPACES: readonly Workspace[] = [
  { id: 'home', label: 'Home', summary: 'What needs attention.', shows: showing('home'), View: ({ siteId }) => <Overview siteId={siteId} /> },
  { id: 'write', label: 'Write', summary: 'Pages across your sites, the editor, revisions.', shows: showing('write'), View: Write },
  {
    id: 'create',
    label: 'Create',
    summary: 'A new page of any type, a brief for AI to write, a conversation.',
    shows: showing('create'),
    View: Create,
  },
  {
    id: 'ideas',
    label: 'Ideas',
    summary: 'Boards, brainstorm sessions, and promoting an idea to a brief.',
    shows: showing('ideas'),
    View: ({ siteId }) => <IdeasWorkspace siteId={siteId} />,
  },
  {
    id: 'research',
    label: 'Research',
    summary: 'Sources and collections, capture, questions over sources, fact-checks.',
    shows: showing('research'),
    View: Research,
  },
  {
    id: 'newsroom',
    label: 'Newsroom',
    summary: 'Desks, the story budget, the calendar, assignments, fronts, corrections, newsletters.',
    shows: showing('newsroom'),
    View: ({ siteId, at }) => <Newsroom siteId={siteId} storyId={at?.to === 'story' ? at.id : undefined} />,
  },
  {
    id: 'books',
    label: 'Books',
    summary: 'Books, outlines, chapters, characters, continuity, manuscripts.',
    shows: showing('books'),
    View: Books,
  },
  {
    id: 'review',
    label: 'Review',
    summary: 'Suggestions with their diffs: accept, reject, accept a whole run.',
    shows: showing('review'),
    View: Review,
  },
  {
    id: 'ai',
    label: 'AI',
    summary: 'Agent runs, assistants, pipelines, output schemas, conversations, providers and models.',
    shows: showing('ai'),
    View: Ai,
  },
  {
    id: 'outbox',
    label: 'Outbox',
    summary: 'The belt of handoffs between pipeline stations, arena trials, the claim desk and its calibration.',
    shows: showing('outbox'),
    View: Outbox,
  },
  {
    id: 'sites',
    label: 'Sites',
    summary: 'The site registry and settings, sync, write-back and the doctor, and their jobs.',
    shows: showing('sites'),
    View: Sites,
  },
  {
    id: 'distribution',
    label: 'Distribution',
    summary: 'Channels, the queue, the ledger, statistics.',
    shows: showing('distribution'),
    View: DistributionWorkspace,
  },
];

/** The workspace that shows `to`, if one does. */
export function workspaceFor(to: Destination): Workspace | undefined {
  return WORKSPACES.find((workspace) => workspace.shows(to));
}
