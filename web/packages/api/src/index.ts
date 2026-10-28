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
// The AI content layer (/api/v2/ai/, PLAN G8).
export type Provider = Schemas['Provider'];
export type ModelEntry = Schemas['ModelEntry'];
export type OutputSchema = Schemas['OutputSchema'];
export type Assistant = Schemas['Assistant'];
export type Pipeline = Schemas['Pipeline'];
export type PipelineStep = Schemas['PipelineStep'];
export type StepSource = Schemas['SourceEnum'];
export type Brief = Schemas['Brief'];
export type BriefStatus = Schemas['BriefStatusEnum'];
export type Conversation = Schemas['Conversation'];
export type Message = Schemas['Message'];
export type Visibility = Schemas['VisibilityEnum'];
// Ideas and research (PLAN G14), and the AI-layer rows their workspaces show.
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
export type RunRef = Schemas['RunRef'];
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
// The outbox desk (/api/v2/outbox/, ADR 0007): the outbox harness's belt, arena trials and claim desk.
export type BeltSummary = Schemas['BeltSummary'];
export type Handoff = Schemas['Handoff'];
export type HandoffKind = Schemas['HandoffKindEnum'];
export type SendableKind = Schemas['SendableKindEnum'];
export type BeltMessage = Schemas['BeltMessage'];
export type DeadLetter = Schemas['DeadLetter'];
export type OutboxRunStatus = Schemas['OutboxRunStatusEnum'];
export type Trial = Schemas['Trial'];
export type TrialDetail = Schemas['TrialDetail'];
export type ArenaRow = Schemas['ArenaRow'];
export type TaskCard = Schemas['TaskCardRequest'];
export type Claim = Schemas['ClaimRequest'];
export type TimelineRow = Schemas['TimelineRowRequest'];
export type ClaimCheck = Schemas['ClaimCheck'];
export type ClaimCheckDetail = Schemas['ClaimCheckDetail'];
export type Verdict = Schemas['Verdict'];
export type Calibration = Schemas['Calibration'];
// Sites and jobs (PLAN G4).
export type ManagedSite = Schemas['ManagedSite'];
export type SiteDetail = Schemas['SiteDetail'];
export type SiteCandidate = Schemas['SiteCandidate'];
export type SiteSettings = Schemas['SiteSettings'];
export type DoctorFinding = Schemas['DoctorFinding'];
export type Job = Schemas['Job'];
export type JobDetail = Schemas['JobDetail'];
export type JobLine = Schemas['JobLine'];
// Distribution (PLAN G5): channels, the queue, the ledger, statistics.
export type DistributionChannel = Schemas['DistributionChannel'];
export type DistributionKind = Schemas['DistributionKindEnum'];
export type DistributionPost = Schemas['DistributionPost'];
export type DistributionPostDetail = Schemas['DistributionPostDetail'];
export type DistributionPostStatus = Schemas['DistributionPostStatusEnum'];
export type DistributionBlocker = Schemas['DistributionBlocker'];
export type DistributionFinding = Schemas['DistributionFinding'];
export type DistributionLedgerEntry = Schemas['DistributionLedgerEntry'];
export type DistributionStatistic = Schemas['DistributionStatistic'];
