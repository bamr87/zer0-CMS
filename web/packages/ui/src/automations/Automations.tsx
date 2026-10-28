// Automations (PLAN G16): a trigger — an event, a schedule, a webhook, a new
// research source, a named hook —, a condition over what it sends (JMESPath,
// tried here against a sample payload), and actions in order, which run as
// the automation's owner and only ever propose. Listed, created and edited
// here; a new one is paused until its owner enables it; it is tried with a
// dry run (nothing done) or fired with a sample payload (a real run); its
// webhook URL and secret — the secret shown once, when it is made or
// re-keyed — are here too, and its run history below. It exports and imports
// as YAML. Everything goes through the host's client (useApi), so the
// extension renders it too.
import { Alert, Badge, Button, Card, Code, CopyButton, Group, JsonInput, Loader, NumberInput, SegmentedControl, Select, Stack, Text, Textarea, TextInput, Title } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Automation, AutomationOptions, AutomationTrigger, Visibility } from '@zer0/api';
import { useState } from 'react';

import { ALL, ConfirmButton, ExportButton, fieldError, ImportButton, isRecord, JsonView, MONO, newKey, once, oneClick, OwnerFields, ReadOnlyNote, Rows, type Ownership } from '../ai/shared';
import { call, errorText } from '../call';
import { useApi, useGo } from '../context';
import { ActionList, toAction, toDraft, type ActionDraft } from './Actions';
import { AutomationRuns } from './Runs';

type TriggerKind = AutomationTrigger['kind'];

const TRIGGERS: { value: TriggerKind; label: string }[] = [
  { value: 'event', label: 'An event' },
  { value: 'schedule', label: 'A schedule' },
  { value: 'webhook', label: 'A webhook' },
  { value: 'source', label: 'A new research source' },
  { value: 'hook', label: 'A named hook' },
];

const FIRST: Record<TriggerKind, AutomationTrigger> = {
  event: { kind: 'event', event: 'content.page.published' },
  schedule: { kind: 'schedule', cron: '0 9 * * 1-5' },
  webhook: { kind: 'webhook' },
  source: { kind: 'source' },
  hook: { kind: 'hook', hook: 'monitor.finding' },
};

/** A trigger in a few words. */
export function triggerText(trigger: AutomationTrigger): string {
  switch (trigger.kind) {
    case 'event':
      return `When ${trigger.event}`;
    case 'schedule':
      return `On ${trigger.cron} (UTC)`;
    case 'webhook':
      return 'On a signed webhook';
    case 'source':
      return 'On a new research source';
    case 'hook':
      return `On the hook ${trigger.hook}`;
  }
}

const OPTIONS_KEY = ['automations', 'options'];

function useOptions() {
  const api = useApi();
  return useQuery({ queryKey: OPTIONS_KEY, queryFn: () => call(api.GET('/api/v2/automations/options/')), staleTime: 60_000 });
}

/** The sample payload a trigger sends, from the platform's samples (an event's by its type). */
function sampleFor(trigger: AutomationTrigger, options?: AutomationOptions): unknown {
  const samples = options?.samples ?? {};
  const kind = samples[trigger.kind];
  return trigger.kind === 'event' && isRecord(kind) ? (kind[trigger.event] ?? {}) : (kind ?? {});
}

