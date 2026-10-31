// A site's voice (ADR 0010, step V0): for a page — and, for a post, a channel —
// every layer of voice that holds, in the order the brand guard applies them
// (the built-in bans, each active brand rules snippet, the site's settings,
// AIEO's brand context, a book's style guide, a chapter's tone), with where
// each lives, where a person changes it and who reads it; which of the
// assistants the person may run here could ask for it; what the brand.rules
// tool tells an agent; and the guard's findings on a text under that
// resolution, at once and without a model. Read-only: the voice is changed
// where each layer says, and nothing here changes what a writer is told.
import { Accordion, Alert, Badge, Button, Card, Code, Group, List, Loader, Paper, Select, Spoiler, Stack, Table, Text, Textarea, Title } from '@mantine/core';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { ResolvedVoice, VoiceFinding, VoiceLayer } from '@zer0/api';
import { useState } from 'react';

import { oneClick } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';
import { useChannels } from '../distribution/shared';
import { PagePicker } from '../PagePicker';

const LIFTED: Record<string, string> = { book: 'switched off by its book', site: 'switched off by its site' };
const LEVEL_COLOR: Record<string, string> = { error: 'red', warning: 'yellow', info: 'gray' };

export function Voice({ siteId }: { siteId: number }) {
  const api = useApi();
  const [page, setPage] = useState<number | null>(null);
  const [channel, setChannel] = useState<string | null>(null);
  const channels = useChannels(siteId);
  const query = { page: page ?? undefined, channel: channel ?? undefined };
  const resolved = useQuery({
    queryKey: ['site-voice', siteId, query],
    queryFn: () => call(api.GET('/api/v2/sites/{id}/voice/resolved/', { params: { path: { id: siteId }, query } })),
  });
  return (
    <Stack>
      <Text size="sm" c="dimmed">
        What this site’s voice is today, composed from every place the platform keeps one, and who reads each part. It is changed where each layer says.
      </Text>
      <Group grow align="start">
        <PagePicker label="For a page" description="Optional: a book’s chapter adds its book and its tone" siteId={siteId} value={page} onChange={setPage} />
        <Select
          label="For a post to a channel"
          description="Optional: the guard a distribution post meets"
          clearable
          placeholder="No channel"
          data={(channels.data?.results ?? []).filter((c) => c.site === siteId).map((c) => ({ value: c.id, label: `${c.name} (${c.kind_label})` }))}
          value={channel}
          onChange={setChannel}
        />
      </Group>
      {resolved.isPending ? <Loader /> : null}
      {resolved.isError ? <Alert color="red">{errorText(resolved.error)}</Alert> : null}
      {resolved.data ? <Resolution voice={resolved.data} /> : null}
      <TestText siteId={siteId} page={page} channel={channel} />
    </Stack>
  );
}

