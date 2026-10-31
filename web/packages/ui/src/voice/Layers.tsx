// The layers of a site's voice, as the Voice tab shows them: the map of who
// reads which layer — the voice's distribution at a glance, a column with no
// mark being a reader it never reaches — and a card per layer with where it
// lives, where it is changed, what it says, its limits and its bans as the
// guard reads them. Each card is a section named by its title; a layer that is
// switched off for the page keeps its contrast and says so in words.
import { Accordion, Badge, Card, Code, Group, List, Spoiler, Stack, Table, Text, Title, VisuallyHidden } from '@mantine/core';
import type { ResolvedVoice, VoiceLayer } from '@zer0/api';
import { useId } from 'react';

import { LevelBadge } from '../LevelBadge';

const LIFTED: Record<string, string> = { book: 'switched off by its book', site: 'switched off by its site' };
// The map's mark for "reads it": deep blue on light, light blue on dark, above 3:1 either way (WCAG 1.4.11).
const READS = 'light-dark(var(--mantine-color-blue-9), var(--mantine-color-blue-3))';

export const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** What the layers hold, as the guard applies it: bans and warnings in force, what it skips, what is switched off. */
export function banTotals(layers: VoiceLayer[]) {
  const totals = { bans: 0, warnings: 0, skipped: 0, off: 0 };
  for (const layer of layers) {
    for (const ban of layer.bans) {
      if (!ban.valid) totals.skipped += 1;
      else if (!layer.active) totals.off += 1;
      else if (ban.level === 'error') totals.bans += 1;
      else totals.warnings += 1;
    }
  }
  return totals;
}

/** "13 bans, 5 warnings, 4 skipped": a ban the guard skips is not counted as one it applies. */
function banCount(layer: VoiceLayer): string {
  const live = layer.bans.filter((b) => b.valid);
  const errors = live.filter((b) => b.level === 'error').length;
  const skipped = layer.bans.length - live.length;
  return [errors ? plural(errors, 'ban', 'bans') : '', live.length - errors ? plural(live.length - errors, 'warning', 'warnings') : '', skipped ? `${skipped} skipped` : '']
    .filter(Boolean)
    .join(', ');
}

export function ReaderMap({ layers, readers }: { layers: VoiceLayer[]; readers: ResolvedVoice['readers'] }) {
  const unreached = readers.filter((r) => !layers.some((layer) => layer.readers.includes(r.key)));
  return (
    <Stack gap={4}>
      <Table.ScrollContainer minWidth={760}>
        <Table aria-label="Who reads which layer" withTableBorder withColumnBorders verticalSpacing={4} fz="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th scope="col" miw={200}>
                Layer
              </Table.Th>
              {readers.map((r) => (
                <Table.Th key={r.key} scope="col" ta="center" title={r.label}>
                  {r.name}
                </Table.Th>
              ))}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {layers.map((layer) => (
              <Table.Tr key={layer.key}>
                <Table.Th scope="row" fw={500}>
                  {layer.label}
                  {layer.active ? '' : ' (off here)'}
                </Table.Th>
                {readers.map((r) =>
                  layer.readers.includes(r.key) ? (
                    <Table.Td key={r.key} ta="center">
                      <Text span aria-hidden fw={700} style={{ color: READS }}>
                        ●
                      </Text>
                      <VisuallyHidden>reads it</VisuallyHidden>
                    </Table.Td>
                  ) : (
                    <Table.Td key={r.key} ta="center">
                      <Text span aria-hidden c="dimmed">
                        –
                      </Text>
                      <VisuallyHidden>does not</VisuallyHidden>
                    </Table.Td>
                  ),
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      {unreached.length ? (
        <Text size="sm">
          Never reached here: {unreached.map((r) => `${r.name} (${r.label})`).join('; ')}.
        </Text>
      ) : null}
      <Accordion variant="default" chevronPosition="left">
        <Accordion.Item value="readers">
          <Accordion.Control>What each reader is</Accordion.Control>
          <Accordion.Panel>
            <List size="sm">
              {readers.map((r) => (
                <List.Item key={r.key}>
                  <Text span fw={500}>
                    {r.name}
                  </Text>
                  : {r.label}
                </List.Item>
              ))}
            </List>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}

export function LayerCard({ layer }: { layer: VoiceLayer }) {
  const titleId = useId();
  const empty = !layer.hidden && !layer.guidance.length && !layer.bans.length && !layer.limits.max_length;
  return (
    <Card withBorder component="section" aria-labelledby={titleId} style={layer.active ? undefined : { borderStyle: 'dashed' }}>
      <Stack gap="xs">
        <Group justify="space-between" align="start">
          <Group gap="xs">
            <Badge variant="light">{layer.scope}</Badge>
            <Title order={5} id={titleId}>
              {layer.label}
            </Title>
          </Group>
          {layer.active ? null : <Badge color="gray.7">{LIFTED[layer.lifted_by] ?? 'switched off'}</Badge>}
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
                <Table aria-label={`${layer.label}: bans`} fz="sm">
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
                        <Table.Td>
                          {ban.valid ? (
                            <LevelBadge size="sm" level={ban.level} />
                          ) : (
                            <Group gap={6} wrap="nowrap" align="start">
                              <LevelBadge size="sm" level="skipped" />
                              <Text size="xs">{ban.why}</Text>
                            </Group>
                          )}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Accordion.Panel>
            </Accordion.Item>
          </Accordion>
        ) : null}
      </Stack>
    </Card>
  );
}
