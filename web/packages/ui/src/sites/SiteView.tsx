// One site: its overview — how it renders, where its files live, its pages,
// and its jobs — with sync, write-back and the doctor as jobs that a person
// starts and follows live (JobLog), its registry fields, its per-site
// settings (its brand rules among them: the voice AI help reads, the phrases
// the brand guard refuses on its pages, and whether its built-in bans hold on
// its books' chapters), and what its last doctor run
// found. Only someone who may manage the site sees the actions and may save;
// the platform re-checks every one.
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  TagsInput,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { SiteDetail, SiteSettings } from '@zer0/api';
import { useState } from 'react';

import { fieldError, newKey, once, oneClick } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { JobLog, JobStatus } from './JobLog';
import { DoctorBadges, rendersWith, when } from './SitesWorkspace';

type Kind = 'sync' | 'export' | 'doctor';
const ACTIONS: { kind: Kind; label: string; help: string }[] = [
  { kind: 'sync', label: 'Sync', help: 'Read the files into the platform; a file changed by hand updates its page.' },
  { kind: 'export', label: 'Write back', help: 'Write the pages into the files; a file changed by hand since is never overwritten.' },
  { kind: 'doctor', label: 'Run the doctor', help: 'Check the site against the platform’s contract.' },
];

export function SiteView({ siteId }: { siteId: number }) {
  const api = useApi();
  const path = { params: { path: { id: siteId } } };
  const site = useQuery({ queryKey: ['site', siteId], queryFn: () => call(api.GET('/api/v2/sites/{id}/', path)) });
  const [watching, setWatching] = useState<string | null>(null);

  if (site.isPending) return <Loader />;
  if (site.isError) return <Alert color="red">{errorText(site.error)}</Alert>;
  const s = site.data;
  return (
    <Stack>
      <Group justify="space-between" align="start">
        <Stack gap={2}>
          <Title order={2}>{s.name}</Title>
          <Text size="sm" c="dimmed">
            {s.hostname}
            {s.managed ? ` · ${s.managed.checkout}` : ''}
          </Text>
        </Stack>
        {s.managed ? <DoctorBadges managed={s.managed} /> : <Badge color="gray">not managed</Badge>}
      </Group>
      {s.managed && s.can_manage ? <Actions site={s} onStarted={setWatching} /> : null}
      {watching ? (
        <Card withBorder>
          <JobLog key={watching} jobId={watching} />
        </Card>
      ) : null}
      <Tabs defaultValue="overview" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="settings">Settings</Tabs.Tab>
          <Tabs.Tab value="findings">Findings</Tabs.Tab>
          <Tabs.Tab value="jobs">Jobs</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview" pt="md">
          <Overview site={s} />
        </Tabs.Panel>
        <Tabs.Panel value="settings" pt="md">
          <SettingsForm siteId={siteId} editable={Boolean(s.can_manage)} />
        </Tabs.Panel>
        <Tabs.Panel value="findings" pt="md">
          <Findings siteId={siteId} />
        </Tabs.Panel>
        <Tabs.Panel value="jobs" pt="md">
          <Jobs site={s} onOpen={setWatching} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

function Actions({ site, onStarted }: { site: SiteDetail; onStarted: (id: string) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const [drafts, setDrafts] = useState(false);
  const start = useMutation({
    mutationFn: ({ kind, key }: { kind: Kind; key: string }) => {
      const params = { params: { path: { id: site.id } }, headers: once(key) };
      if (kind === 'sync') return call(api.POST('/api/v2/sites/{id}/sync/', { ...params, body: { force: false } }));
      if (kind === 'export') return call(api.POST('/api/v2/sites/{id}/export/', { ...params, body: { include_drafts: drafts } }));
      return call(api.POST('/api/v2/sites/{id}/doctor/', params));
    },
    onSuccess: (accepted) => {
      onStarted(accepted.job.id);
      void qc.invalidateQueries({ queryKey: ['site', site.id] });
    },
  });
  return (
    <Stack gap="xs">
      <Group>
        {ACTIONS.map((action) => (
          <Button
            key={action.kind}
            variant={action.kind === 'sync' ? 'filled' : 'light'}
            title={action.help}
            loading={start.isPending && start.variables.kind === action.kind}
            disabled={start.isPending}
            onClick={oneClick(() => start.mutate({ kind: action.kind, key: newKey() }))}
          >
            {action.label}
          </Button>
        ))}
        <Switch label="Write back drafts too" checked={drafts} onChange={(e) => setDrafts(e.currentTarget.checked)} />
      </Group>
      {start.isError ? <Alert color="red">{errorText(start.error)}</Alert> : null}
    </Stack>
  );
}

function Overview({ site }: { site: SiteDetail }) {
  return (
    <Stack>
      <SimpleGrid cols={{ base: 2, md: 4 }}>
        <Fact label="Pages" value={`${site.pages.total} (${site.pages.live} live, ${site.pages.drafts} draft)`} />
        <Fact label="Files the platform tracks" value={String(site.files)} />
        <Fact label="Last sync" value={when(site.managed?.last_synced_at)} />
        <Fact label="Last write-back" value={when(site.managed?.last_exported_at)} />
      </SimpleGrid>
      {site.managed ? <RegistryForm site={site} /> : <Alert color="gray">The platform does not manage this site: register its checkout in Sites.</Alert>}
    </Stack>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <Card withBorder padding="sm">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text fw={600}>{value}</Text>
    </Card>
  );
}

function RegistryForm({ site }: { site: SiteDetail }) {
  const api = useApi();
  const qc = useQueryClient();
  const managed = site.managed;
  const [form, setForm] = useState({
    content_source: managed?.content_source ?? 'files',
    render: managed?.render ?? 'react',
    theme_tag: managed?.theme_tag ?? '',
    server: managed?.server ?? '',
    domains: managed?.domains ?? [],
    deploy_target: managed?.deploy_target ?? '',
  });
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH('/api/v2/sites/{id}/', {
          params: { path: { id: site.id } },
          body: { ...form, server: form.server as 'github-pages' | 'jekyll-4' | '' },
        }),
      ),
    onSuccess: (saved) => qc.setQueryData(['site', site.id], saved),
  });
  const editable = Boolean(site.can_manage);
  const set = (patch: Partial<typeof form>) => setForm((current) => ({ ...current, ...patch }));
  return (
    <Card withBorder>
      <Stack gap="sm">
        <Title order={4}>How it is kept and published</Title>
        <Text size="sm" c="dimmed">
          Now: {managed ? rendersWith(managed) : ''}
        </Text>
        <SegmentedControl
          aria-label="Content source"
          disabled={!editable}
          value={form.content_source}
          onChange={(value) => set({ content_source: value as typeof form.content_source })}
          data={[
            { value: 'files', label: 'People edit the files' },
            { value: 'platform', label: 'The files are generated' },
          ]}
        />
        <Group grow align="start">
          <Select
            label="Renders with"
            disabled={!editable}
            value={form.render}
            onChange={(value) => set({ render: (value ?? 'react') as typeof form.render })}
            data={[
              { value: 'react', label: 'The React renderer' },
              { value: 'jekyll-theme', label: 'The Jekyll-theme option' },
            ]}
            allowDeselect={false}
          />
          <TextInput
            label="Theme tag"
            placeholder="v1.31.3"
            disabled={!editable || form.render !== 'jekyll-theme'}
            value={form.theme_tag}
            error={fieldError(save.error, 'theme_tag')}
            onChange={(e) => set({ theme_tag: e.currentTarget.value })}
          />
          <Select
            label="Jekyll server"
            disabled={!editable || form.render !== 'jekyll-theme'}
            value={form.server || null}
            onChange={(value) => set({ server: value ?? '' })}
            data={[
              { value: 'github-pages', label: 'GitHub Pages’ builder' },
              { value: 'jekyll-4', label: 'The pinned Jekyll 4 image' },
            ]}
            clearable
          />
        </Group>
        <Group grow align="start">
          <TagsInput
            label="Domains"
            disabled={!editable}
            value={form.domains}
            error={fieldError(save.error, 'domains')}
            onChange={(value) => set({ domains: value })}
          />
          <TextInput
            label="Deploy target"
            placeholder="/drsai/"
            disabled={!editable}
            value={form.deploy_target}
            onChange={(e) => set({ deploy_target: e.currentTarget.value })}
          />
        </Group>
        {save.isError ? <Alert color="red">{errorText(save.error)}</Alert> : null}
        {editable ? (
          <Group>
            <Button loading={save.isPending} onClick={oneClick(() => save.mutate())}>
              Save
            </Button>
            {save.isSuccess ? <Text size="sm">Saved.</Text> : null}
          </Group>
        ) : null}
      </Stack>
    </Card>
  );
}

