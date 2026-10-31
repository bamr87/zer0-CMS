// A site's voice (ADR 0010, step V0), the Voice tab of a site's page: for a
// page — and, for a post, a channel — every layer of voice that holds, in the
// order the brand guard applies them (the built-in bans, each active brand
// rules snippet, the site's settings, AIEO's brand context, a book's style
// guide, a chapter's tone, a channel's limits); who reads which layer, as a
// map; which of the assistants the person may run here could ask for it; what
// the brand.rules tool tells an agent; and, beside the layers, a text tested
// against the guard under that resolution. Read-only: each layer says where it is
// changed, and nothing here changes what a writer is told.
//
// The page and channel chosen are the scope. A host may hold it (SiteView
// does, so it survives a change of tab) or leave it to the tab. While a new
// scope resolves, the last resolution stays on screen.
import { Accordion, Alert, Button, CopyButton, Grid, Group, Loader, Select, SimpleGrid, Stack, Text, Title } from '@mantine/core';
import { useUncontrolled } from '@mantine/hooks';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import type { ResolvedVoice } from '@zer0/api';

import { call, errorText } from '../call';
import { useApi } from '../context';
import { useChannels } from '../distribution/shared';
import { PagePicker } from '../PagePicker';
import { banTotals, LayerCard, plural, ReaderMap } from './Layers';
import { TestText } from './TestText';

export interface VoiceScope {
  page: number | null;
  channel: string | null;
}

const NO_SCOPE: VoiceScope = { page: null, channel: null };

export function Voice({ siteId, scope, onScopeChange }: { siteId: number; scope?: VoiceScope; onScopeChange?: (scope: VoiceScope) => void }) {
  const api = useApi();
  const [current, setCurrent] = useUncontrolled<VoiceScope>({ value: scope, defaultValue: NO_SCOPE, onChange: onScopeChange });
  const { page, channel } = current;
  const channels = useChannels(siteId);
  const query = { page: page ?? undefined, channel: channel ?? undefined };
  const resolved = useQuery({
    queryKey: ['site-voice', siteId, query],
    queryFn: () => call(api.GET('/api/v2/sites/{id}/voice/resolved/', { params: { path: { id: siteId }, query } })),
    placeholderData: keepPreviousData,
  });
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        What this site’s voice is today, composed from every place the platform keeps one, and who reads each part. It is changed where each layer says.
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <PagePicker
          label="For a page"
          description="Optional: a book’s chapter adds its book and its tone"
          siteId={siteId}
          value={page}
          onChange={(next) => setCurrent({ ...current, page: next })}
        />
        <Select
          label="For a post to a channel"
          description="Optional: the guard a distribution post meets"
          clearable
          placeholder="No channel"
          data={(channels.data?.results ?? []).filter((c) => c.site === siteId).map((c) => ({ value: c.id, label: `${c.name} (${c.kind_label})` }))}
          value={channel}
          onChange={(next) => setCurrent({ ...current, channel: next })}
        />
      </SimpleGrid>
      {resolved.isPending ? <Loader aria-label="Loading the voice" /> : null}
      {resolved.isError ? <Alert color="red">{errorText(resolved.error)}</Alert> : null}
      {resolved.data ? <Overview voice={resolved.data} refreshing={resolved.isFetching} /> : null}
      <Grid gap="lg">
        <Grid.Col span={{ base: 12, lg: 8 }}>{resolved.data ? <LayerList voice={resolved.data} /> : null}</Grid.Col>
        <Grid.Col span={{ base: 12, lg: 4 }}>
          <div style={{ position: 'sticky', top: 'calc(var(--app-shell-header-offset, 0px) + var(--mantine-spacing-md))' }}>
            <TestText siteId={siteId} page={page} channel={channel} />
          </div>
        </Grid.Col>
      </Grid>
    </Stack>
  );
}

/** Who is told the voice, what it holds, and the map of who reads which layer: the whole width, above the layers. */
function Overview({ voice, refreshing }: { voice: ResolvedVoice; refreshing: boolean }) {
  const asking = voice.assistants.filter((a) => a.reads_voice);
  const totals = banTotals(voice.layers);
  const counts = [
    plural(voice.layers.length, 'layer', 'layers'),
    plural(totals.bans, 'ban', 'bans') + ' in force',
    plural(totals.warnings, 'warning', 'warnings'),
    totals.skipped ? `${totals.skipped} skipped` : '',
    totals.off ? `${totals.off} switched off here` : '',
  ].filter(Boolean);
  return (
    <Stack>
      <Alert color="blue" title="Who is told this voice">
        <Text size="sm">
          A model is told the voice only when it asks, through the brand.rules tool. {asking.length} of the {voice.assistants.length} assistants you may run here list that tool
          {asking.length ? ` (${asking.map((a) => a.name).join(', ')})` : ''}; the editor’s AI panel gives an assistant its own instructions and nothing else. The gates — the guard,
          the brand review, the evals and the distribution guard — hold every page to the bans below.
        </Text>
      </Alert>
      <Group justify="space-between" align="center" wrap="nowrap">
        <Stack gap={2}>
          <Title order={4}>
            The voice
            {voice.page ? ` for “${voice.page.title}”` : ' of the site'}
            {voice.channel ? `, posted to ${voice.channel.name}` : ''}
          </Title>
          <Text size="sm" c="dimmed">
            {counts.join(' · ')}
          </Text>
        </Stack>
        <Group gap="xs" wrap="nowrap">
          {refreshing ? <Loader size="xs" aria-label="Updating the voice" /> : null}
          <CopyButton value={voice.digest}>
            {({ copied, copy }) => (
              <Button variant="subtle" size="compact-xs" onClick={copy} title={voice.digest} aria-label={`Copy the digest ${voice.digest}`}>
                {copied ? 'Copied' : `digest ${voice.digest.slice(0, 12)}`}
              </Button>
            )}
          </CopyButton>
        </Group>
      </Group>
      <ReaderMap layers={voice.layers} readers={voice.readers} />
    </Stack>
  );
}

/** Each layer in the guard's order, then what brand.rules tells an agent; beside them, the tester. */
function LayerList({ voice }: { voice: ResolvedVoice }) {
  return (
    <Stack>
      {voice.layers.map((layer) => (
        <LayerCard key={layer.key} layer={layer} />
      ))}
      <Accordion variant="separated">
        <Accordion.Item value="told">
          <Accordion.Control>What brand.rules tells an agent working here</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="xs">
              <Text size="sm">
                {plural(voice.told.style_guides.length, 'style guide', 'style guides')}, and these banned phrases by name:
              </Text>
              <Text size="sm">{voice.told.banned.map((name) => name ?? '(a ban with no name)').join(' · ') || 'none'}</Text>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
