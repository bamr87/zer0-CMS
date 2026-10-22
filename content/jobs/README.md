# `jobs/` — background work a person starts and follows

A job is work that takes longer than a request may: a site's sync, its write-back into its checkout, its doctor — and, as their milestones land, a render, a deploy, a report. It runs on Celery, writes its log as it goes, leaves artifacts behind, and can be cancelled. PLAN G4; TARGET.md § Sites — Manage.

| Model | What it is |
|---|---|
| `Job` | A kind (the handler that runs it), a status (`queued` → `running` → `succeeded` \| `failed` \| `cancelled`), the params it was started with, the Wagtail site it works on, who started it, its result and its error. A UUID public id |
| `JobLine` | One line of its log, numbered from 0, with a level (`info`, `warning`, `error`) |
| `JobArtifact` | A file it leaves behind (a doctor's `findings.jsonl`), served as its media type |

## Running one

An app registers what a kind does, and starts it where its subject lives (the site endpoints start a site's jobs, `sites/views.py`):

```python
from jobs import services as jobs


@jobs.handler("sync", exclusive=True)
def run_sync(job, ctx):
    ctx.log("Reading …")  # a JobLine, committed as it is written
    ctx.check()  # raises Cancelled once someone asked the job to stop
    ctx.artifact("report.txt", text)  # a JobArtifact
    return {"created": 3}  # the job's result


job = jobs.start("sync", user=person, site=site, params={})  # queued; runs after the transaction commits
```

`jobs.services.execute` is the worker's half (`jobs.tasks.run_job`): it marks the job running, calls the handler, and records how it ended — `Failed` ends it as failed with its reason, any other exception as failed with the exception (logged), `Cancelled` as cancelled. A command runs a job in-process with `start(..., enqueue=False)` and `execute` (`manage.py site_job`). An `exclusive` kind runs one at a time per site together with every other exclusive kind (sync and write-back are), so two of them never race on one checkout: starting one while another is queued or running is `Busy` (409 `job.busy`).

Cancelling is cooperative: a queued job is cancelled at once and never runs; a running one is asked to stop and stops at its handler's next `ctx.check()`; an ended one cannot be cancelled (409 `job.final`).

## The API

| Path | What |
|---|---|
| `GET /api/v2/jobs/` | The jobs the caller may see, newest first, by cursor; `?site=`, `?kind=`, `?status=` |
| `GET /api/v2/jobs/<id>/` | The job, its artifacts and its whole log |
| `GET /api/v2/jobs/<id>/stream/` | Its log as server-sent events: a `line` event per line as it is written (from `?after=`), then `status` and `end` — the agent runs' stream (api/views.py), opened with a comment frame and kept alive with comments |
| `POST /api/v2/jobs/<id>/cancel/` | Cancel it |
| `GET /api/v2/jobs/<id>/artifacts/<name>/` | One artifact, as a download |

One scope, `Job.objects.visible_to(user)`: the jobs a person started and the jobs of every site they may manage (sites/access.py); superusers see them all. Anything else is a 404. Tests: `tests/jobs/`.
