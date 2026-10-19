"""URL map of the content plane.

/healthz          liveness + database (compose and CI wait on it)
/admin/           Wagtail admin (pages, snippets, suggestions, agent runs)
/django-admin/    Django admin (users, tokens)
/api/v2/          Wagtail API v2 + agent runs, graph, suggestions, tools
/graphql/         GraphQL (Grapple + api/graphql.py); /graphiql/ in DEBUG
/mcp/             MCP over Streamable HTTP (mcp_server/)
/                 Wagtail page serving (preview; the sites are headless)
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls
from wagtail.documents import urls as wagtaildocs_urls

from api.urls import router
from api.views import ContentGraphQLView, healthz
from mcp_server.views import mcp_endpoint

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("django-admin/", admin.site.urls),
    path("admin/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("api/v2/", include("api.urls")),
    path("api/v2/", router.urls),
    path("graphql/", ContentGraphQLView.as_view(), name="graphql"),
    path("mcp/", mcp_endpoint, name="mcp"),
]
if settings.DEBUG:
    urlpatterns.append(path("graphiql/", ContentGraphQLView.as_view(graphiql=True), name="graphiql"))
urlpatterns.append(path("", include(wagtail_urls)))
