"""URL map of the platform.

/healthz          liveness: the process answers, touching nothing
/readyz           readiness: database, cache and Redis, 503 when one is down
/version          name, version, commit, built_at
/admin/           Wagtail admin (pages, snippets, suggestions, agent runs)
/django-admin/    Django admin
/api/v2/          Wagtail API v2 + agent runs, graph, suggestions, tools
/api/v2/ai/       the AI content layer: providers, models, schemas, assistants, pipelines, briefs, conversations
/api/v2/ideas/    ideas, boards, capture, brainstorm, clusters, promotion
/api/v2/research/ collections, sources, quotes, citations, feeds, questions, fact-checks
/api/v2/newsroom/ the newsroom: desks, stories, authors, fronts, newsletters, issues, subscriptions
/newsletters/     the pages a newsletter email's links open: confirm, unsubscribe (newsroom/urls.py)
/api/v2/books/    books: the shelf, a book's overview, chapters, validation, manuscripts, the book assistant
/api/v2/aieo/     AIEO: scores, audits, patterns, rewrites, agents, citations, connectors, priorities, reports
/api/v2/openapi.json, /api/v2/docs/  the OpenAPI document and its UI (ops/openapi.py)
/graphql/         GraphQL (Grapple + api/graphql.py); /graphiql/ in DEBUG
/mcp/             MCP over Streamable HTTP (mcp_server/)
/studio/          the studio (web/studio), built; every path under it is its index.html (api/studio.py)
/                 Wagtail page serving (preview; the sites are headless)

Errors Django answers itself — an unknown path, a CSRF failure, a crash — use
the same JSON envelope as the APIs on the API paths (ops/errors.py).
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularJSONAPIView, SpectacularSwaggerView
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from api.studio import studio
from api.urls import router
from api.views import ContentGraphQLView
from mcp_server.views import mcp_endpoint
from newsroom.urls import subscription_pages
from ops.views import healthz, readyz, version

handler400 = "ops.errors.bad_request"
handler403 = "ops.errors.permission_denied"
handler404 = "ops.errors.not_found"
handler500 = "ops.errors.server_error"

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("version", version, name="version"),
    path("django-admin/", admin.site.urls),
    path("admin/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("api/v2/openapi.json", SpectacularJSONAPIView.as_view(), name="openapi"),
    path("api/v2/ai/", include("ai.urls")),
    path("api/v2/ideas/", include("ideas.urls")),
    path("api/v2/research/", include("research.urls")),
    path("api/v2/newsroom/", include("newsroom.urls")),
    path("newsletters/", include(subscription_pages)),
    path("api/v2/books/", include("books.urls")),
    path("api/v2/aieo/", include("aieo.urls")),
    path("api/v2/", include("api.urls")),
    path("api/v2/", router.urls),
    path("graphql/", ContentGraphQLView.as_view(), name="graphql"),
    path("mcp/", mcp_endpoint, name="mcp"),
    re_path(r"^studio(?:/(?P<path>.*))?$", studio, name="studio"),
]
if settings.API_DOCS_ENABLED:
    urlpatterns.append(path("api/v2/docs/", SpectacularSwaggerView.as_view(url_name="openapi"), name="api-docs"))
if settings.DEBUG:
    urlpatterns.append(path("graphiql/", ContentGraphQLView.as_view(graphiql=True), name="graphiql"))
urlpatterns.append(path("", include(wagtail_urls)))
