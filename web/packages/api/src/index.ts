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
// The newsroom (PLAN G15).
export type Desk = Schemas['Desk'];
export type Story = Schemas['Story'];
export type StoryDetail = Schemas['StoryDetail'];
export type StoryStatus = Schemas['StoryStatusEnum'];
export type StoryCard = Schemas['StoryCard'];
export type Person = Schemas['Person'];
export type Author = Schemas['Author'];
export type Front = Schemas['Front'];
export type FrontSlot = Schemas['FrontSlot'];
export type ResolvedSlot = Schemas['ResolvedSlot'];
export type Newsletter = Schemas['Newsletter'];
export type Issue = Schemas['Issue'];
