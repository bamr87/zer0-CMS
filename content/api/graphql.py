"""GraphQL additions on top of Grapple's generated schema (note §2.5, M5, M12, M13).

Grapple derives a type for every page model from its `graphql_fields`; this
module adds what is not a model field:

- queries: `semanticSearch`, `related`, `graphSearch` (GraphRAG), `entities`,
  `suggestions` (authenticated), `agentRun` (authenticated), `aiSchema`;
- mutations: `requestAgentRun`, `acceptSuggestion`, `rejectSuggestion`.

Mutations route through the same functions the admin and REST views call
(`runner.start_run`, `suggestions.services.accept` / `reject`), and every
resolver reads runs and suggestions through the same scopes
(`AgentRun.objects.visible_to`, `Suggestion.objects.visible_to`), so a gate is
never only in GraphQL. A run and a suggestion are named by their UUID public ids
(`UUID`), in arguments and results alike; pages and revisions by Wagtail's ids
(P-D6).
"""

import graphene
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from graphene.types.generic import GenericScalar
from graphql import GraphQLError
from grapple.types.interfaces import get_page_interface
from wagtail.models import Page, Revision

from agents.models import AgentDefinition, AgentRun
from agents.runner import RunRefused, start_run
from agents.schema import export
from graph import services as graph
from suggestions.models import Suggestion
from suggestions.services import SuggestionError, accept, pending_for, reject


class Hit(graphene.ObjectType):
    page = graphene.Field(lambda: get_page_interface())
    score = graphene.Float()
    reasons = graphene.List(graphene.String)


class EntityType(graphene.ObjectType):
    id = graphene.Int()
    kind = graphene.String()
    name = graphene.String()
    slug = graphene.String()
    rel = graphene.String()


class SuggestionType(graphene.ObjectType):
    id = graphene.UUID()
    op = graphene.String()
    block_id = graphene.String()
    field = graphene.String()
    payload = GenericScalar()
    rationale = graphene.String()
    status = graphene.String()
    agent = graphene.String()
    run_id = graphene.UUID()

    @staticmethod
    def of(s: Suggestion):
        return SuggestionType(
            id=s.public_id,
            op=s.op,
            block_id=s.block_id,
            field=s.field,
            payload=s.payload,
            rationale=s.rationale,
            status=s.status,
            agent=s.agent.slug if s.agent else None,
            run_id=s.run.public_id if s.run else None,
        )


class StepType(graphene.ObjectType):
    idx = graphene.Int()
    kind = graphene.String()
    name = graphene.String()
    error = graphene.String()
    latency_ms = graphene.Int()


class AgentRunType(graphene.ObjectType):
    id = graphene.UUID()
    agent = graphene.String()
    status = graphene.String()
    trigger = graphene.String()
    output = GenericScalar()
    error = graphene.String()
    cost_usd = graphene.String()
    tokens = graphene.Int()
    trace_id = graphene.String()
    steps = graphene.List(StepType)

    @staticmethod
    def of(run: AgentRun):
        return AgentRunType(
            id=run.public_id,
            agent=run.agent.slug,
            status=run.status,
            trigger=run.trigger,
            output=run.output,
            error=run.error,
            cost_usd=str(run.cost_usd),
            tokens=run.tokens,
            trace_id=run.trace_id,
            steps=[
                StepType(idx=s.idx, kind=s.kind, name=s.name, error=s.error, latency_ms=s.latency_ms)
                for s in run.steps.all()
            ],
        )


def _hits(hits):
    return [Hit(page=h.page, score=h.score, reasons=h.reasons) for h in hits]


def _live_page(page_id):
    page = Page.objects.live().filter(pk=page_id).first()
    return page.specific if page else None


def _user(info):
    user = getattr(info.context, "user", None)
    return user if user is not None and user.is_authenticated else None


