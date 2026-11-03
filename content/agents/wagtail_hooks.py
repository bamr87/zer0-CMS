"""Admin wiring for the harness: agent definitions as an inspect-only snippet,
and an "Agent runs" report with cost and failure rates (note §4,
observability).

A definition is its YAML file (ADR 0004 decision 8): the admin shows one, its
revisions and its history, and never adds, edits, deletes or publishes one —
an edit there would be a revision the file never sees, saved over by the next
`sync_agents`. Changing an agent is a pull request on
`agents/definitions/<slug>.yaml`; `sync_agents --publish` runs the eval gate.
"""

from django.db.models import Count, Q, Sum
from django.template.response import TemplateResponse
from django.urls import path, reverse
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.models import ModelLogEntry
from wagtail.permission_policies import ModelPermissionPolicy
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from .models import AgentDefinition, AgentRun, Memory


class InspectOnly(ModelPermissionPolicy):
    """Django's model permissions, `view` alone honoured — a superuser included."""

    def user_has_permission(self, user, action):
        return action == "view" and super().user_has_permission(user, action)


class AgentDefinitionViewSet(SnippetViewSet):
    model = AgentDefinition
    icon = "cogs"
    menu_label = "Agents"
    list_display = ["slug", "name", "role", "policy", "live"]
    inspect_view_enabled = True

    @property
    def permission_policy(self):
        return InspectOnly(self.model)


class MemoryViewSet(SnippetViewSet):
    model = Memory
    icon = "doc-full"
    menu_label = "Agent memory"
    list_display = ["scope", "scope_id", "key", "updated_at"]


register_snippet(AgentDefinitionViewSet)
register_snippet(MemoryViewSet)


@hooks.register("register_log_actions")
def run_log_actions(actions):
    """A run started (by whom, from where) and finished (how), in Wagtail's log."""
    actions.register_model(AgentRun, ModelLogEntry)
    actions.register_action("zer0.run.start", "Start an agent run", "Agent run started")
    actions.register_action("zer0.run.finish", "Finish an agent run", "Agent run finished")


def runs_report(request):
    runs = AgentRun.objects.select_related("agent").order_by("-created_at")[:100]
    by_agent = (
        AgentRun.objects.values("agent__slug")
        .annotate(
            total=Count("id"),
            failed=Count("id", filter=Q(status__in=["failed", "refused"])),
            cost=Sum("cost_usd"),
            tokens=Sum("tokens"),
        )
        .order_by("agent__slug")
    )
    return TemplateResponse(request, "agents/runs_report.html", {"runs": runs, "by_agent": by_agent})


@hooks.register("register_admin_urls")
def urls():
    return [path("reports/agent-runs/", runs_report, name="agent_runs_report")]


@hooks.register("register_reports_menu_item")
def runs_menu_item():
    return MenuItem("Agent runs", reverse("agent_runs_report"), icon_name="time", order=900)
