"""The runner: a hand-rolled state machine over `AgentRun` / `AgentStep`
(PLAN-D3).

    queued ──► running ──► succeeded
                  │  └───► failed     (an error, the budget, the step limit)
                  └──────► refused    (policy off, not live, no principal)

`start_run` creates a queued run and hands it to Celery once the creating
transaction commits; `execute` is what the worker runs. A run either calls a
deterministic handler (`AgentDefinition.handler`) or loops: ask the model,
run the tool calls it makes through the registry, feed the results back, stop
when it answers without a tool call. Every model call and tool call is a step
row, written as it happens, so the run table is the checkpoint — a crashed run
can be read back step by step, and nothing a step did is lost.

Nothing here writes content. Writing is what tools do, under the registry's
checks; the runner only decides which tool the model asked for.

`run_finished` is sent when a run reaches a final status, in the transaction
that records it, whether or not its handler ever ran — so whatever the run was
filling (an AI layer brief or reply) can take the run's outcome even when the
run was refused before the handler started.
"""

import copy
import json
import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone
from django.utils.module_loading import import_string
from wagtail.log_actions import log

from .llm import RecordingMissing, RecordingStale, get_llm
from .models import AgentRun, AgentStep
from .principals import is_agent_user
from .registry import ToolContext, ToolError, registry
from .tracing import current_trace_id, new_trace_id, span, trace

run_finished = Signal()  # sender=AgentRun, run=<the run, final>


class RunRefused(Exception):
    pass


class BudgetExceeded(Exception):
    """The run spent its budget or its steps without a final answer."""


def start_run(
    agent,
    *,
    trigger,
    target=None,
    input=None,
    user=None,
    parent=None,
    event_id="",
    revision=None,
    enqueue=True,
    options=None,
) -> AgentRun:
    """Queue a run of `agent` (`options`: Celery's, such as a time limit or a
    queue). Non-eval runs always use the live revision; a definition that has
    never gone live cannot run outside its evals."""
    if revision is None:
        if trigger != "eval" and not agent.live:
            raise RunRefused(f"{agent.slug} is not live: publish a revision that passed its evals first")
        revision = agent.live_revision if trigger != "eval" else agent.get_latest_revision()
    run = AgentRun.objects.create(
        agent=agent,
        revision=revision,
        trigger=trigger,
        target_ct=ContentType.objects.get_for_model(target, for_concrete_model=False) if target is not None else None,
        target_id=target.pk if target is not None else None,
        input=input or {},
        started_by=user if (user is not None and user.is_authenticated) else None,
        started_by_event=event_id,
        parent_run=parent,
        trace_id=current_trace_id() or new_trace_id(),
    )
    log(
        run,
        "zer0.run.start",
        user=run.started_by,
        data={"agent": agent.slug, "trigger": trigger, "target": run.target_id},
    )
    if enqueue:
        from .tasks import run_agent

        transaction.on_commit(lambda: run_agent.apply_async((run.pk,), **(options or {})))
    return run


def execute(run: AgentRun) -> AgentRun:
    with trace(run.trace_id), span("agent.run", agent=run.agent.slug, run_id=run.pk, trigger=run.trigger):
        return _execute(run)


def _execute(run: AgentRun) -> AgentRun:
    if run.is_final:
        return run
    config = apply_profile(run.config(), run)
    from .schema import schema_version

    run.status = AgentRun.RUNNING
    run.started_at = timezone.now()
    run.prompt_version = config.prompt_version
    run.schema_version = schema_version()
    run.save(update_fields=["status", "started_at", "prompt_version", "schema_version"])

    user = get_user_model().objects.filter(username=config.username).first()
    if not is_agent_user(user):
        return _finish(run, AgentRun.REFUSED, error=f"no active agent user {config.username}")
    if config.policy == "off":
        return _finish(run, AgentRun.REFUSED, error=f"{config.slug} has policy off")

    ctx = ToolContext(user=user, agent=config, run=run, trigger=run.trigger, extra={"target": run.target})
    try:
        if config.handler:
            output = import_string(config.handler)(run, ctx)
        else:
            output = model_loop(run, ctx, config)
    except BudgetExceeded as e:
        return _finish(run, AgentRun.FAILED, error=str(e))
    except (RecordingMissing, RecordingStale) as e:
        return _finish(run, AgentRun.FAILED, error=str(e))
    except ToolError as e:
        return _finish(run, AgentRun.FAILED, error=str(e))
    except Exception as e:  # noqa: BLE001 — the run records the failure; the worker stays up
        return _finish(run, AgentRun.FAILED, error=f"{type(e).__name__}: {e}")
    return _finish(run, AgentRun.SUCCEEDED, output=output)


def apply_profile(config, run: AgentRun):
    """A definition may carry profiles (`profile.profiles.<name>`) that swap its
    handler or system prompt — the drafter's `abc` and `story` (M12). The run
    picks one by `input.profile`, else by its target's own `profile` field."""
    profiles = (config.profile or {}).get("profiles", {})
    name = (run.input or {}).get("profile") or getattr(run.target, "profile", None)
    if name not in profiles:
        return config
    chosen = copy.copy(config)
    chosen.handler = profiles[name].get("handler", "")
    chosen.system_prompt = profiles[name].get("system_prompt", config.system_prompt)
    return chosen