export function AutomationList({ siteId }: { siteId?: number | null }) {
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const query = { ...ALL, ordering: 'name', ...(siteId ? { site: siteId } : {}) };
  const automations = useQuery({ queryKey: ['automations', 'list', query], queryFn: () => call(api.GET('/api/v2/automations/', { params: { query } })) });
  return (
    <Stack>
      <Group justify="space-between">
        <Text size="sm" c="dimmed">
          When something happens, do something: as you, and nothing published.
        </Text>
        <Group gap="xs">
          <ImportButton
            label="Import an automation"
            format="yaml"
            onImport={async (document) => {
              const made = await call(api.POST('/api/v2/automations/import/', { body: { yaml: String(document) } }));
              qc.setQueryData(['automations', 'one', made.id], made); // its secret, shown once on its page
              void qc.invalidateQueries({ queryKey: ['automations', 'list'] });
              go({ to: 'automation', id: made.id });
            }}
          />
          <Button onClick={() => go({ to: 'automation' })}>New automation</Button>
        </Group>
      </Group>
      <Rows
        label="Automations"
        query={automations}
        name={(a) => a.name}
        onOpen={(a) => go({ to: 'automation', id: a.id })}
        columns={[
          { title: 'Trigger', cell: (a) => triggerText(a.trigger) },
          { title: 'State', cell: (a) => <Badge color={a.enabled ? 'green' : 'gray'}>{a.enabled ? 'On' : 'Paused'}</Badge> },
          { title: 'Last run', cell: (a) => (a.last_run ? `${a.last_run.status}, ${new Date(a.last_run.created_at).toLocaleString()}` : '—') },
          { title: 'Owner', cell: (a) => a.owner ?? '—' },
        ]}
        empty={{
          title: 'No automations yet',
          description: 'Pitch every wire item, brief a story each morning, or tell the desk when a page goes live.',
          action: <Button onClick={() => go({ to: 'automation' })}>New automation</Button>,
        }}
      />
    </Stack>
  );
}

/** One automation to edit, test and follow — or a new one (no id). */
export function AutomationEditor({ id }: { id?: string }) {
  const api = useApi();
  const existing = useQuery({
    queryKey: ['automations', 'one', id],
    enabled: id !== undefined,
    queryFn: () => call(api.GET('/api/v2/automations/{public_id}/', { params: { path: { public_id: id ?? '' } } })),
  });
  const options = useOptions();
  // The secret is in the answer that made the automation (or re-keyed it) and never again: kept while this is open,
  // whatever is read after it — enabling it, say, which opens the form again.
  const [secret, setSecret] = useState<string | null>(null);
  const fresh = existing.data?.secret ?? null;
  if (fresh && fresh !== secret) setSecret(fresh);
  if ((id && existing.isPending) || options.isPending) return <Loader aria-label="Loading the automation" />;
  if (id && existing.isError) return <Alert color="red">{errorText(existing.error)}</Alert>;
  if (options.isError) return <Alert color="red">{errorText(options.error)}</Alert>;
  const automation = existing.data;
  return <AutomationForm key={automation?.updated_at ?? 'new'} automation={automation} options={options.data} secret={secret} onSecret={setSecret} />;
}

interface Draft extends Ownership {
  name: string;
  description: string;
  trigger: AutomationTrigger;
  condition: string;
  on_error: 'stop' | 'continue';
  max_runs_per_hour: number;
}