class Query(graphene.ObjectType):
    semantic_search = graphene.List(
        Hit, query=graphene.String(required=True), first=graphene.Int(default_value=10), page_type=graphene.String()
    )
    graph_search = graphene.List(
        Hit,
        query=graphene.String(required=True),
        first=graphene.Int(default_value=5),
        hops=graphene.Int(default_value=1),
    )
    related = graphene.List(
        Hit, page_id=graphene.Int(required=True), first=graphene.Int(default_value=5), kind=graphene.String()
    )
    entities = graphene.List(EntityType, page_id=graphene.Int(required=True))
    suggestions = graphene.List(SuggestionType, page_id=graphene.Int(required=True))
    agent_run = graphene.Field(AgentRunType, id=graphene.UUID(required=True))
    ai_schema = GenericScalar()

    def resolve_semantic_search(self, info, query, first=10, page_type=None):
        return _hits(graph.semantic_search(query, first=min(first, 50), page_type=page_type))

    def resolve_graph_search(self, info, query, first=5, hops=1):
        return _hits(graph.graph_rag(query, first=min(first, 20), hops=hops))

    def resolve_related(self, info, page_id, first=5, kind=None):
        page = _live_page(page_id)
        return _hits(graph.related(page, first=min(first, 20), kind=kind)) if page else []

    def resolve_entities(self, info, page_id):
        page = _live_page(page_id)
        if page is None:
            return []
        from graph.models import Edge, Entity

        page_ct = ContentType.objects.get_for_model(Page)
        entity_ct = ContentType.objects.get_for_model(Entity)
        edges = Edge.objects.filter(src_ct=page_ct, src_id=page.pk, dst_ct=entity_ct, valid_to__isnull=True)
        entities = {e.pk: e for e in Entity.objects.filter(pk__in=[e.dst_id for e in edges])}
        return [
            EntityType(
                id=e.dst_id,
                kind=entities[e.dst_id].kind,
                name=entities[e.dst_id].name,
                slug=entities[e.dst_id].slug,
                rel=e.rel,
            )
            for e in edges
            if e.dst_id in entities
        ]

    def resolve_suggestions(self, info, page_id):
        page = Page.objects.filter(pk=page_id).first()
        if page is None:
            return []
        return [SuggestionType.of(s) for s in pending_for(page.specific).visible_to(_user(info))]

    def resolve_agent_run(self, info, id):
        run = AgentRun.objects.visible_to(_user(info)).filter(public_id=id).select_related("agent").first()
        return AgentRunType.of(run) if run is not None else None

    def resolve_ai_schema(self, info):
        return export()


class RequestAgentRun(graphene.Mutation):
    class Arguments:
        agent = graphene.String(required=True)
        page_id = graphene.Int()
        input = GenericScalar()

    run_id = graphene.UUID()
    status = graphene.String()
    trace_id = graphene.String()

    def mutate(self, info, agent, page_id=None, input=None):
        from .access import may_request_run

        user = _user(info)
        definition = AgentDefinition.objects.filter(slug=agent).first()
        if definition is None:
            raise GraphQLError(f"no agent {agent}")
        page = None
        if page_id:
            found = Page.objects.filter(pk=page_id).first()
            if found is None:
                raise GraphQLError(f"no page {page_id}")
            page = found.specific
        allowed, reason = may_request_run(user, definition, page)
        if not allowed:
            raise GraphQLError(reason)
        try:
            run = start_run(definition, trigger="graphql", target=page, input=input or {}, user=user)
        except RunRefused as e:
            raise GraphQLError(str(e)) from e
        return RequestAgentRun(run_id=run.public_id, status=run.status, trace_id=run.trace_id)


class AcceptSuggestion(graphene.Mutation):
    class Arguments:
        id = graphene.UUID()
        ids = graphene.List(graphene.UUID)

    ok = graphene.Boolean()
    revision_id = graphene.Int()
    accepted = graphene.List(graphene.UUID)

    def mutate(self, info, id=None, ids=None):
        user = _user(info)
        wanted = [*([id] if id else []), *(ids or [])]
        suggestions = list(Suggestion.objects.visible_to(user).filter(public_id__in=wanted))
        if user is None or len(suggestions) != len(set(wanted)) or not wanted:
            raise GraphQLError("unknown suggestion, or not signed in")
        try:
            result = accept(suggestions, user)
        except (SuggestionError, PermissionDenied) as e:
            raise GraphQLError(str(e)) from e
        revision_id = result.pk if isinstance(result, Revision) else None
        return AcceptSuggestion(ok=True, revision_id=revision_id, accepted=[s.public_id for s in suggestions])


class RejectSuggestion(graphene.Mutation):
    class Arguments:
        id = graphene.UUID(required=True)
        reason = graphene.String()

    ok = graphene.Boolean()

    def mutate(self, info, id, reason=""):
        user = _user(info)
        suggestion = Suggestion.objects.visible_to(user).filter(public_id=id).first()
        if user is None or suggestion is None:
            raise GraphQLError("unknown suggestion, or not signed in")
        try:
            reject(suggestion, user, reason=reason)
        except (SuggestionError, PermissionDenied) as e:
            raise GraphQLError(str(e)) from e
        return RejectSuggestion(ok=True)


class Mutation(graphene.ObjectType):
    request_agent_run = RequestAgentRun.Field()
    accept_suggestion = AcceptSuggestion.Field()
    reject_suggestion = RejectSuggestion.Field()
