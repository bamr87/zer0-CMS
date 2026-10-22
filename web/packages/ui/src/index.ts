// @zer0/ui — the studio's workspaces and the components they are made of,
// written once for every host: the studio renders them today, the extension's
// webviews in PLAN G10. A host wraps them in <StudioProvider> (its client,
// its event streams, its navigation), Mantine and TanStack Query, and imports
// '@zer0/ui/ui.css' after Mantine's core styles.
export * from './ai';
export { BodyEditor } from './BodyEditor';
export { ApiError, call, errorText } from './call';
export { StudioProvider, useApi, useGo, useStream, type AiSection, type Destination, type Host, type OpenStream } from './context';
export { CreatePage } from './CreatePage';
export { DiffView } from './DiffView';
export { FieldsPanel, fromLocalInput, toLocalInput, type FieldValues } from './FieldsPanel';
export { Overview } from './Overview';
export { PageEditor, type PageAction } from './PageEditor';
export { PageList } from './PageList';
export { RevisionHistory } from './RevisionHistory';
export { RichText, roundTrips, throughEditor, type TextFormat } from './RichText';
export { RunList, RunStatus, RunTimeline, useLiveRun } from './RunTimeline';
export { STATUS_OPTIONS, StatusBadge } from './StatusBadge';
export { SuggestionInbox } from './SuggestionInbox';