function AutomationForm(props: { automation?: Automation; options: AutomationOptions; secret: string | null; onSecret: (secret: string) => void }) {
  const { automation, options } = props;
  const api = useApi();
  const go = useGo();
  const qc = useQueryClient();
  const [draft, setDraft] = useState<Draft>(() => ({
    name: automation?.name ?? '',
    description: automation?.description ?? '',
    visibility: (automation?.visibility ?? 'private') as Visibility,
    site: automation?.site ?? null,
    trigger: automation?.trigger ?? FIRST.event,
    condition: automation?.condition ?? '',
    on_error: automation?.on_error ?? 'stop',
    max_runs_per_hour: automation?.max_runs_per_hour ?? 60,
  }));
  const [actions, setActions] = useState<ActionDraft[]>(() => (automation?.actions ?? []).map(toDraft));
  const editable = automation?.can_edit ?? true;
  const body = () => ({ ...draft, actions: actions.map(toAction) });
  const save = useMutation({
    mutationFn: () =>
      automation
        ? call(api.PATCH('/api/v2/automations/{public_id}/', { params: { path: { public_id: automation.id } }, body: body() }))
        : call(api.POST('/api/v2/automations/', { body: body() })),
    onSuccess: (saved) => {
      notifications.show({ message: `${saved.name} saved` });
      void qc.invalidateQueries({ queryKey: ['automations', 'list'] });
      qc.setQueryData(['automations', 'one', saved.id], saved); // a new one's secret, shown once on its page
      if (!automation) go({ to: 'automation', id: saved.id });
    },
  });
  const remove = useMutation({
    mutationFn: () => call(api.DELETE('/api/v2/automations/{public_id}/', { params: { path: { public_id: automation?.id ?? '' } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['automations', 'list'] });
      go({ to: 'ai', section: 'automations' });
    },
  });
  const error = save.error;
  const setTrigger = (trigger: AutomationTrigger) => setDraft({ ...draft, trigger });
  const [sample, setSample] = useState<string | null>(null);
  const shownSample = sample ?? JSON.stringify(sampleFor(draft.trigger, options), null, 2);

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>{automation ? automation.name : 'New automation'}</Title>
        {automation && editable ? <ConfirmButton label="Delete" question={`Delete ${automation.name} and its runs?`} busy={remove.isPending} onConfirm={() => remove.mutate()} /> : null}
      </Group>
      {automation ? <ReadOnlyNote owner={automation.owner} can={editable} /> : null}
      {remove.isError ? <Alert color="red">{errorText(remove.error)}</Alert> : null}
      {automation ? <State automation={automation} secret={props.secret} onSecret={props.onSecret} /> : null}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <Stack>
          <TextInput label="Name" required value={draft.name} disabled={!editable} onChange={(e) => setDraft({ ...draft, name: e.currentTarget.value })} error={fieldError(error, 'name')} />
          <TextInput label="Description" value={draft.description} disabled={!editable} onChange={(e) => setDraft({ ...draft, description: e.currentTarget.value })} />
          <OwnerFields value={draft} disabled={!editable} error={error} onChange={(next) => setDraft({ ...draft, ...next })} />

          <Title order={4}>When</Title>
          <TriggerFields trigger={draft.trigger} options={options} disabled={!editable} error={fieldError(error, 'trigger')} onChange={setTrigger} />

          <Title order={4}>If</Title>
          <Textarea
            label="Condition"
            description="A JMESPath expression over the payload, e.g. data.page_type == 'cms.ArticlePage'. Empty: always."
            autosize
            minRows={1}
            styles={MONO}
            value={draft.condition}
            disabled={!editable}
            error={fieldError(error, 'condition')}
            onChange={(e) => setDraft({ ...draft, condition: e.currentTarget.value })}
          />
          <JsonInput
            label="Sample payload"
            description="What this trigger sends; templates read it too ({{ data.url }})."
            autosize
            minRows={3}
            maxRows={16}
            value={shownSample}
            validationError="This is not valid JSON"
            onChange={setSample}
          />
          <ConditionCheck condition={draft.condition} sample={shownSample} onReset={sample === null ? undefined : () => setSample(null)} />

          <Title order={4}>Then</Title>
          <ActionList actions={actions} onChange={setActions} editable={editable} agents={options.agents} stages={options.stages} />
          {fieldError(error, 'actions') ? (
            <Text c="red" size="sm">
              {fieldError(error, 'actions')}
            </Text>
          ) : null}
          <Group grow align="start">
            <SegmentedControl
              aria-label="When an action fails"
              data={[
                { value: 'stop', label: 'Stop at a failing action' },
                { value: 'continue', label: 'Record it and go on' },
              ]}
              value={draft.on_error}
              disabled={!editable}
              onChange={(value) => setDraft({ ...draft, on_error: value === 'continue' ? 'continue' : 'stop' })}
            />
            <NumberInput
              label="Runs per hour, at most"
              min={1}
              max={1000}
              value={draft.max_runs_per_hour}
              disabled={!editable}
              error={fieldError(error, 'max_runs_per_hour')}
              onChange={(value) => setDraft({ ...draft, max_runs_per_hour: Number(value) || 1 })}
            />
          </Group>
          {error ? <Alert color="red">{errorText(error)}</Alert> : null}
          {editable ? (
            <Group>
              <Button type="submit" loading={save.isPending} disabled={!draft.name.trim()} onClick={oneClick()}>
                {automation ? 'Save' : 'Create (paused)'}
              </Button>
            </Group>
          ) : null}
        </Stack>
      </form>
      {automation ? <TryIt automation={automation} sample={shownSample} /> : null}
      {automation ? (
        <Card withBorder>
          <Title order={4} mb="xs">
            Runs
          </Title>
          <AutomationRuns automation={automation.id} {...(automation.can_edit ? {} : { owner: automation.owner })} />
        </Card>
      ) : null}
    </Stack>
  );
}

