// The Newsroom workspace (TARGET.md § The newsroom): a site's desks, the story
// budget as a board by status, the editorial calendar, assignments, fronts,
// newsletters and authors — with a story's panel beside them and pitching a
// new story.
// Opening a story asks the host to go to it ({ to: 'story' }), so a story's
// panel has an address; the host renders this workspace with its `storyId`.
import { Alert, Button, Drawer, Group, Modal, Select, Stack, Tabs } from '@mantine/core';
import { useState } from 'react';

import { useGo } from '../context';
import { Assignments } from './Assignments';
import { Authors } from './Authors';
import { Board } from './Board';
import { Calendar } from './Calendar';
import { Fronts } from './Fronts';
import { Newsletters } from './Newsletters';
import { PitchForm } from './PitchForm';
import { useDesks } from './shared';
import { StoryPanel } from './StoryPanel';

export function Newsroom({ siteId, storyId }: { siteId?: number; storyId?: string }) {
  const go = useGo();
  const desks = useDesks(siteId);
  const [deskId, setDeskId] = useState<string | null>(null);
  const [tab, setTab] = useState<string | null>('budget');
  const [pitching, setPitching] = useState(false);
  const [notice, setNotice] = useState<{ story: string; text: string }>(); // what pitching left to say
  const desk = deskId ?? undefined;
  const query = { site: siteId, desk };
  const open = (id: string) => go({ to: 'story', id });
  const all = desks.data?.results ?? [];

  return (
    <Stack>
      <Group justify="space-between" align="flex-end">
        <Select
          label="Desk"
          placeholder="Every desk"
          clearable
          w={260}
          data={all.map((d) => ({ value: d.id, label: d.name }))}
          value={deskId}
          onChange={setDeskId}
        />
        <Button onClick={() => setPitching(true)} disabled={all.length === 0}>
          Pitch a story
        </Button>
      </Group>
      {desks.isSuccess && all.length === 0 ? (
        <Alert color="gray" title="No desk here yet">
          A desk is a section of a site and the people who run it; someone with the right to set up desks adds one (for parodynews:
          manage.py seed_parody_desk).
        </Alert>
      ) : null}
      <Tabs value={tab} onChange={setTab} keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="budget">Budget</Tabs.Tab>
          <Tabs.Tab value="calendar">Calendar</Tabs.Tab>
          <Tabs.Tab value="assignments">Assignments</Tabs.Tab>
          <Tabs.Tab value="fronts">Fronts</Tabs.Tab>
          <Tabs.Tab value="newsletters">Newsletters</Tabs.Tab>
          <Tabs.Tab value="authors">Authors</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="budget" pt="md">
          <Board query={query} onOpen={open} />
        </Tabs.Panel>
        <Tabs.Panel value="calendar" pt="md">
          <Calendar query={query} onOpen={open} />
        </Tabs.Panel>
        <Tabs.Panel value="assignments" pt="md">
          <Assignments query={query} onOpen={open} />
        </Tabs.Panel>
        <Tabs.Panel value="fronts" pt="md">
          <Fronts siteId={siteId} deskId={desk} />
        </Tabs.Panel>
        <Tabs.Panel value="newsletters" pt="md">
          <Newsletters siteId={siteId} />
        </Tabs.Panel>
        <Tabs.Panel value="authors" pt="md">
          <Authors />
        </Tabs.Panel>
      </Tabs>
      <Drawer
        opened={storyId !== undefined}
        onClose={() => go({ to: 'newsroom' })}
        position="right"
        size="xl"
        title="Story"
        closeButtonProps={{ 'aria-label': 'Close the story' }}
      >
        {storyId ? <StoryPanel storyId={storyId} notice={notice?.story === storyId ? notice.text : undefined} /> : null}
      </Drawer>
      <Modal opened={pitching} onClose={() => setPitching(false)} title="Pitch a story" size="lg" closeButtonProps={{ 'aria-label': 'Close' }}>
        <PitchForm
          desks={all}
          deskId={desk}
          onDone={(id, warning) => {
            setPitching(false);
            setNotice(warning ? { story: id, text: warning } : undefined);
            open(id);
          }}
        />
      </Modal>
    </Stack>
  );
}
