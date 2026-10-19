"""`review.submit_verdict`: how a review run ends. It only records the verdict
on the run; `workflow.services.finish_review` acts on it once the run is
final, so a run that crashes after submitting still leaves one decision."""

from agents.registry import ToolError, obj, tool


@tool(
    "review.submit_verdict",
    effect="propose",
    description="End a review: pass or fail the page, with comments on specific blocks and a one-line summary.",
    input_schema=obj(
        {
            "passed": {"type": "boolean"},
            "summary": {"type": "string", "maxLength": 2000},
            "comments": {
                "type": "array",
                "maxItems": 50,
                "items": obj(
                    {"block_id": {"type": "string"}, "text": {"type": "string", "minLength": 1, "maxLength": 2000}},
                    required=["text"],
                ),
            },
        },
        required=["passed", "summary"],
    ),
)
def submit_verdict(ctx, passed, summary, comments=None):
    if ctx.run is None:
        raise ToolError("not_allowed", "a verdict belongs to a review run")
    ctx.run.output = {
        **(ctx.run.output or {}),
        "verdict": {"passed": passed, "summary": summary, "comments": comments or []},
    }
    ctx.run.save(update_fields=["output"])
    return {"recorded": True, "passed": passed}