function Resolution({ voice }: { voice: ResolvedVoice }) {
  const readers = Object.fromEntries(voice.readers.map((r) => [r.key, r.label]));
  const asking = voice.assistants.filter((a) => a.reads_voice);
  return (
    <Stack>
      <Alert color="blue" title="Who is told this voice">
        <Text size="sm">
          A model is told the voice only when it asks, through the brand.rules tool. {asking.length} of the {voice.assistants.length} assistants you may run here list that tool
          {asking.length ? ` (${asking.map((a) => a.name).join(', ')})` : ''}; the editor’s AI panel gives an assistant its own instructions and nothing else. The gates — the guard,
          the brand review, the evals and the distribution guard — hold every page to the bans below.
        </Text>
      </Alert>
      <Group justify="space-between">
        <Title order={4}>
          {voice.layers.length} {voice.layers.length === 1 ? 'layer' : 'layers'}
          {voice.page ? ` for “${voice.page.title}”` : ''}
          {voice.channel ? ` posted to ${voice.channel.name}` : ''}
        </Title>
        <Text size="xs" c="dimmed" title={voice.digest}>
          digest {voice.digest.slice(0, 12)}
        </Text>
      </Group>
      {voice.layers.map((layer) => (
        <LayerCard key={layer.key} layer={layer} readers={readers} />
      ))}
      <Accordion variant="separated">
        <Accordion.Item value="told">
          <Accordion.Control>What brand.rules tells an agent working here</Accordion.Control>
          <Accordion.Panel>
            <Stack gap="xs">
              <Text size="sm">
                {voice.told.style_guides.length} style {voice.told.style_guides.length === 1 ? 'guide' : 'guides'}, and these banned phrases by name:
              </Text>
              <Text size="sm">{voice.told.banned.map((name) => name ?? '(a ban with no name)').join(' · ') || 'none'}</Text>
            </Stack>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "13 bans, 5 warnings, 4 skipped": a ban the guard skips is not counted as one it applies. */
function banCount(layer: VoiceLayer): string {
  const live = layer.bans.filter((b) => b.valid);
  const errors = live.filter((b) => b.level === 'error').length;
  const skipped = layer.bans.length - live.length;
  return [errors ? plural(errors, 'ban', 'bans') : '', live.length - errors ? plural(live.length - errors, 'warning', 'warnings') : '', skipped ? `${skipped} skipped` : '']
    .filter(Boolean)
    .join(', ');
}

function LayerCard({ layer, readers }: { layer: VoiceLayer; readers: Record<string, string> }) {
  const empty = !layer.hidden && !layer.guidance.length && !layer.bans.length && !layer.limits.max_length;
  return (
    <Card withBorder aria-label={layer.label} opacity={layer.active ? 1 : 0.7}>
      <Stack gap="xs">
        <Group justify="space-between" align="start">
          <Group gap="xs">
            <Badge variant="light">{layer.scope}</Badge>
            <Title order={5}>{layer.label}</Title>
          </Group>
          {layer.active ? null : <Badge color="gray">{LIFTED[layer.lifted_by] ?? 'switched off'}</Badge>}
        </Group>
        <Text size="xs" c="dimmed">
          {layer.source} · {layer.edit ? `change it in ${layer.edit}` : 'it is code: no screen changes it'}
        </Text>
        {layer.hidden ? <Text size="sm">Only the site’s editors see what it says.</Text> : null}
        {empty ? (
          <Text size="sm" c="dimmed">
            Nothing is set here yet.
          </Text>
        ) : null}
        {layer.guidance.map((g) => (
          <Stack key={g.label} gap={2}>
            <Text size="sm" fw={500}>
              {g.label}
            </Text>
            <Spoiler maxHeight={96} showLabel="Show all" hideLabel="Show less">
              <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
                {g.text}
              </Text>
            </Spoiler>
          </Stack>
        ))}
        {layer.limits.max_length ? (
          <Text size="sm">
            At most {layer.limits.max_length.toLocaleString()} characters{layer.limits.max_escaped_length ? ', counted once escaped for LinkedIn' : ''}; the hook must land before the fold at{' '}
            {layer.limits.fold} characters.
          </Text>
        ) : null}
        {layer.bans.length ? (
          <Accordion variant="contained">
            <Accordion.Item value="bans">
              <Accordion.Control>{banCount(layer)}</Accordion.Control>
              <Accordion.Panel>
                <Table aria-label={`${layer.label}: bans`}>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Phrase</Table.Th>
                      <Table.Th>Pattern</Table.Th>
                      <Table.Th>Level</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {layer.bans.map((ban, at) => (
                      <Table.Tr key={`${ban.name}-${at}`}>
                        <Table.Td>{ban.name || '(no name)'}</Table.Td>
                        <Table.Td>
                          <Code>{ban.pattern}</Code>
                        </Table.Td>
                        <Table.Td>{ban.valid ? <Badge color={LEVEL_COLOR[ban.level]}>{ban.level}</Badge> : <Badge color="gray">skipped: {ban.why}</Badge>}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        ) : null}
        <Stack gap={2}>
          <Text size="xs" fw={500}>
            Read by
          </Text>
          <List size="xs">
            {layer.readers.map((key) => (
              <List.Item key={key}>{readers[key] ?? key}</List.Item>
            ))}
          </List>
        </Stack>
      </Stack>
    </Card>
  );
}

function TestText({ siteId, page, channel }: { siteId: number; page: number | null; channel: string | null }) {
  const api = useApi();
  const [text, setText] = useState('');
  // The findings are shown only under the page and channel they were found under: change either and they go.
  const test = useMutation({
    mutationFn: (scope: { page: number | null; channel: string | null }) =>
      call(api.POST('/api/v2/sites/{id}/voice/test/', { params: { path: { id: siteId } }, body: { text, page: scope.page ?? undefined, channel: scope.channel ?? undefined } })),
  });
  const current = test.variables?.page === page && test.variables.channel === channel;
  return (
    <Paper withBorder p="md" component="form" aria-label="Test a text" onSubmit={(e) => e.preventDefault()}>
      <Stack gap="xs">
        <Title order={4}>Test a text</Title>
        <Text size="sm" c="dimmed">
          The brand guard’s findings under this voice{channel ? ', as a post to the channel' : page ? ', as text on the page' : ''}. No model is asked. The guard is a floor: it cannot see a voice, an invented claim
          or a second call to action.
        </Text>
        <Textarea label="Text" autosize minRows={3} maxLength={20000} value={text} onChange={(e) => setText(e.currentTarget.value)} />
        <Group>
          <Button onClick={oneClick(() => test.mutate({ page, channel }))} loading={test.isPending} disabled={!text.trim()}>
            Test it
          </Button>
        </Group>
        {test.isError && current ? <Alert color="red">{errorText(test.error)}</Alert> : null}
        {test.data && current ? <Findings findings={test.data.findings} /> : null}
      </Stack>
    </Paper>
  );
}

function Findings({ findings }: { findings: VoiceFinding[] }) {
  const blocking = findings.filter((f) => f.level === 'error');
  return (
    <Stack gap={4} aria-label="Findings">
      <Text size="sm" fw={500}>
        {blocking.length ? `${blocking.length} ${blocking.length === 1 ? 'error' : 'errors'} — the guard would refuse it` : 'No errors — the guard would let it through'}
      </Text>
      {findings.map((f, at) => (
        <Group key={at} gap="xs" wrap="nowrap" align="start">
          <Badge color={LEVEL_COLOR[f.level]}>{f.level}</Badge>
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {f.message}
          </Text>
        </Group>
      ))}
    </Stack>
  );
}
