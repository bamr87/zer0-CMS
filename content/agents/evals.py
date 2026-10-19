"""Eval suites, the publish gate and the promotion rule (note §4, M14).

An `EvalCase` names an input (a page to build, a brief, a scenario for the
recorded model) and a rubric: a list of checks. `run_case` builds the case's
fixtures inside a savepoint, runs the agent against the revision under test,
scores the run, and rolls the fixtures back — an eval leaves an `EvalResult`
and nothing else. A case passes when every check passes and its score is not
below the same case's score for the previous live revision (a regression
fails even when the absolute bar is met).

`gate(definition, revision)` is what `AgentDefinition.publish()` asks:

- every case of the agent has a passing result for this revision, and there
  is at least one case (no suite, no publish);
- if the revision raises the agent's policy to `draft` or `auto`, the agent's
  suggestions have been accepted at `AGENT_PROMOTION_ACCEPT_RATE` or better
  over at least `AGENT_PROMOTION_MIN_DECISIONS` decisions (note §9, "evals
  before autonomy").
"""

import re
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction

from cms.models import POLICY_ORDER, POLICY_SUGGEST

from .models import AgentRun, EvalCase, EvalResult


@dataclass
class GateResult:
    passed: bool
    reasons: list = field(default_factory=list)


def accept_rate(agent) -> tuple[float | None, int]:
    from suggestions.models import Suggestion

    decided = Suggestion.objects.filter(agent=agent, status__in=[Suggestion.ACCEPTED, Suggestion.REJECTED])
    total = decided.count()
    if total == 0:
        return None, 0
    return decided.filter(status=Suggestion.ACCEPTED).count() / total, total


def gate(definition, revision) -> GateResult:
    reasons = []
    cases = list(EvalCase.objects.filter(agent_id=definition.pk))
    if not cases:
        reasons.append(f"{definition.slug} has no eval cases; a definition goes live only by passing its suite")
    for case in cases:
        result = EvalResult.objects.filter(case=case, revision=revision).order_by("-created_at", "-id").first()
        if result is None:
            reasons.append(f"{case} has not been run against revision {revision.pk}")
        elif not result.passed:
            reasons.append(f"{case} failed against revision {revision.pk} (score {result.score:.2f})")

    proposed = revision.as_object()
    # The policy that is live now, from its revision — not `definition.policy`,
    # which an in-memory edit of the latest revision object may have changed.
    live = definition.live_revision if definition.live and definition.live_revision_id else None
    current = live.as_object().policy if live is not None else POLICY_SUGGEST
    if POLICY_ORDER.index(proposed.policy) > POLICY_ORDER.index(current) and POLICY_ORDER.index(proposed.policy) > 1:
        rate, decided = accept_rate(definition)
        need_rate = settings.AGENT_PROMOTION_ACCEPT_RATE
        need_n = settings.AGENT_PROMOTION_MIN_DECISIONS
        if decided < need_n or rate is None or rate < need_rate:
            shown = "no decisions" if rate is None else f"{rate:.0%} of {decided}"
            reasons.append(
                f"promotion to {proposed.policy} needs an accept rate of {need_rate:.0%} over {need_n}+ decided "
                f"suggestions; {definition.slug} has {shown}"
            )
    return GateResult(passed=not reasons, reasons=reasons)


# ── scoring ────────────────────────────────────────────────────────────────


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text or "")


def _syllables(word: str) -> int:
    groups = re.findall(r"[aeiouy]+", word.lower())
    count = len(groups) - (1 if word.lower().endswith("e") and len(groups) > 1 else 0)
    return max(1, count)


def flesch(text: str) -> float:
    """Flesch reading ease; higher is easier. 60–70 is plain English."""
    words = _words(text)
    if not words:
        return 100.0
    sentences = max(1, len(re.findall(r"[.!?]+", text)) or 1)
    syllables = sum(_syllables(w) for w in words)
    return 206.835 - 1.015 * (len(words) / sentences) - 84.6 * (syllables / len(words))


def suggestion_text(s) -> str:
    payload = s.payload or {}
    value = payload.get("value")
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if isinstance(v, str))
    return str(value or "")