def first_message(run: AgentRun) -> str:
    target = run.target
    payload = {"input": run.input, "trigger": run.trigger}
    if target is not None:
        payload["target"] = {
            "id": target.pk,
            "type": target._meta.label,
            "title": getattr(target, "title", str(target)),
        }
    return json.dumps(payload, sort_keys=True, default=str)


def _context(run: AgentRun, results: list) -> dict:
    target = run.target
    return {
        "target": {"id": target.pk if target is not None else None},
        "input": run.input,
        "results": results,
    }


def model_loop(
    run: AgentRun,
    ctx: ToolContext,
    config,
    *,
    llm=None,
    model=None,
    system=None,
    messages=None,
    schema=None,
    params=None,
    step_offset=0,
) -> dict:
    """Ask the model, run the tool calls it makes, feed the results back, stop at
    an answer with no tool call. A definition's run uses its own model, prompt
    and backend; a handler (the AI content layer's assistants, ai/handlers.py)
    passes its own client, persona, history, output schema and parameters, and
    `step_offset` when it calls the loop again within one run (the recording
    step numbers keep counting)."""
    llm = llm or get_llm()
    run.llm_backend = getattr(llm, "name", type(llm).__name__)
    run.save(update_fields=["llm_backend"])
    tools = [t.spec() for t in registry.for_context(ctx)]
    if tools and "tools" not in getattr(llm, "capabilities", {"tools"}):
        raise ValueError(f"{run.llm_backend} has no tool calls and {config.slug} uses tools: choose another backend")
    messages = list(messages) if messages is not None else [{"role": "user", "content": first_message(run)}]
    model = model or config.model
    system = config.system_prompt if system is None else system
    options = {key: value for key, value in (("schema", schema), ("params", params)) if value}
    results: list = []
    scenario = run.input.get("scenario", "default")

    for step in range(config.max_steps):
        started = time.monotonic()
        with span("agent.llm", model=model, step=step_offset + step):
            completion = llm.complete(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                metadata={
                    "agent": config.slug,
                    "scenario": scenario,
                    "step": step_offset + step,
                    "context": _context(run, results),
                },
                **options,
            )
        AgentStep.objects.create(
            run=run,
            idx=run.next_step_index(),
            kind=AgentStep.LLM,
            name=completion.model or model,
            args={"step": step, "messages": len(messages)},
            result={
                "text": completion.text,
                "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in completion.tool_calls],
            },
            latency_ms=int((time.monotonic() - started) * 1000),
            tokens=completion.tokens,
            cost_usd=completion.cost_usd,
        )
        run.tokens += completion.tokens
        run.cost_usd += completion.cost_usd
        run.save(update_fields=["tokens", "cost_usd"])
        if run.cost_usd > Decimal(config.budget_usd):
            raise BudgetExceeded(f"spent ${run.cost_usd} of a ${config.budget_usd} budget")

        if not completion.tool_calls:
            output = final_output(completion.text)
            if getattr(completion, "data", None) is not None:
                output["json"] = completion.data  # a provider's native structured output
            return output

        messages.append(
            {
                "role": "assistant",
                "content": completion.text,
                "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in completion.tool_calls],
            }
        )
        for call in completion.tool_calls:
            try:
                result = registry.call(call.name, call.arguments, ctx)
            except ToolError as e:
                # The model sees the refusal and may correct itself; the step
                # row already records it.
                result = e.as_dict()
            results.append(result)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(result, default=str)}
            )
    raise BudgetExceeded(f"stopped after max_steps={config.max_steps} without a final answer")


def final_output(text: str) -> dict:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").split("\n", 1)[-1]
    try:
        return {"text": text, "json": json.loads(stripped)}
    except (ValueError, TypeError):
        return {"text": text}


def _finish(run: AgentRun, status: str, output=None, error="") -> AgentRun:
    from outbox.services import emit
    from suggestions.models import Suggestion

    with transaction.atomic():
        run.finish(status, output=output, error=error)
        run.save(update_fields=["status", "output", "error", "finished_at"])
        emit(
            "agent.run.completed",
            subject=f"run:{run.pk}",
            data={
                "run_id": run.pk,
                "agent": run.agent.slug,
                "status": status,
                "trigger": run.trigger,
                "cost_usd": format(run.cost_usd.normalize(), "f") if run.cost_usd else "0",
                "tokens": run.tokens,
                "suggestions": Suggestion.objects.filter(run=run).count(),
            },
        )
        run_finished.send(sender=AgentRun, run=run)
        log(run, "zer0.run.finish", data={"agent": run.agent.slug, "status": status, "error": error[:500]})
    if run.trigger == "workflow":
        from workflow.services import finish_review

        finish_review(run)
    return run
