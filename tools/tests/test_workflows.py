"""Tests for the shape of the CI workflows that guard the platform's image and supply chain.

GitHub Actions cannot run here, so what a workflow will do is pinned by reading
it: the image workflow builds content/Dockerfile, runs Django's deploy checks on
it, boots the compose stack's roles on that one image and probes /readyz and
/version, on every change to what the image is built from or run by; CodeQL
scans the Python platform beside the TypeScript and the Ruby; and the pinned
Python and npm dependencies are audited for known vulnerabilities (report-only
until their first findings are triaged). Run:
`python3 -m unittest discover tools/tests`.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def load(name: str) -> dict:
    workflow = yaml.safe_load((WORKFLOWS / name).read_text())
    workflow["on"] = workflow.pop(True, workflow.get("on"))  # YAML 1.1 reads a bare `on:` key as true
    return workflow


def runs(job: dict) -> list[str]:
    return [str(step.get("run", "")) for step in job["steps"]]


def step_running(job: dict, text: str) -> dict:
    found = [step for step in job["steps"] if text in str(step.get("run", ""))]
    assert len(found) == 1, f"one step runs {text!r}, found {len(found)}"
    return found[0]


class ImageWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = load("image.yml")
        self.job = self.workflow["jobs"]["image"]

    def test_it_runs_on_every_change_to_what_the_image_is_built_from_or_run_by(self):
        wanted = {"content/**", "web/**", "schemas/**", "docker-compose.yml", ".github/workflows/image.yml"}
        for event in ("push", "pull_request"):
            with self.subTest(event=event):
                self.assertTrue(wanted <= set(self.workflow["on"][event]["paths"]), self.workflow["on"][event])
        self.assertEqual(self.workflow["on"]["push"]["branches"], ["main"])
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})

    def test_the_image_job_builds_boots_and_probes_the_image(self):
        commands = runs(self.job)
        order = [
            next(i for i, run in enumerate(commands) if needle in run)
            for needle in ("config -q", "docker build", "check --deploy", "--wait", "/readyz")
        ]
        self.assertEqual(order, sorted(order), "parse, build, deploy checks, boot, then probe")
        build = step_running(self.job, "docker build")["run"]
        self.assertIn("--file content/Dockerfile", build)
        self.assertIn('--build-arg GIT_SHA="$GITHUB_SHA"', build)
        boot = step_running(self.job, "--wait")["run"]
        self.assertIn("--no-build", boot, "every role runs the image this job built")
        for role in ("db", "redis", "content", "worker", "relay", "events"):
            self.assertIn(f" {role}", boot.split("--no-build", 1)[1], role)
        probe = step_running(self.job, "/readyz")["run"]
        for path in ("/healthz", "/readyz", "/version", "/studio/"):
            self.assertIn(f"http://127.0.0.1:8000{path}", probe, path)
        self.assertIn("GITHUB_SHA", probe, "/version must name the commit that was built")
        teardown = [step for step in self.job["steps"] if "down" in str(step.get("run", ""))]
        self.assertEqual([step.get("if") for step in teardown], ["always()"])

    def test_the_deploy_checks_get_a_generated_key_and_credential_keys(self):
        check = step_running(self.job, "check --deploy")["run"]
        self.assertIn("--fail-level ERROR", check)
        for name in ("SECRET_KEY", "AI_CREDENTIAL_KEYS"):
            self.assertIn(f"-e {name}", check, name)
        self.assertIn("secrets.token_urlsafe(50)", check, "a generated key, never the compose placeholder")
        self.assertIn("--network none", check)

    def test_the_roles_it_boots_are_the_compose_files_content_services(self):
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
        boot = step_running(self.job, "--wait")["run"]
        override = step_running(self.job, "pull_policy: never")["run"]
        for role in ("content", "worker", "relay", "events"):
            with self.subTest(role=role):
                self.assertIn("content", compose[role]["profiles"])
                self.assertIn(role, override.split("for role in", 1)[1].split(";", 1)[0])
                self.assertIn(f" {role}", boot)
        for role in ("db", "redis"):
            self.assertIn("content", compose[role]["profiles"])


class CodeqlTest(unittest.TestCase):
    def test_the_codeql_matrix_scans_python(self):
        workflow = load("codeql-analysis.yml")
        legs = workflow["jobs"]["analyze"]["strategy"]["matrix"]["include"]
        self.assertIn({"language": "python", "build-mode": "none"}, legs)
        self.assertEqual({leg["language"] for leg in legs}, {"javascript-typescript", "ruby", "python"})
        push, pull = workflow["on"]["push"]["paths"], workflow["on"]["pull_request"]["paths"]
        self.assertEqual(push, pull, "the two path lists are written out twice and must stay identical")
        self.assertIn("**/*.py", push)


class AuditTest(unittest.TestCase):
    def test_the_pinned_python_dependencies_are_audited(self):
        job = load("content.yml")["jobs"]["audit"]
        audit = step_running(job, "pip-audit -r")
        self.assertIn("-r requirements.txt", audit["run"])
        self.assertIn("-r requirements-providers.txt", audit["run"])
        self.assertIn("$GITHUB_STEP_SUMMARY", audit["run"])

    def test_the_studios_shipped_npm_dependencies_are_audited(self):
        job = load("web.yml")["jobs"]["web"]
        self.assertIn("npm audit --omit=dev --audit-level=high", runs(job))


if __name__ == "__main__":
    unittest.main()
