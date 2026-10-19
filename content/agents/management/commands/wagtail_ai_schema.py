"""`manage.py wagtail_ai_schema [--out FILE | --check FILE]`: the content
schema agents read (agents/schema.py). `--check` exits 1 when the committed
copy (schemas/content/ai-schema.json) is out of date."""

from pathlib import Path

from django.core.management.base import BaseCommand

from agents.schema import dumps, export


class Command(BaseCommand):
    help = "Export the block and page schema as JSON Schema."

    def add_arguments(self, parser):
        parser.add_argument("--out")
        parser.add_argument("--check")

    def handle(self, *args, out=None, check=None, **options):
        text = dumps(export())
        if check:
            current = Path(check).read_text(encoding="utf-8") if Path(check).exists() else ""
            if current != text:
                self.stderr.write(f"{check} is out of date: run manage.py wagtail_ai_schema --out {check}")
                raise SystemExit(1)
            self.stdout.write(f"{check} is current (version {export()['version']})")
            return
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(text, encoding="utf-8")
            self.stdout.write(f"wrote {out} (version {export()['version']})")
            return
        self.stdout.write(text, ending="")
