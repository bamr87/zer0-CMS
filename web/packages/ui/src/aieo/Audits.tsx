// Audit a pasted text, a page, a URL or a whole site: the request starts a
// run (202) followed live on its stream, then the audit opens with its score
// breakdown and evidence — for a site, every page it read and the link map's
// hubs and orphans — and its report, as AIEO wrote it. Below, the audit
// history: every audit the person may see, newest first.
import {
  Alert,
  Badge,
  Button,
  Checkbox,
  CopyButton,
  Group,
  Modal,
  NumberInput,
  Paper,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AieoAudit, AieoAuditKind } from '@zer0/api';
import { useState } from 'react';

import { MarkdownView, newKey, once, oneClick, RunProgress } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi } from '../context';
import { PagePicker } from '../PagePicker';
import { ScoreCard } from './ScoreCard';
import { gradeColor, readLinkMap, readPages, readScore } from './score';

const KINDS: { value: AieoAuditKind; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'page', label: 'Page' },
  { value: 'url', label: 'URL' },
  { value: 'site', label: 'Site' },
];

export function Audits({ siteId }: { siteId?: number }) {
  const api = useApi();
  const qc = useQueryClient();
  const [kind, setKind] = useState<AieoAuditKind>('text');
  const [content, setContent] = useState('');
  const [format, setFormat] = useState<'markdown' | 'html'>('markdown');
  const [pageId, setPageId] = useState<number | null>(null);
  const [url, setUrl] = useState('');
  const [maxPages, setMaxPages] = useState<number>(25);
  const [ai, setAi] = useState(true);
  const [visual, setVisual] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const start = useMutation({
    mutationFn: (key: string) =>
      call(
        api.POST('/api/v2/aieo/audits/', {
          body: {
            kind,
            method: ai ? 'ai' : 'heuristic',
            content: kind === 'text' ? content : '',
            format,
            page_id: kind === 'page' ? pageId : null,
            url: kind === 'url' || kind === 'site' ? url : '',
            max_pages: maxPages,
            visual: kind === 'url' && visual,
            provider: '',
            title: '',
            site: siteId ?? null,
          },
          params: { header: once(key) },
        }),
      ),
    onSuccess: (made) => {
      setOpen(made.audit.id);
      setRunId(made.run.id);
      void qc.invalidateQueries({ queryKey: ['aieo', 'audits'] });
    },
  });
  const ready =
    (kind === 'text' && content.trim()) || (kind === 'page' && pageId) || ((kind === 'url' || kind === 'site') && url.trim());

  return (
    <Stack>
      <Paper withBorder p="md" component="form" aria-label="Audit" onSubmit={(e) => e.preventDefault()}>
        <Stack gap="sm">
          <SegmentedControl value={kind} onChange={(v) => setKind(v as AieoAuditKind)} data={KINDS} aria-label="What to audit" />
          {kind === 'text' ? (
            <>
              <Textarea label="Text to audit" autosize minRows={4} maxRows={14} value={content} onChange={(e) => setContent(e.currentTarget.value)} />
              <Select label="Format" w={160} data={['markdown', 'html']} value={format} onChange={(v) => setFormat(v === 'html' ? 'html' : 'markdown')} allowDeselect={false} />
            </>
          ) : null}
          {kind === 'page' ? <PagePicker label="Page" value={pageId} onChange={setPageId} siteId={siteId} /> : null}
          {kind === 'url' || kind === 'site' ? (
            <TextInput label={kind === 'site' ? 'Site address' : 'Page address'} placeholder="https://example.com/" value={url} onChange={(e) => setUrl(e.currentTarget.value)} />
          ) : null}
          {kind === 'site' ? <NumberInput label="Pages to read at most" min={1} max={200} w={200} value={maxPages} onChange={(v) => setMaxPages(Number(v) || 25)} /> : null}
          {kind === 'url' ? <Checkbox label="Screenshot it too (the visual audit, when the platform has it on)" checked={visual} onChange={(e) => setVisual(e.currentTarget.checked)} /> : null}
          <Switch
            label="A model's evaluation (the heuristics score it if the model fails)"
            checked={ai}
            onChange={(e) => setAi(e.currentTarget.checked)}
          />
          <Group>
            <Button disabled={!ready} loading={start.isPending} onClick={oneClick(() => start.mutate(newKey()))}>
              Audit
            </Button>
          </Group>
          {start.isError ? <Alert color="red">{errorText(start.error)}</Alert> : null}
          {runId ? (
            <RunProgress
              key={runId}
              runId={runId}
              onFinal={() => {
                void qc.invalidateQueries({ queryKey: ['aieo', 'audit'] });
                void qc.invalidateQueries({ queryKey: ['aieo', 'audits'] });
              }}
            />
          ) : null}
        </Stack>
      </Paper>
      {open ? <AuditView id={open} /> : null}
      <History siteId={siteId} onOpen={setOpen} />
    </Stack>
  );
}

