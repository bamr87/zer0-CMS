"""`manage.py run_evals (--agent SLUG | --all) [--recorded] [--publish]`.

Runs each agent's eval suite against its latest revision and prints one line
per case. `--recorded` forces the recorded model backend (CI uses it: no
network, no keys, no cost). `--publish` publishes revisions whose gate
passes. Exit status 1 when any case fails — which is how an eval regression
fails CI (M14).
"""

from django.core.management.base import BaseCommand, CommandError
from django.test import override_settings

from agents.evals import gate, run_suite
from agents.models import AgentDefinition


class Command(BaseCommand):
    help = "Run agent eval suites."

    def add_arguments(self, parser):
        parser.add_argument("--agent", action="append", default=[])
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--recorded", action="store_true")
        parser.add_argument("--publish", action="store_true")

    def handle(self, *args, agent, all=False, recorded=False, publish=False, **options):
        if not agent and not all:
            raise CommandError("name an agent with --agent or pass --all")
        definitions = AgentDefinition.objects.all() if all else AgentDefinition.objects.filter(slug__in=agent)
        if not all and definitions.count() != len(set(agent)):
            raise CommandError(
                f"unknown agent(s): {', '.join(sorted(set(agent) - set(definitions.values_list('slug', flat=True))))}"
            )
        failed = 0
        with override_settings(LLM_BACKEND="recorded") if recorded else _null():
            for definition in definitions:
                revision = definition.get_latest_revision()
                for result in run_suite(definition, revision):
                    failed += 0 if result.passed else 1
                    mark = "pass" if result.passed else "FAIL"
                    notes = "; ".join(d["note"] for d in result.details if not d["passed"])
                    self.stdout.write(
                        f"{mark}  {definition.slug}/{result.case.name}  score {result.score:.2f}  {notes}"
                    )
                if publish:
                    g = gate(definition, revision)
                    if g.passed and not (definition.live and definition.live_revision_id == revision.pk):
                        revision.publish(log_action=False)
                        self.stdout.write(f"      published {definition.slug} revision {revision.pk}")
        if failed:
            raise SystemExit(1)


class _null:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False
