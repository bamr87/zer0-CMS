// The studio's areas (docs/plan/TARGET.md § The studio), in navigation order.
// An area that is not built yet names the milestone that brings it
// (docs/plan/PLAN.md), so the navigation shows the whole product from day one
// and nobody mistakes an empty area for a broken one.
import {
  IconBook,
  IconBulb,
  IconChecklist,
  IconFilePlus,
  IconHome,
  IconNews,
  IconPencil,
  IconPhoto,
  IconSearch,
  IconSend,
  IconSettings,
  IconSparkles,
  IconWorld,
  type Icon,
} from '@tabler/icons-react';

export interface Area {
  path: string;
  label: string;
  summary: string;
  icon: Icon;
  /** The PLAN milestone that builds the area, while it is not built. */
  milestone?: string;
}

export const AREAS: Area[] = [
  { path: '/', label: 'Home', summary: 'What needs attention.', icon: IconHome },
  { path: '/write', label: 'Write', summary: 'Pages across your sites, the editor, revisions.', icon: IconPencil },
  { path: '/create', label: 'Create', summary: 'A new page of any type, a brief for AI to write, a conversation.', icon: IconFilePlus },
  { path: '/ideas', label: 'Ideas', summary: 'Boards, brainstorm sessions, and promoting an idea to a brief.', icon: IconBulb },
  { path: '/research', label: 'Research', summary: 'Sources and collections, capture, questions over sources, fact-checks.', icon: IconSearch },
  {
    path: '/newsroom',
    label: 'Newsroom',
    summary: 'Desks, the story budget, the calendar, assignments, fronts, corrections, newsletters.',
    icon: IconNews,
  },
  { path: '/books', label: 'Books', summary: 'Books, outlines, chapters, characters, continuity, manuscripts.', icon: IconBook },
  { path: '/review', label: 'Review', summary: 'Suggestions with their diffs: accept, reject, accept a whole run.', icon: IconChecklist },
  {
    path: '/ai',
    label: 'AI',
    summary: 'Agent runs, assistants, pipelines, output schemas, conversations, providers, models and automations.',
    icon: IconSparkles,
  },
  {
    path: '/sites',
    label: 'Sites',
    summary: 'The site registry and settings, render and deploy, monitoring, AIEO, improvement proposals.',
    icon: IconWorld,
    milestone: 'G4',
  },
  { path: '/media', label: 'Media', summary: 'The library, generation runs, compositions, the SVG studio.', icon: IconPhoto, milestone: 'G6' },
  { path: '/distribution', label: 'Distribution', summary: 'Channels, the queue, the ledger, statistics.', icon: IconSend, milestone: 'G5' },
  { path: '/admin', label: 'Admin', summary: 'People, groups and permissions, tokens, the audit log, jobs.', icon: IconSettings, milestone: 'G3' },
];