type Nav = SiteSettings['navigation'];

function SettingsForm({ siteId, editable }: { siteId: number; editable: boolean }) {
  const api = useApi();
  const settings = useQuery({
    queryKey: ['site-settings', siteId],
    queryFn: () => call(api.GET('/api/v2/sites/{id}/settings/', { params: { path: { id: siteId } } })),
  });
  if (settings.isPending) return <Loader />;
  if (settings.isError) return <Alert color="red">{errorText(settings.error)}</Alert>;
  return <SettingsFields siteId={siteId} initial={settings.data} editable={editable} />;
}

function SettingsFields({ siteId, initial, editable }: { siteId: number; initial: SiteSettings; editable: boolean }) {
  const api = useApi();
  const qc = useQueryClient();
  const [form, setForm] = useState(initial);
  const [tokens, setTokens] = useState(Object.entries(initial.design_tokens ?? {}).map(([name, value]) => ({ name, value })));
  const [bans, setBans] = useState<[string, string][]>((initial.banned_patterns ?? []).map((ban) => [ban.name, ban.pattern]));
  const save = useMutation({
    mutationFn: () =>
      call(
        api.PATCH('/api/v2/sites/{id}/settings/', {
          params: { path: { id: siteId } },
          body: {
            ...form,
            design_tokens: Object.fromEntries(tokens.filter((t) => t.name.trim()).map((t) => [t.name.trim(), t.value])),
            banned_patterns: bans.filter(([name, pattern]) => name.trim() || pattern.trim()).map(([name, pattern]) => ({ name: name.trim(), pattern })),
          },
        }),
      ),
    onSuccess: (saved) => qc.setQueryData(['site-settings', siteId], saved),
  });
  const set = (patch: Partial<SiteSettings>) => setForm((current) => ({ ...current, ...patch }));
  const nav: Nav = form.navigation ?? [];
  const setNav = (next: Nav) => set({ navigation: next });
  const text = (name: keyof SiteSettings, label: string, description?: string) => (
    <TextInput
      label={label}
      description={description}
      disabled={!editable}
      value={String(form[name] ?? '')}
      error={fieldError(save.error, name)}
      onChange={(e) => set({ [name]: e.currentTarget.value })}
    />
  );
  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder>
          <Stack gap="xs">
            <Title order={5}>SEO defaults</Title>
            {text('seo_title_suffix', 'Title suffix', 'Appended to every page title')}
            <Textarea label="Description" disabled={!editable} value={form.seo_description ?? ''} onChange={(e) => set({ seo_description: e.currentTarget.value })} />
            {text('seo_image', 'Social image', 'For a page without its own')}
            <Switch label="Ask search engines not to index it" disabled={!editable} checked={Boolean(form.noindex)} onChange={(e) => set({ noindex: e.currentTarget.checked })} />
          </Stack>
        </Card>
        <Card withBorder>
          <Stack gap="xs">
            <Title order={5}>Analytics and budget</Title>
            {text('ga4_measurement_id', 'GA4 measurement id', 'G-XXXXXXX')}
            {text('search_console_property', 'Search Console property')}
            <NumberInput
              label="Monthly AI budget (USD)"
              disabled={!editable}
              min={0}
              decimalScale={2}
              value={form.monthly_budget_usd ?? ''}
              onChange={(value) => set({ monthly_budget_usd: value === '' ? null : String(value) })}
            />
          </Stack>
        </Card>
        <Card withBorder>
          <Stack gap="xs">
            <Title order={5}>Voice and design</Title>
            <Textarea label="Brand voice" description="How the site writes; AI help reads it" autosize minRows={3} disabled={!editable} value={form.brand_voice ?? ''} onChange={(e) => set({ brand_voice: e.currentTarget.value })} />
            {text('skin', 'Skin')}
            <Pairs label="Design tokens" left="Token" right="Value" rows={tokens.map((t) => [t.name, t.value])} editable={editable} onChange={(rows) => setTokens(rows.map(([name, value]) => ({ name, value })))} />
            <Pairs label="Banned phrases (the brand guard refuses them on this site's pages, as regular expressions, any case)" left="Phrase" right="Pattern" rows={bans} editable={editable} onChange={setBans} />
            {fieldError(save.error, 'banned_patterns') ? <Text size="sm" c="red">{fieldError(save.error, 'banned_patterns')}</Text> : null}
            <Switch
              label="Built-in bans on its books' chapters"
              description="Off for fiction that needs the marketing words they ban, in every book here; the banned phrases above still hold"
              disabled={!editable}
              checked={form.chapter_builtin_bans !== false}
              onChange={(e) => set({ chapter_builtin_bans: e.currentTarget.checked })}
            />
          </Stack>
        </Card>
        <Card withBorder>
          <Stack gap="xs">
            <Title order={5}>Navigation</Title>
            <Pairs label="Main menu" left="Label" right="Link" rows={nav.map((n) => [n.label, n.url])} editable={editable} onChange={(rows) => setNav(rows.map(([label, url]) => ({ label, url })))} />
            {fieldError(save.error, 'navigation') ? <Text size="sm" c="red">{fieldError(save.error, 'navigation')}</Text> : null}
          </Stack>
        </Card>
      </SimpleGrid>
      {save.isError ? <Alert color="red">{errorText(save.error)}</Alert> : null}
      {editable ? (
        <Group>
          <Button loading={save.isPending} onClick={oneClick(() => save.mutate())}>
            Save settings
          </Button>
          {save.isSuccess ? <Text size="sm">Saved.</Text> : null}
        </Group>
      ) : null}
    </Stack>
  );
}

