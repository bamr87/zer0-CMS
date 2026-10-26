"""`fake`: scripted completions, for unit tests (and `agents.llm.FakeLLM`).

Each `complete()` takes the next item of the script: a `Completion`, a dict in
the recordings' shape (`{"text", "tool_calls", "tokens_in", …}`, with
`{{placeholders}}` filled from the call's context), an exception to raise, or a
callable that receives the call and returns one of those. An empty script
answers with empty text. Every call is kept in `calls`, so a test can assert on
exactly what was sent. It never touches a network.
"""

from .base import Completion, ModelInfo, Provider
from .recorded import completion_from, fill


class FakeProvider(Provider):
    slug = "fake"
    display_name = "Fake (scripted, for tests)"
    capabilities = frozenset({"complete", "stream", "structured", "tools", "models"})
    default_model = "fake-1"
    static_models = (ModelInfo("fake-1", "Fake model", {"structured_output": True, "tools": True}),)

    def __init__(self, script=(), *, settings=None):
        super().__init__(settings=settings)
        self.script = list(script)
        self.calls: list[dict] = []

    def complete(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None) -> Completion:
        call = {"model": model, "system": system, "messages": messages, "tools": tools, "metadata": metadata}
        if schema is not None:
            call["schema"] = schema
        if params:
            call["params"] = params
        self.calls.append(call)
        if not self.script:
            return Completion(text="", model=model)
        nxt = self.script.pop(0)
        if callable(nxt) and not isinstance(nxt, type):
            nxt = nxt(call)
        if isinstance(nxt, BaseException):
            raise nxt
        if isinstance(nxt, Completion):
            return nxt
        return completion_from(fill(nxt, (metadata or {}).get("context", {})), model)

    def stream(self, **request):
        text = self.complete(**request).text
        for start in range(0, len(text), 16):
            yield text[start : start + 16]
