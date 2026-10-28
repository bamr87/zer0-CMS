// @zer0/ui — the studio's workspaces and the components they are made of,
// written once for every host: the studio renders them today, the extension's
// webviews in PLAN G10. A host wraps them in <StudioProvider> (its client,
// its event streams, its navigation), Mantine and TanStack Query, and imports
// '@zer0/ui/ui.css' after Mantine's core styles.
export * from './ai';
export * from './automations';
export { BodyEditor } from './BodyEditor';
export { BookAssist } from './books/BookAssist';
export { BookShelf, PremiseToBook } from './books/BookShelf';
export { BookView } from './books/BookView';
export { ChapterWriter } from './books/ChapterWriter';
export { ApiError, call, errorText } from './call';
export { StudioProvider, useApi, useGo, useStream, type AiSection, type Destination, type Host, type OpenStream, type OutboxTab } from './context';
export type { DistributionTab } from './context';
export { CreatePage } from './CreatePage';
export { DiffView } from './DiffView';
export { Distribute } from './distribution/Compose';
export { Distribution } from './distribution/Distribution';
export { FieldsPanel, fromLocalInput, toLocalInput, type FieldValues } from './FieldsPanel';
export { CaptureIdea } from './ideas/CaptureIdea';
export { IdeasWorkspace } from './ideas/IdeasWorkspace';
export { Newsroom } from './newsroom/Newsroom';
export { StoryPanel } from './newsroom/StoryPanel';
export { ClaimCheckView } from './outbox/ClaimCheckView';
export { OutboxDesk } from './outbox/OutboxDesk';
export { TrialView } from './outbox/TrialView';
export { Overview } from './Overview';
export { PageEditor, type PageAction } from './PageEditor';
export { PageList } from './PageList';
export { PageResearch } from './research/PageResearch';
export { ResearchWorkspace } from './research/ResearchWorkspace';
export { SourceView } from './research/SourceView';
export { RevisionHistory } from './RevisionHistory';
export { RichText, roundTrips, throughEditor, type TextFormat } from './RichText';
export { RunList, RunStatus, RunTimeline, useLiveRun } from './RunTimeline';
export { STATUS_OPTIONS, StatusBadge } from './StatusBadge';
export { JobLog, JobStatus, useLiveJob } from './sites/JobLog';
export { RegisterSite, SitesWorkspace } from './sites/SitesWorkspace';
export { SiteView } from './sites/SiteView';
export { SuggestionInbox } from './SuggestionInbox';