/** Rows of two strings — a menu's items, a design's tokens — added, edited and removed in place. */
function Pairs({
  label,
  left,
  right,
  rows,
  editable,
  onChange,
}: {
  label: string;
  left: string;
  right: string;
  rows: [string, string][];
  editable: boolean;
  onChange: (rows: [string, string][]) => void;
}) {
  const put = (at: number, row: [string, string]) => onChange(rows.map((r, i) => (i === at ? row : r)));
  return (
    <Stack gap={4}>
      <Text size="sm" fw={500}>
        {label}
      </Text>
      {rows.map(([a, b], at) => (
        <Group key={at} gap="xs" grow>
          <TextInput aria-label={`${left} ${at + 1}`} disabled={!editable} value={a} onChange={(e) => put(at, [e.currentTarget.value, b])} />
          <TextInput aria-label={`${right} ${at + 1}`} disabled={!editable} value={b} onChange={(e) => put(at, [a, e.currentTarget.value])} />
          {editable ? (
            <Button variant="subtle" color="red" size="xs" style={{ flexGrow: 0 }} onClick={() => onChange(rows.filter((_, i) => i !== at))}>
              Remove
            </Button>
          ) : null}
        </Group>
      ))}
      {editable ? (
        <Group>
          <Button variant="light" size="xs" onClick={() => onChange([...rows, ['', '']])}>
            Add
          </Button>
        </Group>
      ) : null}
    </Stack>
  );
}

