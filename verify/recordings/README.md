# `verify/recordings/` — the model answers the browser scenarios' platform gives

The browser scenarios (`verify/scenarios/studio-ai-*.yml`) drive the studio's AI workspaces against the platform that `verify/verify.yml` starts, and that platform must never reach a model. So its server runs with `AI_DEFAULT_PROVIDER=recorded`, `LLM_RECORDINGS_DIR=../verify/recordings` and `CELERY_TASK_ALWAYS_EAGER=true`: every assistant run answers from the files here, in the request that asked for it, the way the `recorded` adapter replays the agents' recordings (`content/ai/providers/recorded.py`, `content/agents/README.md` § Recordings).

They are written by hand, not recorded, and carry no `prompt_digest`, so they answer any assistant's prompt — which is the point for a demo and the reason nothing else reads them: the platform's tests use the `fake` provider and its evals replay `content/agents/recordings/`, whose digests do hold. Agents are synced and published (`seed_demo`) before the server starts with this directory.

| File | The `assistant` run's model call it answers |
|---|---|
| `assistant/default/00.json` | the first: an assistant's answer — a brief's text, a reply in a conversation, an answer on a page |
| `assistant/default/01.json` | the second: a brief's metadata step, as the bundled content-detail schema's JSON |
