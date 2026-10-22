// A site's brand context — brand voice, style guide, writing examples, target
// keywords, internal-links map, competitor analysis and the rest of AIEO's
// context files — which every AIEO agent reads and the scorer takes keywords
// from; and where the site's content stands in AIEO's lifecycle, each stage
// a door to the workspace that does it (Ideas, Research, Create, Review).
import { Accordion, Alert, Button, Group, Paper, SimpleGrid, Stack, Text, Textarea, TagsInput, Title, UnstyledButton } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AieoBrandContext } from '@zer0/api';
import { useState } from 'react';

import { call, errorText } from '../call';
import { useApi, useGo, type Destination } from '../context';

const DOCUMENTS = [
  ['brand_voice', 'Brand voice'],
  ['style_guide', 'Style guide'],
  ['writing_examples', 'Writing examples'],
  ['target_keywords', 'Target keywords'],
  ['internal_links_map', 'Internal links map'],
  ['competitor_analysis', 'Competitor analysis'],
  ['seo_guidelines', 'SEO guidelines'],
  ['cro_best_practices', 'CRO best practices'],
  ['features', 'Product features'],
] as const;
type DocumentName = (typeof DOCUMENTS)[number][0];

export function Context({ siteId }: { siteId?: number }) {
  if (siteId === undefined) return <Alert color="gray">Choose a site in the header to see its context and lifecycle.</Alert>;
  return (
    <Stack>
      <Lifecycle siteId={siteId} />
      <BrandContext siteId={siteId} />
    </Stack>
  );
}

function Lifecycle({ siteId }: { siteId: number }) {
  const api = useApi();
  const go = useGo();
  const stages = useQuery({
    queryKey: ['aieo', 'lifecycle', siteId],
    queryFn: () => call(api.GET('/api/v2/aieo/lifecycle/', { params: { query: { site: siteId } } })),
  });
  if (stages.isError) return <Alert color="red">{errorText(stages.error)}</Alert>;
  const s = stages.data;
  if (!s) return null;
  const doors: [string, number, Destination][] = [
    ['Topics', s.topics, { to: 'ideas' }],
    ['Research', s.research, { to: 'research' }],
    ['Drafts', s.drafts, { to: 'briefs' }],
    ['Rewrites to review', s.rewrites, { to: 'review' }],
    ['Review required', s.review_required, { to: 'review' }],
    ['Published', s.published, { to: 'pages' }],
    ['Landing pages', s.landing_pages, { to: 'create' }],
  ];
  return (
    <Stack gap="xs">
      <Title order={4}>The lifecycle</Title>
      <SimpleGrid cols={{ base: 2, md: 4 }} aria-label="Lifecycle">
        {doors.map(([label, count, to]) => (
          <UnstyledButton key={label} onClick={() => go(to)}>
            <Paper withBorder p="sm">
              <Text size="xl" fw={700}>
                {count}
              </Text>
              <Text size="sm">{label}</Text>
            </Paper>
          </UnstyledButton>
        ))}
        <Paper withBorder p="sm">
          <Text size="xl" fw={700}>
            {s.average_score ?? '—'}
          </Text>
          <Text size="sm">Average score of {s.audits} audits</Text>
        </Paper>
      </SimpleGrid>
    </Stack>
  );
}

function BrandContext({ siteId }: { siteId: number }) {
  const api = useApi();
  const context = useQuery({
    queryKey: ['aieo', 'context', siteId],
    queryFn: () => call(api.GET('/api/v2/aieo/context/{site_id}/', { params: { path: { site_id: siteId } } })),
  });
  if (context.isError) return <Alert color="red">{errorText(context.error)}</Alert>;
  return context.data ? <ContextForm key={context.data.updated_at} siteId={siteId} saved={context.data} /> : null;
}

const listOf = (value: unknown, key: string): string[] => {
  const found = (value as Record<string, unknown> | null)?.[key];
  return Array.isArray(found) ? found.filter((v): v is string => typeof v === 'string') : [];
};

function ContextForm({ siteId, saved }: { siteId: number; saved: AieoBrandContext }) {
  const api = useApi();
  const qc = useQueryClient();
  const [docs, setDocs] = useState<Record<DocumentName, string>>(() =>
    Object.fromEntries(DOCUMENTS.map(([name]) => [name, saved[name] ?? ''])) as Record<DocumentName, string>,
  );
  const [competitors, setCompetitors] = useState(listOf(saved.competitors, 'competitors'));
  const [keywords, setKeywords] = useState(listOf(saved.competitors, 'keywords'));
  const [topics, setTopics] = useState(listOf(saved.competitors, 'topics'));
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PUT('/api/v2/aieo/context/{site_id}/', {
          params: { path: { site_id: siteId } },
          body: { ...docs, competitors: { competitors, keywords, topics } },
        }),
      ),
    onSuccess: () => {
      notifications.show({ message: 'Brand context saved' });
      void qc.invalidateQueries({ queryKey: ['aieo', 'context', siteId] });
    },
  });
  return (
    <Paper withBorder p="md" component="form" aria-label="Brand context" onSubmit={(e) => e.preventDefault()}>
      <Stack gap="sm">
        <Title order={4}>Brand context</Title>
        <Text size="sm" c="dimmed">
          What the AIEO agents read about this site. Target keywords: {saved.keywords.join(', ') || 'none yet'}.
        </Text>
        <Accordion variant="separated">
          {DOCUMENTS.map(([name, label]) => (
            <Accordion.Item key={name} value={name}>
              <Accordion.Control>{label}</Accordion.Control>
              <Accordion.Panel>
                <Textarea aria-label={label} autosize minRows={4} maxRows={16} value={docs[name]} onChange={(e) => setDocs({ ...docs, [name]: e.currentTarget.value })} />
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
        <TagsInput label="Competitors" value={competitors} onChange={setCompetitors} />
        <TagsInput label="Keywords" value={keywords} onChange={setKeywords} />
        <TagsInput label="Topics competitors cover" value={topics} onChange={setTopics} />
        <Group>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            Save the context
          </Button>
        </Group>
        {save.isError ? <Alert color="red">{errorText(save.error)}</Alert> : null}
      </Stack>
    </Paper>
  );
}