function TriggerFields(props: { trigger: AutomationTrigger; options: AutomationOptions; disabled: boolean; error?: string; onChange: (next: AutomationTrigger) => void }) {
  const { trigger, options, disabled, onChange } = props;
  const api = useApi();
  const collections = useQuery({
    queryKey: ['research', 'collections', 'all'],
    enabled: trigger.kind === 'source',
    queryFn: () => call(api.GET('/api/v2/research/collections/', { params: { query: ALL } })),
  });
  const feeds = useQuery({
    queryKey: ['research', 'feeds', 'all'],
    enabled: trigger.kind === 'source',
    queryFn: () => call(api.GET('/api/v2/research/feeds/', { params: { query: ALL } })),
  });
  return (
    <Stack gap="xs">
      <Select
        label="What fires it"
        data={TRIGGERS}
        value={trigger.kind}
        allowDeselect={false}
        disabled={disabled}
        error={props.error}
        onChange={(kind) => kind && kind !== trigger.kind && onChange(FIRST[kind as TriggerKind])}
      />
      {trigger.kind === 'event' ? (
        <Select
          label="Event"
          data={options.events}
          value={trigger.event}
          allowDeselect={false}
          disabled={disabled}
          onChange={(event) => event && onChange({ ...trigger, event: event as typeof trigger.event })}
        />
      ) : null}
      {trigger.kind === 'schedule' ? (
        <TextInput
          label="Schedule"
          description="A cron line in UTC: minute hour day-of-month month day-of-week — 0 9 * * 1-5 is nine every weekday."
          styles={MONO}
          value={trigger.cron}
          disabled={disabled}
          onChange={(e) => onChange({ ...trigger, cron: e.currentTarget.value })}
        />
      ) : null}
      {trigger.kind === 'webhook' ? (
        <Text size="sm" c="dimmed">
          Once it is saved, its URL and secret are shown here. A request is signed with the secret: the header X-Zer0-Signature-256 carries sha256= and the HMAC-SHA256 of the body (GitHub’s X-Hub-Signature-256 works too).
        </Text>
      ) : null}
      {trigger.kind === 'source' ? (
        <Group grow align="start">
          <Select
            label="In the collection"
            placeholder="Any"
            clearable
            data={(collections.data?.results ?? []).map((c) => ({ value: c.id, label: c.name }))}
            value={trigger.collection ?? null}
            disabled={disabled}
            onChange={(collection) => onChange({ kind: 'source', ...(collection ? { collection } : {}), ...(trigger.feed ? { feed: trigger.feed } : {}) })}
          />
          <Select
            label="From the feed"
            placeholder="Any"
            clearable
            data={(feeds.data?.results ?? []).map((f) => ({ value: f.id, label: f.title || f.url }))}
            value={trigger.feed ?? null}
            disabled={disabled}
            onChange={(feed) => onChange({ kind: 'source', ...(trigger.collection ? { collection: trigger.collection } : {}), ...(feed ? { feed } : {}) })}
          />
        </Group>
      ) : null}
      {trigger.kind === 'hook' ? (
        <TextInput
          label="Hook"
          description="A name the platform's apps fire (monitor.finding), or agent.<slug>.<name> for one an agent's tool fires."
          styles={MONO}
          value={trigger.hook}
          disabled={disabled}
          onChange={(e) => onChange({ ...trigger, hook: e.currentTarget.value })}
        />
      ) : null}
    </Stack>
  );
}

