// @zer0/api — the platform's REST API for the studio and the extension: the
// types generated from the committed OpenAPI document, the shapes components
// pass around (named here once), and the same-origin session client.
import type { components } from './schema';

export type { components, operations, paths } from './schema';
export { createSessionClient, csrfFromCookie, type ApiClient, type SessionClientOptions } from './client';

type Schemas = components['schemas'];
export type Me = Schemas['Me'];
export type Site = Schemas['Site'];
export type PageSummary = Schemas['PageSummary'];
export type PageDetail = Schemas['PageDetail'];
export type PageStatus = Schemas['PageStatusEnum'];
export type PageType = Schemas['PageType'];
export type FieldSpec = Schemas['FieldSpec'];
export type Block = Schemas['Block'];
export type Revision = Schemas['Revision'];
export type RevisionCompare = Schemas['RevisionCompare'];
export type Suggestion = Schemas['Suggestion'];
export type Run = Schemas['Run'];
export type Step = Schemas['Step'];
export type ErrorEnvelope = Schemas['ErrorEnvelope'];
// Ideas and research (PLAN G14), and the AI-layer rows their workspaces show.
export type Visibility = Schemas['VisibilityEnum'];
export type Board = Schemas['Board'];
export type Idea = Schemas['Idea'];
export type IdeaStatus = Schemas['IdeaStatusEnum'];
export type Clusters = Schemas['Clusters'];
export type Collection = Schemas['Collection'];
export type Source = Schemas['Source'];
export type SourceSummary = Schemas['SourceList'];
export type Quote = Schemas['Quote'];
export type Citation = Schemas['Citation'];
export type Feed = Schemas['Feed'];
export type Question = Schemas['Question'];
export type FactCheck = Schemas['FactCheck'];
export type Finding = Schemas['Finding'];
export type AiMessage = Schemas['Message'];
export type Brief = Schemas['Brief'];
export type RunRef = Schemas['RunRef'];
