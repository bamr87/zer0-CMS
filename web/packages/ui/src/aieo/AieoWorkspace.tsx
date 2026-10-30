// The AIEO workspace (Sites → AIEO): audit a page, a URL or a site with the
// score breakdown and its evidence; optimize or scrub into suggestions; the
// pattern library; the AIEO agents; citations over time; the site's
// connectors and priorities; reports; the brand context and the lifecycle.
// Each section is a tab the host can route to (`{ to: 'aieo', section }`).
import { Tabs } from '@mantine/core';

import { useGo, type AieoSection } from '../context';
import { Agents } from './Agents';
import { Audits } from './Audits';
import { Citations } from './Citations';
import { Connectors, Priorities } from './Connectors';
import { Context } from './Context';
import { Patterns } from './Patterns';
import { Reports } from './Reports';
import { Rewrite } from './Rewrite';

const SECTIONS: { value: AieoSection; label: string }[] = [
  { value: 'audit', label: 'Audit' },
  { value: 'optimize', label: 'Optimize' },
  { value: 'patterns', label: 'Patterns' },
  { value: 'agents', label: 'Agents' },
  { value: 'citations', label: 'Citations' },
  { value: 'connectors', label: 'Connectors' },
  { value: 'priorities', label: 'Priorities' },
  { value: 'reports', label: 'Reports' },
  { value: 'context', label: 'Context' },
];

export function AieoWorkspace({ siteId, section = 'audit' }: { siteId?: number; section?: AieoSection }) {
  const go = useGo();
  return (
    <Tabs value={section} onChange={(next) => go({ to: 'aieo', section: (next as AieoSection | null) ?? 'audit' })} keepMounted={false}>
      <Tabs.List>
        {SECTIONS.map((s) => (
          <Tabs.Tab key={s.value} value={s.value}>
            {s.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
      <Tabs.Panel value="audit" pt="md">
        <Audits siteId={siteId} />
      </Tabs.Panel>
      <Tabs.Panel value="optimize" pt="md">
        <Rewrite siteId={siteId} />
      </Tabs.Panel>
      <Tabs.Panel value="patterns" pt="md">
        <Patterns siteId={siteId} />
      </Tabs.Panel>
      <Tabs.Panel value="agents" pt="md">
        <Agents siteId={siteId} />
      </Tabs.Panel>
      <Tabs.Panel value="citations" pt="md">
        <Citations siteId={siteId} />
      </Tabs.Panel>
      <Tabs.Panel value="connectors" pt="md">
        <Connectors siteId={siteId} />
      </Tabs.Panel>
      <Tabs.Panel value="priorities" pt="md">
        <Priorities siteId={siteId} />
      </Tabs.Panel>
      <Tabs.Panel value="reports" pt="md">
        <Reports siteId={siteId} />
      </Tabs.Panel>
      <Tabs.Panel value="context" pt="md">
        <Context siteId={siteId} />
      </Tabs.Panel>
    </Tabs>
  );
}