/** One audit: its status, its score breakdown when it is ready, a site's pages and link map, its report. */
export function AuditView({ id }: { id: string }) {
  const api = useApi();
  const audit = useQuery({
    queryKey: ['aieo', 'audit', id],
    queryFn: () => call(api.GET('/api/v2/aieo/audits/{public_id}/', { params: { path: { public_id: id } } })),
    refetchInterval: (query) => (query.state.data && ['pending', 'running'].includes(query.state.data.status) ? 2000 : false),
  });
  if (audit.isError) return <Alert color="red">{errorText(audit.error)}</Alert>;
  const row = audit.data;
  if (!row) return null;
  return (
    <Paper withBorder p="md" aria-label={`Audit of ${row.target}`}>
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>{row.target}</Title>
          <Group gap="xs">
            <Badge variant="light">{row.kind}</Badge>
            <Badge color={row.status === 'ready' ? 'teal' : row.status === 'failed' ? 'red' : 'blue'}>{row.status}</Badge>
            {row.status === 'ready' ? <ReportButton id={row.id} /> : null}
          </Group>
        </Group>
        {row.status === 'failed' ? <Alert color="red">{row.error || 'The audit failed.'}</Alert> : null}
        {row.status === 'ready' ? <Finished row={row} /> : null}
      </Stack>
    </Paper>
  );
}

function Finished({ row }: { row: AieoAudit }) {
  const pages = readPages(row.pages);
  const links = readLinkMap(row.result);
  const benchmark = row.benchmark as { percentile?: number | null; similar?: { target?: string; score?: number | null }[] };
  const similar = (benchmark.similar ?? []).filter((s) => typeof s.target === 'string');
  return (
    <Stack gap="sm">
      <ScoreCard scored={readScore(row.result, row)} />
      {typeof benchmark.percentile === 'number' ? (
        <Text size="sm" c="dimmed">
          Better than {benchmark.percentile}% of the audits here.
        </Text>
      ) : null}
      {similar.length ? (
        <Text size="sm" c="dimmed">
          Closest in meaning: {similar.map((s) => `${s.target} (${s.score ?? '—'})`).join(', ')}
        </Text>
      ) : null}
      {row.screenshot ? (
        <Text size="sm">
          A screenshot was taken: <code>{row.screenshot}</code>
        </Text>
      ) : null}
      {pages.length ? (
        <Stack gap="xs">
          <Title order={5}>Pages read ({pages.length})</Title>
          <Table aria-label="Pages read">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Page</Table.Th>
                <Table.Th>Found by</Table.Th>
                <Table.Th>Score</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {pages.map((p) => (
                <Table.Tr key={p.url}>
                  <Table.Td>{p.title || p.url}</Table.Td>
                  <Table.Td>{p.foundBy}</Table.Td>
                  <Table.Td>{p.score === null ? <Text c="red" size="sm">{p.error}</Text> : `${p.score} (${p.grade})`}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Text size="sm">
            <b>Hubs:</b> {links.hubs.map((h) => `${h.url} (${h.inbound})`).join(', ') || 'none'}
          </Text>
          <Text size="sm">
            <b>Orphans</b> (no other page read links to them): {links.orphans.join(', ') || 'none'}
          </Text>
        </Stack>
      ) : null}
    </Stack>
  );
}

function ReportButton({ id }: { id: string }) {
  const api = useApi();
  const [shown, setShown] = useState(false);
  const report = useQuery({
    queryKey: ['aieo', 'report', id],
    enabled: shown,
    queryFn: () => call(api.GET('/api/v2/aieo/audits/{public_id}/report/', { params: { path: { public_id: id } } })),
  });
  return (
    <>
      <Button size="xs" variant="default" onClick={() => setShown(true)}>
        Report
      </Button>
      <Modal opened={shown} onClose={() => setShown(false)} title={report.data?.filename ?? 'Report'} size="xl">
        {report.isError ? <Alert color="red">{errorText(report.error)}</Alert> : null}
        {report.data ? (
          <Stack>
            <CopyButton value={report.data.markdown}>
              {({ copied, copy }) => (
                <Button size="xs" variant="light" onClick={copy}>
                  {copied ? 'Copied' : 'Copy the Markdown'}
                </Button>
              )}
            </CopyButton>
            <MarkdownView markdown={report.data.markdown} label="The report" />
          </Stack>
        ) : null}
      </Modal>
    </>
  );
}

function History({ siteId, onOpen }: { siteId?: number; onOpen: (id: string) => void }) {
  const api = useApi();
  const audits = useQuery({
    queryKey: ['aieo', 'audits', siteId],
    queryFn: () => call(api.GET('/api/v2/aieo/audits/', { params: { query: { site: siteId, page_size: 50 } } })),
  });
  const rows = audits.data?.results ?? [];
  return (
    <Stack gap="xs">
      <Title order={4}>History</Title>
      {audits.isError ? <Alert color="red">{errorText(audits.error)}</Alert> : null}
      {rows.length === 0 && audits.isSuccess ? <Text c="dimmed">No audits yet.</Text> : null}
      {rows.length ? (
        <Table aria-label="Audit history" highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>What</Table.Th>
              <Table.Th>Kind</Table.Th>
              <Table.Th>Score</Table.Th>
              <Table.Th>When</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row) => (
              <Table.Tr key={row.id}>
                <Table.Td>
                  <Button variant="subtle" size="compact-sm" onClick={() => onOpen(row.id)}>
                    {row.target}
                  </Button>
                </Table.Td>
                <Table.Td>{row.kind}</Table.Td>
                <Table.Td>
                  {row.status === 'ready' ? (
                    <Badge color={gradeColor(row.grade)}>
                      {row.score} · {row.grade}
                    </Badge>
                  ) : (
                    <Badge variant="light" color={row.status === 'failed' ? 'red' : 'blue'}>
                      {row.status}
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>{new Date(row.created_at).toLocaleString()}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </Stack>
  );
}