/** The sample payload as JSON, or an error a person can read. */
function parsed(sample: string): Record<string, unknown> {
  const value: unknown = JSON.parse(sample);
  if (!isRecord(value)) throw new Error('The sample payload is a JSON object');
  return value;
}

function ConditionCheck({ condition, sample, onReset }: { condition: string; sample: string; onReset?: () => void }) {
  const api = useApi();
  const tried = useMutation({ mutationFn: () => call(api.POST('/api/v2/automations/condition/', { body: { condition, payload: parsed(sample) } })) });
  const verdict = tried.data;
  return (
    <Stack gap={4}>
      <Group gap="xs">
        <Button variant="default" size="xs" loading={tried.isPending} onClick={() => tried.mutate()}>
          Try the condition
        </Button>
        {onReset ? (
          <Button variant="subtle" size="xs" onClick={onReset}>
            Use the trigger’s sample
          </Button>
        ) : null}
        {verdict ? (
          <Badge role="status" aria-label="The condition’s verdict" color={verdict.matched === null ? 'red' : verdict.matched ? 'green' : 'gray'}>
            {verdict.matched === null ? 'Cannot be evaluated' : verdict.matched ? 'Matches' : 'Does not match'}
          </Badge>
        ) : null}
      </Group>
      {verdict?.error ? (
        <Text size="sm" c="red">
          {verdict.error}
        </Text>
      ) : null}
      {verdict && !verdict.error ? (
        <Text size="sm" c="dimmed">
          It found: <Code>{JSON.stringify(verdict.value)}</Code>
        </Text>
      ) : null}
      {tried.isError ? <Alert color="red">{errorText(tried.error)}</Alert> : null}
    </Stack>
  );
}

/** Whether it runs — enable or pause it — and, for a webhook, where to send it and the secret that signs it. */
function State({ automation, secret, onSecret }: { automation: Automation; secret: string | null; onSecret: (secret: string) => void }) {
  const api = useApi();
  const qc = useQueryClient();
  const path = { params: { path: { public_id: automation.id } } };
  const refresh = (saved: Automation) => {
    qc.setQueryData(['automations', 'one', automation.id], saved);
    void qc.invalidateQueries({ queryKey: ['automations', 'list'] });
  };
  const toggle = useMutation({
    mutationFn: () => call(automation.enabled ? api.POST('/api/v2/automations/{public_id}/disable/', path) : api.POST('/api/v2/automations/{public_id}/enable/', path)),
    onSuccess: refresh,
  });
  const rekey = useMutation({
    mutationFn: () => call(api.POST('/api/v2/automations/{public_id}/rotate-secret/', path)),
    onSuccess: (data) => onSecret(data.secret),
  });
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Group justify="space-between">
          <Group gap="xs">
            <Badge size="lg" color={automation.enabled ? 'green' : 'gray'}>
              {automation.enabled ? 'On' : 'Paused'}
            </Badge>
            <Text size="sm" c="dimmed">
              {automation.enabled ? 'It runs when its trigger fires.' : 'It runs only when you test it.'} Its actions run as {automation.owner ?? 'its owner'}.
            </Text>
          </Group>
          <Group gap="xs">
            <ExportButton name={automation.name} format="yaml" load={async () => (await call(api.GET('/api/v2/automations/{public_id}/export/', path))).yaml} />
            {automation.can_edit || automation.enabled ? (
              <Button color={automation.enabled ? 'gray' : 'green'} loading={toggle.isPending} onClick={oneClick(() => toggle.mutate())}>
                {automation.enabled ? 'Pause' : 'Enable'}
              </Button>
            ) : null}
          </Group>
        </Group>
        {toggle.isError ? <Alert color="red">{errorText(toggle.error)}</Alert> : null}
        {secret ? (
          <Alert color="yellow" title="Its secret — shown this once">
            <Group gap="xs">
              <Code>{secret}</Code>
              <CopyButton value={secret}>{({ copied, copy }) => <Button size="xs" onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>}</CopyButton>
            </Group>
            <Text size="sm">It signs the webhooks it receives and the ones it calls. Copy it now: it is not shown again.</Text>
          </Alert>
        ) : null}
        {automation.webhook_url ? (
          <Group gap="xs">
            <Text size="sm">Webhook:</Text>
            <Code>{automation.webhook_url}</Code>
            <CopyButton value={automation.webhook_url}>{({ copied, copy }) => <Button size="xs" variant="default" onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>}</CopyButton>
          </Group>
        ) : null}
        {automation.can_edit ? (
          <Group>
            <ConfirmButton label="New secret" question="A new secret: requests signed with the old one are refused from now on." busy={rekey.isPending} onConfirm={() => rekey.mutate()} />
          </Group>
        ) : null}
        {rekey.isError ? <Alert color="red">{errorText(rekey.error)}</Alert> : null}
      </Stack>
    </Card>
  );
}

