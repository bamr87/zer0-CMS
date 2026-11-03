"""Adds this app's queries and mutations to Grapple's schema, and puts
`PublicMedia` first, where its resolvers shadow Grapple's (api/graphql.py)."""

from wagtail import hooks


@hooks.register("register_schema_query")
def add_queries(query_mixins):
    from .graphql import PublicMedia, Query

    query_mixins.insert(0, PublicMedia)
    query_mixins.append(Query)


@hooks.register("register_schema_mutation")
def add_mutations(mutation_mixins):
    from .graphql import Mutation

    mutation_mixins.append(Mutation)
