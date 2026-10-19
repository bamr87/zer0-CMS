"""The runner (M9): the model loop with a fake model, budgets and step limits,
recordings that refuse a changed prompt, tracing, and the completion event."""

from decimal import Decimal

import pytest

from agents.llm import Completion, FakeLLM, RecordedLLM, RecordingStale, ToolCall, fill, use_llm
from agents.models import AgentRun, AgentStep
from agents.runner import execute, start_run
from agents.tracing import trace
from outbox.models import OutboxEvent


def run_with(llm, definition, target, **kwargs):
    with use_llm(llm):
        run = start_run(definition, trigger="manual", target=target, enqueue=False, **kwargs)
        return execute(run)


@pytest.mark.django_db
def test_the_loop_runs_tools_and_stops_at_a_final_answer(agent, article):
    llm = FakeLLM(
        [
            Completion(
                tool_calls=[ToolCall("c1", "content.get_page", {"page_id": article.pk})],
                tokens_in=10,
                tokens_out=5,
                cost_usd=Decimal("0.01"),
            ),
            Completion(text='{"done": true}', tokens_in=20, tokens_out=5, cost_usd=Decimal("0.01")),
        ]
    )
    run = run_with(llm, agent("seo"), article)
    assert run.status == AgentRun.SUCCEEDED, run.error
    assert run.output["json"] == {"done": True}
    assert (run.tokens, run.cost_usd) == (40, Decimal("0.02"))
    assert list(run.steps.values_list("kind", "name")) == [
        ("llm", "anthropic/claude-haiku-5-5"),
        ("tool", "content.get_page"),
        ("llm", "anthropic/claude-haiku-5-5"),
    ]
    tool_message = llm.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool" and f'"id": {article.pk}' in tool_message["content"]
    assert run.prompt_version and run.schema_version


@pytest.mark.django_db
def test_a_refused_tool_call_is_shown_to_the_model_not_raised(agent, article):
    llm = FakeLLM(
        [
            Completion(tool_calls=[ToolCall("c1", "content.publish", {"page_id": article.pk})]),
            Completion(text="ok"),
        ]
    )
    run = run_with(llm, agent("seo"), article)
    assert run.status == AgentRun.SUCCEEDED
    assert (
        '"error": "not_found"' in llm.calls[1]["messages"][-1]["content"]
        or '"not_allowed"' in llm.calls[1]["messages"][-1]["content"]
    )


@pytest.mark.django_db
def test_the_budget_and_the_step_limit_end_a_run(agent, article):
    pricey = FakeLLM(
        [Completion(tool_calls=[ToolCall("c", "content.get_page", {"page_id": article.pk})], cost_usd=Decimal("1"))]
    )
    run = run_with(pricey, agent("seo"), article)
    assert run.status == AgentRun.FAILED and "budget" in run.error
    loops = FakeLLM(
        [Completion(tool_calls=[ToolCall(f"c{i}", "content.get_page", {"page_id": article.pk})]) for i in range(20)]
    )
    run = run_with(loops, agent("seo"), article)
    assert run.status == AgentRun.FAILED and "max_steps" in run.error


@pytest.mark.django_db
def test_a_finished_run_emits_agent_run_completed_with_its_trace(agent, article):
    with trace("4bf92f3577b34da6a3ce929d0e0e4736"):
        run = run_with(FakeLLM([Completion(text="nothing to do")]), agent("seo"), article)
    assert run.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    event = OutboxEvent.objects.get(type="agent.run.completed", subject=f"run:{run.pk}")
    assert event.data["status"] == "succeeded" and event.trace_id == run.trace_id
    assert event.envelope()["traceparent"].split("-")[1] == run.trace_id


@pytest.mark.django_db
def test_a_recording_made_against_another_prompt_is_refused(agent, article, tmp_path):
    (tmp_path / "seo" / "default").mkdir(parents=True)
    (tmp_path / "seo" / "default" / "00.json").write_text(
        '{"prompt_digest": "0000000000000000", "response": {"text": "x"}}'
    )
    run = run_with(RecordedLLM(tmp_path), agent("seo"), article)
    assert run.status == AgentRun.FAILED and "recorded against prompt" in run.error
    with pytest.raises(RecordingStale):
        RecordedLLM(tmp_path).complete(model="m", system="other", messages=[], tools=[], metadata={"agent": "seo"})


def test_placeholders_fill_with_types_kept():
    context = {"target": {"id": 7}, "results": [{"body": [{"id": "abc"}]}], "input": {"fixture_ids": [9]}}
    assert fill(
        {"page_id": "{{target.id}}", "block": "{{results.0.body.0.id}}", "dst": "page:{{input.fixture_ids.0}}"}, context
    ) == {"page_id": 7, "block": "abc", "dst": "page:9"}


@pytest.mark.django_db
def test_runs_through_celery_execute_on_commit(agent, article, django_capture_on_commit_callbacks):
    with use_llm(FakeLLM([Completion(text="done")])), django_capture_on_commit_callbacks(execute=True):
        run = start_run(agent("seo"), trigger="manual", target=article)
    run.refresh_from_db()
    assert run.status == AgentRun.SUCCEEDED
    assert AgentStep.objects.filter(run=run, kind="llm").count() == 1
