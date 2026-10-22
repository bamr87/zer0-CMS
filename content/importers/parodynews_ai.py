"""parodynews's AI tables → the AI content layer (ADR 0006 decision 7, PLAN §4.4).

Called by `importers.parodynews.import_dump` on the same `dumpdata` rows:

| parodynews                               | here                                                 |
|------------------------------------------|------------------------------------------------------|
| `AIProviderConfig`                       | `ProviderConfig` — never the credential: re-enter it |
| `AIModel`                                | `ModelEntry`                                         |
| `JSONSchema`                             | `OutputSchema` (shared)                              |
| `Assistant`                              | `Assistant` (shared; its OpenAI tool JSON is not carried) |
| `AssistantGroup` + memberships           | `Pipeline` + `PipelineStep`s reading the conversation, in position order |
| `ContentDetail` + its `ContentItem`s     | a `Brief`: prompt, the items' text as Markdown, the metadata; applied when its post was imported |
| `Thread` + its `Message`s                | a `Conversation` + `Message`s, numbered in time order |

Ownership follows parodynews's rule: a row with no user was everyone's
(`shared`); one with a user is that person's (`private`), matched by username
from `auth.user` rows in the dump — and kept private, visible to staff only,
when no such person exists here. Provider slug `mock` is the platform's `fake`.
Every row gets a public id derived from its parodynews key, so a second import
updates the same rows and changes nothing that did not change in the dump.
"""

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from ai import providers
from ai.models import (
    Assistant,
    Brief,
    Conversation,
    Message,
    ModelEntry,
    OutputSchema,
    Pipeline,
    PipelineStep,
    ProviderConfig,
    Visibility,
)
from ai.services import set_default, stable_id

SLUGS = {"mock": "fake"}
DEFAULT_PROMPT = "you are a helpful assistant."
MESSAGE_STATUS = {"completed": Message.COMPLETED, "failed": Message.FAILED, "initial": Message.COMPLETED}


def _index(rows, model):
    return {row["pk"]: row["fields"] for row in rows if row.get("model") == model}


def _owners(rows):
    usernames = {pk: f.get("username") for pk, f in _index(rows, "auth.user").items()}
    found = {u.username: u for u in get_user_model().objects.filter(username__in=[n for n in usernames.values() if n])}

    def owned(user_pk) -> dict:
        if user_pk is None:
            return {"owner": None, "visibility": Visibility.SHARED}
        return {"owner": found.get(usernames.get(user_pk)), "visibility": Visibility.PRIVATE}

    return owned


def _upsert(table, kind, pk, **values):
    row, _ = table.objects.update_or_create(public_id=stable_id(f"parodynews.{kind}", pk), defaults=values)
    return row


