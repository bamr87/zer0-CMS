// A score and its breakdown: the citability score and grade, the five
// dimensions as a radar and as bars, each pattern with its evidence and
// recommendation, the gaps worst first, the anti-pattern penalties, and — from
// a model's evaluation — the assessment, the executive summary, the priority
// actions and before/after improvements. `compact` shows the editor's panel's
// share: the bars without the radar, the first gaps, no details.
import { Accordion, Alert, Badge, Group, List, Paper, Progress, RingProgress, Stack, Table, Text, Title } from '@mantine/core';

import { Radar } from './Radar';
import { DIMENSION_LABELS, DIMENSIONS, gradeColor, label, type Scored } from './score';

const SEVERITY: Record<string, string> = { high: 'red', medium: 'orange', low: 'yellow' };

export function ScoreCard({ scored, compact = false }: { scored: Scored; compact?: boolean }) {
  return (
    <Stack gap="sm" aria-label="Citability score">
      <Group align="center" gap="lg">
        <RingProgress
          size={compact ? 84 : 110}
          thickness={compact ? 8 : 10}
          roundCaps
          sections={[{ value: Math.max(0, Math.min(100, scored.score)), color: gradeColor(scored.grade) }]}
          label={
            <Text ta="center" fw={700} size={compact ? 'md' : 'xl'}>
              {Math.round(scored.score * 10) / 10}
            </Text>
          }
        />
        <Stack gap={4}>
          <Group gap="xs">
            <Badge size="lg" color={gradeColor(scored.grade)}>
              Grade {scored.grade || '—'}
            </Badge>
            <Badge variant="light" color={scored.method === 'ai' ? 'grape' : 'gray'}>
              {scored.method === 'ai' ? "A model's evaluation" : 'Heuristics'}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            {scored.wordCount} words · penalties −{scored.penalties}
          </Text>
        </Stack>
      </Group>
      {scored.fallback ? <Alert color="yellow">{scored.fallback}</Alert> : null}
      {scored.visual ? <Alert color="gray">{scored.visual}</Alert> : null}
      <Group align="center" gap="lg">
        {compact ? null : <Radar dimensions={scored.dimensions} />}
        <Stack gap={6} aria-label="Dimensions" style={{ flex: 1, minWidth: 200 }}>
          {DIMENSIONS.map((d) => (
            <div key={d}>
              <Group justify="space-between" gap="xs">
                <Text size="sm">{DIMENSION_LABELS[d]}</Text>
                <Text size="sm" fw={600}>
                  {scored.dimensions[d] ?? '—'}
                </Text>
              </Group>
              <Progress value={scored.dimensions[d] ?? 0} aria-label={`${DIMENSION_LABELS[d]} ${scored.dimensions[d] ?? 0}`} />
            </div>
          ))}
        </Stack>
      </Group>
      {scored.assessment ? <Text size="sm">{scored.assessment}</Text> : null}
      {scored.gaps.length ? (
        <Stack gap={4}>
          <Title order={5}>Gaps</Title>
          <List spacing={4} size="sm">
            {scored.gaps.slice(0, compact ? 4 : undefined).map((gap) => (
              <List.Item key={gap.category} icon={<Badge size="xs" color={SEVERITY[gap.severity] ?? 'gray'}>{gap.severity}</Badge>}>
                <b>{label(gap.category)}</b>: {gap.description}
              </List.Item>
            ))}
          </List>
        </Stack>
      ) : null}
      {compact ? null : <Details scored={scored} />}
    </Stack>
  );
}

function Details({ scored }: { scored: Scored }) {
  return (
    <Stack gap="sm">
      {scored.summary ? (
        <Paper withBorder p="sm">
          <Title order={5}>Executive summary</Title>
          <Text size="sm" style={{ whiteSpace: 'pre-wrap' }}>
            {scored.summary}
          </Text>
        </Paper>
      ) : null}
      {scored.actions.length ? (
        <Stack gap={4}>
          <Title order={5}>Priority actions</Title>
          {scored.actions.map((action, i) => (
            <Text key={i} size="sm">
              <b>{action.title}</b> — {action.impact} impact, {action.effort} effort. {action.description}
            </Text>
          ))}
        </Stack>
      ) : null}
      <Accordion variant="separated" multiple>
        <Accordion.Item value="patterns">
          <Accordion.Control>Patterns ({scored.patterns.length})</Accordion.Control>
          <Accordion.Panel>
            <Table striped aria-label="Pattern scores">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Pattern</Table.Th>
                  <Table.Th>Score</Table.Th>
                  <Table.Th>Evidence and recommendation</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {scored.patterns.map((p) => (
                  <Table.Tr key={p.name}>
                    <Table.Td>
                      {label(p.name)} {p.detected ? <Badge size="xs" color="teal">seen</Badge> : null}
                    </Table.Td>
                    <Table.Td>
                      {Math.round(p.score * 10) / 10} / {p.max}
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs">{p.evidence.join(' · ')}</Text>
                      {p.recommendation ? (
                        <Text size="xs" c="dimmed">
                          {p.recommendation}
                        </Text>
                      ) : null}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Accordion.Panel>
        </Accordion.Item>
        {scored.improvements.length ? (
          <Accordion.Item value="improvements">
            <Accordion.Control>Sample improvements ({scored.improvements.length})</Accordion.Control>
            <Accordion.Panel>
              {scored.improvements.map((item, i) => (
                <Stack key={i} gap={2} mb="sm">
                  <Text size="sm" fw={600}>
                    {item.section}
                  </Text>
                  <Text size="xs" c="dimmed">
                    Before: {item.current}
                  </Text>
                  <Text size="xs">After: {item.improved}</Text>
                </Stack>
              ))}
            </Accordion.Panel>
          </Accordion.Item>
        ) : null}
      </Accordion>
    </Stack>
  );
}
