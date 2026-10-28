// The AI area (/ai, PLAN G8): agent runs, assistants, pipelines, output
// schemas, conversations, providers, the model catalog and automations (G16)
// — one tab each, every tab a route — and one row of each opened under it.
// The workspaces are @zer0/ui's; this file only places them, as App.tsx does
// for the others.
import { Stack, Tabs, Title } from '@mantine/core';
import {
  AssistantEditor,
  AssistantList,
  AutomationEditor,
  AutomationList,
  ConversationList,
  ConversationThread,
  ModelCatalog,
  PipelineEditor,
  PipelineList,
  ProviderList,
  RunList,
  RunTimeline,
  SchemaEditor,
  SchemaList,
  type AiSection,
} from '@zer0/ui';
import type { ReactNode } from 'react';
import { Route, Routes, useLocation, useNavigate, useParams } from 'react-router';

import { useSite } from '../site';

const SECTIONS: { value: AiSection; label: string }[] = [
  { value: 'runs', label: 'Runs' },
  { value: 'assistants', label: 'Assistants' },
  { value: 'pipelines', label: 'Pipelines' },
  { value: 'schemas', label: 'Output schemas' },
  { value: 'conversations', label: 'Conversations' },
  { value: 'providers', label: 'Providers' },
  { value: 'models', label: 'Models' },
  { value: 'automations', label: 'Automations' },
];

/**
 * Section tabs that are routes — `base` + `/` + the section, the first being
 * `base` itself — around the routes they switch, which render in the active
 * tab's panel (so the content is the panel its tab names).
 */
export function SectionTabs(props: { base: string; sections: { value: string; label: string }[]; label: string; children: ReactNode }) {
  const { base, sections, label, children } = props;
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const first = sections[0]?.value;
  const current = pathname.slice(base.length).split('/')[1] || first;
  const pick = (next: string | null) => void navigate(next === first || !next ? base : `${base}/${next}`);
  return (
    <Tabs value={current} onChange={pick} keepMounted={false}>
      <Tabs.List aria-label={label}>
        {sections.map((s) => (
          <Tabs.Tab key={s.value} value={s.value}>
            {s.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      {current ? (
        <Tabs.Panel value={current} pt="md">
          {children}
        </Tabs.Panel>
      ) : null}
    </Tabs>
  );
}

/** The `:id` of a route, or undefined for `new`. */
function WithId({ children }: { children: (id: string | undefined) => ReactNode }) {
  const { id } = useParams();
  return children(id === 'new' ? undefined : id);
}

export function AiArea() {
  const { siteId } = useSite();
  return (
    <Stack>
      <Title order={2}>AI</Title>
      <SectionTabs base="/ai" sections={SECTIONS} label="AI sections">
        <Routes>
          <Route index element={<RunList />} />
          <Route path="runs" element={<RunList />} />
          <Route path="runs/:id" element={<WithId>{(id) => <RunTimeline key={id} runId={Number(id)} />}</WithId>} />
          <Route path="assistants" element={<AssistantList />} />
          <Route path="assistants/:id" element={<WithId>{(id) => <AssistantEditor key={id ?? 'new'} id={id} />}</WithId>} />
          <Route path="pipelines" element={<PipelineList />} />
          <Route path="pipelines/:id" element={<WithId>{(id) => <PipelineEditor key={id ?? 'new'} id={id} />}</WithId>} />
          <Route path="schemas" element={<SchemaList />} />
          <Route path="schemas/:id" element={<WithId>{(id) => <SchemaEditor key={id ?? 'new'} id={id} />}</WithId>} />
          <Route path="conversations" element={<ConversationList siteId={siteId} />} />
          <Route path="conversations/:id" element={<WithId>{(id) => <ConversationThread key={id} id={id ?? ''} />}</WithId>} />
          <Route path="providers" element={<ProviderList />} />
          <Route path="models" element={<ModelCatalog />} />
          <Route path="automations" element={<AutomationList siteId={siteId} />} />
          <Route path="automations/:id" element={<WithId>{(id) => <AutomationEditor key={id ?? 'new'} id={id} />}</WithId>} />
        </Routes>
      </SectionTabs>
    </Stack>
  );
}