def import_ai(rows, report, pages_by_post: dict) -> None:
    owned = _owners(rows)
    known = set(providers.available())

    for config in _index(rows, "parodynews.aiproviderconfig").values():
        slug = SLUGS.get(config["provider"], config["provider"])
        if slug not in known:
            report.skipped.append(f"provider {config['provider']}: no adapter")
            continue
        row, _ = ProviderConfig.objects.update_or_create(
            slug=slug,
            defaults={
                "display_name": config.get("display_name") or slug,
                "base_url": config.get("base_url") or "",
                "organization": config.get("organization_id") or "",
                "project": config.get("project_id") or "",
                "default_model": config.get("default_model") or "",
                "extra": config.get("extra") or {},
                "enabled": config.get("is_enabled", True),
            },
        )
        if config.get("is_default") and row.enabled:
            set_default(row)
        report.providers.append(slug)

    models = {}
    for pk, f in _index(rows, "parodynews.aimodel").items():
        slug = SLUGS.get(f["provider"], f["provider"])
        if slug not in known:
            report.skipped.append(f"model {f['provider']}:{f['model_id']}: no adapter")
            continue
        provider, _ = ProviderConfig.objects.get_or_create(slug=slug, defaults={"display_name": slug})
        models[pk], _ = ModelEntry.objects.update_or_create(
            provider=provider,
            model_id=f["model_id"],
            defaults={
                "display_name": f.get("display_name") or "",
                "description": f.get("description") or "",
                "active": f.get("is_active", True),
            },
        )

    schemas = {}
    for pk, f in _index(rows, "parodynews.jsonschema").items():
        try:
            schemas[pk] = _upsert(
                OutputSchema,
                "jsonschema",
                pk,
                name=f["name"][:120],
                description=f.get("description") or "",
                schema=f["schema"],
                visibility=Visibility.SHARED,
            )
        except ValidationError as e:
            report.skipped.append(f"schema {f['name']}: {'; '.join(e.messages)}")
    report.schemas = len(schemas)

    assistants = {}
    for pk, f in sorted(_index(rows, "parodynews.assistant").items(), key=lambda kv: str(kv[0])):
        model = models.get(f.get("model"))
        prompt = (f.get("prompt") or "").strip()
        extra = prompt if prompt and prompt.lower() != DEFAULT_PROMPT and prompt != f.get("instructions") else ""
        assistants[pk] = _upsert(
            Assistant,
            "assistant",
            pk,
            name=(f.get("name") or str(pk))[:120],
            description=f.get("description") or "",
            instructions="\n\n".join(p for p in (f.get("instructions"), extra) if p),
            model=model,
            provider=model.provider if model else None,
            params={k: f[k] for k in ("temperature", "top_p") if f.get(k) is not None},
            output_schema=schemas.get(f.get("json_schema")),
            visibility=Visibility.SHARED,
        )
    report.assistants = [a.name for a in assistants.values()]

    members = defaultdict(list)
    for pk, f in _index(rows, "parodynews.assistantgroupmembership").items():
        if f.get("assistantgroup") is not None and f.get("assistant") in assistants:
            members[f["assistantgroup"]].append((f["position"], pk, assistants[f["assistant"]]))
    pipelines = {}
    for pk, f in _index(rows, "parodynews.assistantgroup").items():
        pipeline = _upsert(Pipeline, "assistantgroup", pk, name=f["name"][:120], visibility=Visibility.SHARED)
        wanted = [(i, a.pk) for i, (_, _, a) in enumerate(sorted(members[pk], key=lambda m: m[:2]), start=1)]
        if list(pipeline.steps.order_by("position").values_list("position", "assistant_id")) != wanted:
            pipeline.steps.all().delete()
            PipelineStep.objects.bulk_create(
                PipelineStep(pipeline=pipeline, position=i, assistant_id=a, source=PipelineStep.CONVERSATION)
                for i, a in wanted
            )
        pipelines[pk] = pipeline
    report.pipelines = len(pipelines)

    items = _index(rows, "parodynews.contentitem")
    by_detail = defaultdict(list)
    for item in sorted(items.values(), key=lambda i: i.get("line_number", 0)):
        by_detail[item["detail"]].append(item)
    posted = {f.get("content_detail"): pk for pk, f in _index(rows, "parodynews.post").items()}
    for pk, f in _index(rows, "parodynews.contentdetail").items():
        written = [i for i in by_detail[pk] if i.get("content_type") != "message"]
        if by_detail[pk] and not written:
            continue  # a thread's container: its text arrives as that thread's messages
        markdown = "\n\n".join(i["content_text"].strip() for i in written if i.get("content_text", "").strip())
        page = pages_by_post.get(posted.get(pk))
        _upsert(
            Brief,
            "contentdetail",
            pk,
            title=(f.get("title") or "")[:255],
            prompt=written[0].get("prompt", "") if written else "",
            markdown=markdown,
            metadata={
                "title": f.get("title") or "",
                "description": f.get("description") or "",
                "author": f.get("author") or "",
                "slug": f.get("slug") or "",
                "date": f.get("published_at") or "",
                "keywords": list(f.get("keywords") or []),
                "tags": [],
            },
            assistant=assistants.get(written[0].get("assistant")) if written else None,
            page=page,
            status=Brief.APPLIED if page else Brief.READY if markdown else Brief.DRAFT,
            **owned(f.get("user")),
        )
        report.briefs += 1

    threads = {}
    for pk, f in _index(rows, "parodynews.thread").items():
        threads[pk] = _upsert(
            Conversation,
            "thread",
            pk,
            title=(f.get("name") or "Conversation")[:200],
            pipeline=pipelines.get(f.get("assistant_group")),
            **owned(f.get("user")),
        )
        if f.get("created_at"):
            Conversation.objects.filter(pk=threads[pk].pk).update(created_at=f["created_at"])
    report.conversations = len(threads)

    said = defaultdict(list)
    for pk, f in _index(rows, "parodynews.message").items():
        if f.get("thread") in threads:
            said[f["thread"]].append((f.get("created_at") or "", str(pk), pk, f))
    for thread, messages in said.items():
        for seq, (_, _, pk, f) in enumerate(sorted(messages), start=1):
            status = MESSAGE_STATUS.get(f.get("status"))
            row = _upsert(
                Message,
                "message",
                pk,
                conversation=threads[thread],
                seq=seq,
                role=f.get("role") or Message.USER,
                text=items.get(f.get("contentitem"), {}).get("content_text", ""),
                assistant=assistants.get(f.get("assistant")),
                status=status or Message.FAILED,
                provider=SLUGS.get(f.get("provider") or "", f.get("provider") or ""),
                model=f.get("model_id") or "",
                usage=f.get("usage") or {},
                error=f.get("error") or ("" if status else "interrupted before the import"),
            )
            if f.get("created_at"):
                Message.objects.filter(pk=row.pk).update(created_at=f["created_at"])
            report.messages += 1
