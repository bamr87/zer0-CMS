// The studio's routes: each area's path, the editor and the run timeline
// under them, and an empty state for each area a later milestone builds.
// The workspaces themselves are @zer0/ui's; this file only places them, and
// turns the destinations they ask for (Destination) into paths.
import { Alert, Button, Group, Stack, Text, Title } from '@mantine/core';
import type { ApiClient } from '@zer0/api';
import { Overview, PageEditor, PageList, StudioProvider, SuggestionInbox, type Destination, type OpenStream } from '@zer0/ui';
import { useCallback, type ReactNode } from 'react';
import { Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router';

import { AiArea } from './ai/AiArea';
import { CreateArea } from './ai/CreateArea';
import { AREAS, type Area } from './areas';
import { SignedIn } from './auth';
import { Shell } from './Shell';
import { SiteProvider, useSite } from './site';

export function pathFor(to: Destination): string {
  switch (to.to) {
    case 'page':
      return to.tab ? `/write/${to.id}?tab=${to.tab}` : `/write/${to.id}`;
    case 'pages':
      return '/write';
    case 'create':
      return '/create';
    case 'run':
      return `/ai/runs/${to.id}`;
    case 'review':
      return to.runId ? `/review?run=${to.runId}` : '/review';
    case 'ai':
      return to.section && to.section !== 'runs' ? `/ai/${to.section}` : '/ai';
    case 'assistant':
      return `/ai/assistants/${to.id ?? 'new'}`;
    case 'pipeline':
      return `/ai/pipelines/${to.id ?? 'new'}`;
    case 'schema':
      return `/ai/schemas/${to.id ?? 'new'}`;
    case 'conversation':
      return `/ai/conversations/${to.id}`;
    case 'brief':
      return `/create/briefs/${to.id ?? 'new'}`;
    case 'briefs':
      return '/create/briefs';
  }
}

export function App({ api, stream }: { api: ApiClient; stream: OpenStream }) {
  const navigate = useNavigate();
  const go = useCallback((to: Destination) => void navigate(pathFor(to)), [navigate]);
  return (
    <StudioProvider api={api} stream={stream} go={go}>
      <SignedIn>
        {(person) => (
          <SiteProvider>
            <Routes>
              <Route element={<Shell person={person} />}>
                <Route index element={<Home />} />
                <Route path="write" element={<Write />} />
                <Route path="write/:id" element={<EditPage />} />
                <Route path="create/*" element={<CreateArea />} />
                <Route path="review" element={<Review />} />
                <Route path="ai/*" element={<AiArea />} />
                {AREAS.filter((area) => area.milestone).map((area) => (
                  <Route key={area.path} path={area.path.slice(1)} element={<Planned area={area} />} />
                ))}
                <Route path="*" element={<Section title="Not found">There is nothing at this address.</Section>} />
              </Route>
            </Routes>
          </SiteProvider>
        )}
      </SignedIn>
    </StudioProvider>
  );
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{title}</Title>
        {action}
      </Group>
      {children}
    </Stack>
  );
}

function Home() {
  const { siteId } = useSite();
  return (
    <Section title="Home">
      <Overview siteId={siteId} />
    </Section>
  );
}

function Write() {
  const { siteId } = useSite();
  const navigate = useNavigate();
  return (
    <Section title="Write" action={<Button onClick={() => void navigate('/create')}>New page</Button>}>
      <PageList siteId={siteId} />
    </Section>
  );
}

function EditPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  return <PageEditor key={id} pageId={Number(id)} tab={params.get('tab') === 'suggestions' ? 'suggestions' : undefined} />;
}

function Review() {
  const { siteId } = useSite();
  const [params] = useSearchParams();
  const runId = Number(params.get('run')) || undefined;
  return (
    <Section title={runId ? `Review run #${runId}` : 'Review'}>
      <SuggestionInbox siteId={runId ? undefined : siteId} runId={runId} />
    </Section>
  );
}

function Planned({ area }: { area: Area }) {
  return (
    <Section title={area.label}>
      <Text>{area.summary}</Text>
      <Alert color="gray" title="Not built yet">
        This area arrives with PLAN {area.milestone} (docs/plan/PLAN.md § 3). Everything it shows will also reach the VS Code
        extension.
      </Alert>
    </Section>
  );
}