def score_run(run: AgentRun, checks: list[dict]) -> tuple[float, list[dict]]:
    from suggestions.guard import page_findings
    from suggestions.models import Suggestion

    suggestions = list(Suggestion.objects.filter(run=run).order_by("id"))
    details = []
    for spec in checks:
        name = spec["check"]
        ok, note = True, ""
        if name == "status":
            ok, note = run.status == spec["is"], f"status {run.status}"
        elif name == "suggestions":
            matching = [
                s
                for s in suggestions
                if s.op in spec.get("ops", [s.op]) and (not spec.get("fields") or s.field in spec["fields"])
            ]
            ok = len(matching) >= spec.get("min", 1) and len(matching) <= spec.get("max", 10_000)
            note = f"{len(matching)} matching suggestion(s)"
        elif name == "max_length":
            over = [s for s in suggestions if s.field == spec["field"] and len(suggestion_text(s)) > spec["max"]]
            ok, note = not over, f"{len(over)} over {spec['max']} chars"
        elif name == "brand_clean":
            errors = [f for s in suggestions for f in page_findings(suggestion_text(s)) if f["level"] == "error"]
            ok, note = not errors, "; ".join(f["message"] for f in errors)
        elif name == "readability":
            texts = [suggestion_text(s) for s in suggestions if suggestion_text(s)]
            worst = min((flesch(t) for t in texts), default=100.0)
            ok, note = worst >= spec["min"], f"lowest Flesch {worst:.0f}"
        elif name == "max_cost_usd":
            ok, note = float(run.cost_usd) <= float(spec["max"]), f"${run.cost_usd}"
        elif name == "output":
            value = (run.output or {}).get("json") or {}
            for key in spec.get("path", "").split(".") if spec.get("path") else []:
                value = value.get(key) if isinstance(value, dict) else None
            ok, note = value == spec["equals"], f"{spec.get('path')} = {value!r}"
        elif name == "verdict":
            verdict = (run.output or {}).get("verdict", {})
            ok, note = verdict.get("passed") is spec["passed"], f"verdict {verdict.get('passed')}"
        else:
            ok, note = False, f"unknown check {name!r}"
        details.append({"check": name, "passed": bool(ok), "note": note})
    passed = sum(1 for d in details if d["passed"])
    return (passed / len(details) if details else 0.0), details


# ── running ────────────────────────────────────────────────────────────────


class _Rollback(Exception):
    pass


def _make_page(parent, page_spec: dict):
    from cms import models as cms_models

    model = getattr(cms_models, page_spec.get("type", "ArticlePage"))
    page = model(
        title=page_spec["title"],
        slug=page_spec.get("slug", re.sub(r"[^a-z0-9]+", "-", page_spec["title"].lower()).strip("-")[:50] or "eval"),
        search_description=page_spec.get("search_description", ""),
        body=page_spec.get("body", []),
        **page_spec.get("fields", {}),
    )
    parent.add_child(instance=page)
    return page


def build_fixtures(spec: dict):
    """Create what an eval case runs against: the target page (a draft, as a
    page in moderation would be) and any `extra_pages` (published, so search
    and the graph can find them). Returns (target, extras)."""
    from wagtail.models import Page

    from cms.services import publish

    root = Page.get_first_root_node()
    extras = []
    for extra in spec.get("extra_pages", []):
        page = _make_page(root, extra)
        publish(page, user=None)
        extras.append(page)
    target = None
    if spec.get("page"):
        target = _make_page(root, spec["page"])
        target.save_revision()
    return target, extras


def run_case(case: EvalCase, revision, *, previous_score: float | None = None) -> EvalResult:
    from .runner import execute, start_run

    definition = case.agent
    outcome = {}
    try:
        with transaction.atomic():
            target, extras = build_fixtures(case.input)
            run_input = dict(case.input.get("input", {}))
            run_input.setdefault("scenario", case.name)
            if extras:
                run_input["fixture_ids"] = [p.pk for p in extras]
            run = start_run(
                definition, trigger="eval", target=target, input=run_input, revision=revision, enqueue=False
            )
            execute(run)
            score, details = score_run(run, case.checks)
            outcome = {"score": score, "details": details, "status": run.status, "error": run.error}
            raise _Rollback
    except _Rollback:
        pass
    score = outcome["score"]
    details = outcome["details"]
    if outcome["error"]:
        details.append({"check": "run", "passed": outcome["status"] == AgentRun.SUCCEEDED, "note": outcome["error"]})
    regression = previous_score is not None and score < previous_score
    if regression:
        details.append(
            {"check": "regression", "passed": False, "note": f"score {score:.2f} < previous {previous_score:.2f}"}
        )
    passed = all(d["passed"] for d in details) and not regression
    return EvalResult.objects.create(case=case, revision=revision, score=score, passed=passed, details=details)


def run_suite(definition, revision=None) -> list[EvalResult]:
    revision = revision or definition.get_latest_revision()
    previous = definition.live_revision if definition.live and definition.live_revision_id != revision.pk else None
    results = []
    for case in EvalCase.objects.filter(agent=definition):
        prev = None
        if previous is not None:
            last = EvalResult.objects.filter(case=case, revision=previous).order_by("-created_at", "-id").first()
            prev = last.score if last else None
        results.append(run_case(case, revision, previous_score=prev))
    return results
