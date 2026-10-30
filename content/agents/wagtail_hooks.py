"""Admin wiring for the harness: agent definitions as a snippet with revisions
(publishing one runs through the eval gate), and an "Agent runs" report with
cost and failure rates (note §4, observability)."""

from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.template.response import TemplateResponse
from django.urls import path, reverse
from wagtail import hooks
from wagtail.admin.menu import MenuItem
from wagtail.models import ModelLogEntry
from wagtail.snippets.models import register_snippet
from wagtail.snippets.views.snippets import SnippetViewSet

from .evals import gate
from .models import AgentDefinition, AgentRun, Memory


class AgentDefinitionViewSet(SnippetViewSet):
    model = AgentDefinition
    icon = "cogs"
    menu_label = "Agents"
    list_display = ["slug", "name", "role", "policy", "live"]


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


@hooks.register("before_publish")
def eval_gate_before_publish(request, obj):
    """The admin's view of the gate `AgentDefinition.publish()` enforces: say
    why, instead of a server error."""
    if not isinstance(obj, AgentDefinition):
        return None
    revision = obj.get_latest_revision()
    result = gate(obj, revision)
    if result.passed:
        return None
    from django.shortcuts import redirect

    messages.error(
        request,
        "Not published: " + "; ".join(result.reasons) + f" — run manage.py run_evals --agent {obj.slug} --publish",
    )
    return redirect(reverse("wagtailsnippets_agents_agentdefinition:edit", args=[obj.pk]))


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
