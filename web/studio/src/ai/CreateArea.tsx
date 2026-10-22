// The Create area (/create): a new page of a type its parent allows (P4), a
// brief for an assistant or a pipeline to write (G8: written, generated,
// reviewed, applied as a draft with suggestions), and conversations — the
// same ones the AI area lists — to think a piece through first.
import { Stack, Title } from '@mantine/core';
import { BriefList, BriefWorkspace, ConversationList, CreatePage } from '@zer0/ui';
import { Route, Routes, useParams } from 'react-router';

import { useSite } from '../site';
import { SectionTabs } from './AiArea';

const SECTIONS = [
  { value: 'page', label: 'A page' },
  { value: 'briefs', label: 'Briefs' },
  { value: 'conversations', label: 'Conversations' },
];

function Brief() {
  const { siteId } = useSite();
  const { id } = useParams();
  return <BriefWorkspace key={id} id={id === 'new' ? undefined : id} siteId={siteId} />;
}

export function CreateArea() {
  const { siteId } = useSite();
  return (
    <Stack>
      <Title order={2}>Create</Title>
      <SectionTabs base="/create" sections={SECTIONS} label="What to create">
        <Routes>
          <Route index element={<CreatePage siteId={siteId} />} />
          <Route path="briefs" element={<BriefList siteId={siteId} />} />
          <Route path="briefs/:id" element={<Brief />} />
          <Route path="conversations" element={<ConversationList siteId={siteId} />} />
        </Routes>
      </SectionTabs>
    </Stack>
  );
}
