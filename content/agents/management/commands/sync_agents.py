"""`manage.py sync_agents [--publish]`: load agents/definitions/*.yaml.

With `--publish`, every definition with an unpublished revision then runs its
eval suite against that revision and goes live if the gate passes
(agents/evals.py). Exit status 1 if any definition was refused.
"""

from django.core.management.base import BaseCommand

from agents.evals import gate, run_suite
from agents.models import EvalGateError
from agents.sync import sync


class Command(BaseCommand):
    help = "Sync agent definitions from YAML; optionally evaluate and publish them."

    def add_arguments(self, parser):
        parser.add_argument("--publish", action="store_true")
        parser.add_argument("--directory")

    def handle(self, *args, publish=False, directory=None, **options):
        refused = 0
        for definition, state in sync(directory):
            line = f"{definition.slug:<10} {state}"
            if publish:
                revision = definition.get_latest_revision()
                if definition.live and definition.live_revision_id == revision.pk:
                    line += ", live"
                else:
                    results = run_suite(definition, revision)
                    passed = sum(r.passed for r in results)
                    result = gate(definition, revision)
                    if result.passed:
                        try:
                            revision.publish(log_action=False)
                            line += f", evals {passed}/{len(results)}, published revision {revision.pk}"
                        except EvalGateError as e:
                            refused += 1
                            line += f", refused: {e}"
                    else:
                        refused += 1
                        line += f", evals {passed}/{len(results)}, refused: {'; '.join(result.reasons)}"
            self.stdout.write(line)
        if refused:
            raise SystemExit(1)