/** A dry run (what it would do, doing nothing) or a real run with the sample payload, as saved. */
function TryIt({ automation, sample }: { automation: Automation; sample: string }) {
  const api = useApi();
  const qc = useQueryClient();
  const path = { public_id: automation.id };
  const dry = useMutation({ mutationFn: () => call(api.POST('/api/v2/automations/{public_id}/dry-run/', { params: { path }, body: { payload: parsed(sample) } })) });
  const fire = useMutation({
    mutationFn: (key: string) => call(api.POST('/api/v2/automations/{public_id}/test/', { params: { path, header: once(key) }, body: { payload: parsed(sample) } })),
    onSuccess: (run) => {
      notifications.show({ message: run.status === 'limited' ? 'Over its runs per hour: nothing ran' : 'Fired: its run is below' });
      void qc.invalidateQueries({ queryKey: ['automations'] });
    },
  });
  if (!automation.can_edit) return null;
  return (
    <Card withBorder>
      <Stack gap="xs">
        <Title order={4}>Try it, as saved</Title>
        <Text size="sm" c="dimmed">
          With the sample payload above: a dry run says what it would do and does nothing; firing it runs it for real, paused or not.
        </Text>
        <Group>
          <Button variant="default" loading={dry.isPending} onClick={() => dry.mutate()}>
            Dry run
          </Button>
          <Button loading={fire.isPending} onClick={oneClick(() => fire.mutate(newKey()))}>
            Fire it now
          </Button>
        </Group>
        {dry.isError ? <Alert color="red">{errorText(dry.error)}</Alert> : null}
        {fire.isError ? <Alert color="red">{errorText(fire.error)}</Alert> : null}
        {dry.data ? (
          <Stack gap={4} aria-label="The dry run">
            <Text size="sm">{dry.data.error ? `The condition cannot be evaluated: ${dry.data.error}` : dry.data.matched ? 'The condition matches; it would:' : 'The condition does not match: it would do nothing.'}</Text>
            {dry.data.matched
              ? dry.data.actions.map((action) => (
                  <Stack key={action.index} gap={2}>
                    <Text size="sm" fw={600}>
                      {action.index + 1}. {action.kind}
                    </Text>
                    <JsonView value={action.input} label={`Action ${action.index + 1} as it would run`} />
                  </Stack>
                ))
              : null}
          </Stack>
        ) : null}
      </Stack>
    </Card>
  );
}