const CHECKS = ['config', 'image-engine', 'cms', 'fleet', 'distribution', 'content'];

function Findings({ siteId }: { siteId: number }) {
  const api = useApi();
  const [severity, setSeverity] = useState('all');
  const [check, setCheck] = useState<string | null>(null);
  const query = { ...(severity !== 'all' ? { severity: severity as 'error' | 'warning' } : {}), ...(check ? { check } : {}) };
  const findings = useQuery({
    queryKey: ['site-findings', siteId, severity, check],
    queryFn: () => call(api.GET('/api/v2/sites/{id}/findings/', { params: { path: { id: siteId }, query } })),
  });
  return (
    <Stack>
      <Group>
        <SegmentedControl
          aria-label="Severity"
          value={severity}
          onChange={setSeverity}
          data={[
            { value: 'all', label: 'All' },
            { value: 'error', label: 'Errors' },
            { value: 'warning', label: 'Warnings' },
          ]}
        />
        <Select aria-label="Check" placeholder="Every check" data={CHECKS} value={check} onChange={setCheck} clearable />
      </Group>
      {findings.isPending ? <Loader /> : null}
      {findings.isError ? <Alert color="red">{errorText(findings.error)}</Alert> : null}
      {findings.data?.length === 0 ? <Text c="dimmed">Nothing found — or the doctor has not run yet.</Text> : null}
      {findings.data?.length ? (
        <Table verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Severity</Table.Th>
              <Table.Th>Check</Table.Th>
              <Table.Th>Rule</Table.Th>
              <Table.Th>File</Table.Th>
              <Table.Th>What it found</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {findings.data.map((f) => (
              <Table.Tr key={f.fingerprint + f.file}>
                <Table.Td>
                  <Badge color={f.severity === 'error' ? 'red' : 'orange'} variant="light">
                    {f.severity}
                  </Badge>
                </Table.Td>
                <Table.Td>{f.check_id}</Table.Td>
                <Table.Td>{f.rule}</Table.Td>
                <Table.Td>{f.line ? `${f.file}:${f.line}` : f.file}</Table.Td>
                <Table.Td>{f.evidence}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
    </Stack>
  );
}

function Jobs({ site, onOpen }: { site: SiteDetail; onOpen: (id: string) => void }) {
  const go = useGo();
  if (site.jobs.length === 0) return <Text c="dimmed">No jobs yet.</Text>;
  return (
    <Table highlightOnHover verticalSpacing="xs">
      <Table.Thead>
        <Table.Tr>
          <Table.Th>Job</Table.Th>
          <Table.Th>Status</Table.Th>
          <Table.Th>Started</Table.Th>
          <Table.Th>Result</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {site.jobs.map((job) => (
          <Table.Tr key={job.id}>
            <Table.Td>
              <Anchor component="button" type="button" onClick={() => onOpen(job.id)}>
                {job.kind}
              </Anchor>{' '}
              <Anchor component="button" type="button" size="xs" c="dimmed" onClick={() => go({ to: 'job', id: job.id })}>
                (open)
              </Anchor>
            </Table.Td>
            <Table.Td>
              <JobStatus status={job.status} />
            </Table.Td>
            <Table.Td>{new Date(job.created_at).toLocaleString()}</Table.Td>
            <Table.Td>
              <Text size="sm">
                {Object.entries(job.result ?? {})
                  .map(([name, value]) => `${String(value)} ${name}`)
                  .join(', ')}
              </Text>
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
