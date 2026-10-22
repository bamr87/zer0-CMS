"""parodynews's AI tables → the AI content layer (ADR 0006 decision 7, PLAN §4.4).

Called by `importers.parodynews.import_dump` on the same `dumpdata` rows:

| parodynews                               | here                                                 |
|------------------------------------------|------------------------------------------------------|
| `AIProviderConfig`                       | `ProviderConfig` — never the credential: re-enter it; `extra` only as the adapter's options |
| `AIModel`                                | `ModelEntry`                                         |
| `JSONSchema`                             | `OutputSchema` (shared)                              |
| `Assistant`                              | `Assistant` (shared; its OpenAI tool JSON is not carried) |
| `AssistantGroup` + memberships           | `Pipeline` + `PipelineStep`s reading the conversation, in position order |
| `ContentDetail` + its `ContentItem`s     | a `Brief`: prompt, the items' text as Markdown, the metadata; applied when its post was imported |
| `Thread` + its `Message`s                | a `Conversation` + `Message`s, in time order         |

Ownership follows parodynews's rule: a row with no user was everyone's
(`shared`); one with a user is that person's (`private`), matched by username
from `auth.user` rows in the dump — and kept private, visible to staff only,
when no such person exists here. Provider slug `mock` is the platform's `fake`.

barodybroject keeps running until its gate is green, so the import is re-run on
fresh dumps. Every row gets a public id derived from its parodynews key and an
`ImportedRecord` — a digest of what the import wrote — so a second import
changes nothing that did not change in the dump, and nothing a person changed
here: a row edited or deleted on the platform since the last import is reported
as a conflict and left alone (`force` overwrites it, though an applied brief
keeps its draft even then). A message that is new in the dump goes after the
conversation's last one, whatever people added here meanwhile.
"""

import hashlib
import json
from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Max, Model

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

from .models import ImportedRecord

SOURCE = "parodynews"
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


def _digest(state) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()


class Writer:
    """Writes what the dump says, unless a person changed it here since the import last wrote it."""

    def __init__(self, report, force: bool):
        self.report, self.force = report, force

    def guard(self, key: str, current, wanted, write) -> bool:
        """Call `write()` when what is here now (`current()`) is what the last
        import left (or was never imported, or `force`), and record what is here
        after; else report a conflict and leave it."""
        record = ImportedRecord.objects.filter(source=SOURCE, key=key).first()
        now = current()
        if record is not None and _digest(now) != record.digest and not self.force:
            self.report.conflicts.append(f"{key}: changed here since the last import (pass --force to overwrite)")
            return False
        if now != wanted:
            write()
        ImportedRecord.objects.update_or_create(source=SOURCE, key=key, defaults={"digest": _digest(current())})
        return True

    def row(self, table, key: str, lookup: dict, **values):
        """The row `lookup` finds, created or brought to `values` under `guard`; None when a person deleted it."""

        def current():
            found = table.objects.filter(**lookup).first()
            return None if found is None else {name: found.serializable_value(name) for name in values}

        wanted = {name: value.pk if isinstance(value, Model) else value for name, value in values.items()}
        self.guard(key, current, wanted, lambda: table.objects.update_or_create(**lookup, defaults=values))
        return table.objects.filter(**lookup).first()

    def owned(self, table, kind: str, pk, **values):
        return self.row(table, f"{kind}:{pk}", {"public_id": stable_id(f"parodynews.{kind}", pk)}, **values)


def _set_steps(pipeline, wanted) -> None:
    pipeline.steps.all().delete()
    PipelineStep.objects.bulk_create(
        PipelineStep(pipeline=pipeline, position=position, assistant_id=assistant, source=source)
        for position, assistant, source in wanted
    )


def import_ai(rows, report, pages_by_post: dict, *, force=False) -> None:
    owned = _owners(rows)
    known = set(providers.available())
    write = Writer(report, force)

    for config in _index(rows, "parodynews.aiproviderconfig").values():
        slug = SLUGS.get(config["provider"], config["provider"])
        if slug not in known:
            report.skipped.append(f"provider {config['provider']}: no adapter")
            continue
        options, extra = providers.provider_class(slug).options, config.get("extra") or {}
        if set(extra) - set(options):
            report.skipped.append(
                f"provider {slug}: options not carried: {', '.join(sorted(set(extra) - set(options)))}"
            )
        row = write.row(
            ProviderConfig,
            f"provider:{slug}",
            {"slug": slug},
            display_name=config.get("display_name") or slug,
            base_url=config.get("base_url") or "",
            organization=config.get("organization_id") or "",
            project=config.get("project_id") or "",
            default_model=config.get("default_model") or "",
            extra={k: v for k, v in extra.items() if k in options},
            enabled=config.get("is_enabled", True),
        )
        if row is not None and config.get("is_default") and row.enabled:
            write.guard(
                "default-provider",
                lambda: ProviderConfig.objects.filter(is_default=True).values_list("slug", flat=True).first(),
                slug,
                lambda row=row: set_default(row),
            )
        report.providers.append(slug)

    models = {}
    for pk, f in _index(rows, "parodynews.aimodel").items():
        slug = SLUGS.get(f["provider"], f["provider"])
        if slug not in known:
            report.skipped.append(f"model {f['provider']}:{f['model_id']}: no adapter")
            continue
        provider, _ = ProviderConfig.objects.get_or_create(slug=slug, defaults={"display_name": slug})
        models[pk] = write.row(
            ModelEntry,
            f"aimodel:{pk}",
            {"provider": provider, "model_id": f["model_id"]},
            display_name=f.get("display_name") or "",
            description=f.get("description") or "",
            active=f.get("is_active", True),
        )

    schemas = {}
    for pk, f in _index(rows, "parodynews.jsonschema").items():
        try:
            schemas[pk] = write.owned(
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
        assistants[pk] = write.owned(
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
    report.assistants = [a.name for a in assistants.values() if a is not None]

    members = defaultdict(list)
    for pk, f in _index(rows, "parodynews.assistantgroupmembership").items():
        if f.get("assistantgroup") is not None and assistants.get(f.get("assistant")) is not None:
            members[f["assistantgroup"]].append((f["position"], pk, assistants[f["assistant"]]))
    pipelines = {}
    for pk, f in _index(rows, "parodynews.assistantgroup").items():
        pipeline = write.owned(Pipeline, "assistantgroup", pk, name=f["name"][:120], visibility=Visibility.SHARED)
        if pipeline is None:
            continue
        ordered = sorted(members[pk], key=lambda m: m[:2])
        wanted = [(i, a.pk, PipelineStep.CONVERSATION) for i, (_, _, a) in enumerate(ordered, start=1)]
        write.guard(
            f"assistantgroup:{pk}/steps",
            lambda p=pipeline: list(p.steps.order_by("position").values_list("position", "assistant_id", "source")),
            wanted,
            lambda p=pipeline, w=wanted: _set_steps(p, w),
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
        values = {
            "title": (f.get("title") or "")[:255],
            "prompt": written[0].get("prompt", "") if written else "",
            "markdown": markdown,
            "metadata": {
                "title": f.get("title") or "",
                "description": f.get("description") or "",
                "author": f.get("author") or "",
                "slug": f.get("slug") or "",
                "date": f.get("published_at") or "",
                "keywords": list(f.get("keywords") or []),
                "tags": [],
            },
            "assistant": assistants.get(written[0].get("assistant")) if written else None,
            "page": page,
            "status": Brief.APPLIED if page else Brief.READY if markdown else Brief.DRAFT,
            **owned(f.get("user")),
        }
        applied = Brief.objects.filter(public_id=stable_id("parodynews.contentdetail", pk), status=Brief.APPLIED)
        if applied.exists():
            values.update(status=Brief.APPLIED, page=applied.get().page)  # its draft stays, whatever the dump says
        write.owned(Brief, "contentdetail", pk, **values)
        report.briefs += 1

    threads = {}
    for pk, f in _index(rows, "parodynews.thread").items():
        conversation = write.owned(
            Conversation,
            "thread",
            pk,
            title=(f.get("name") or "Conversation")[:200],
            pipeline=pipelines.get(f.get("assistant_group")),
            **owned(f.get("user")),
        )
        if conversation is None:
            continue
        threads[pk] = conversation
        if f.get("created_at"):
            Conversation.objects.filter(pk=conversation.pk).update(created_at=f["created_at"])
    report.conversations = len(threads)

    said = defaultdict(list)
    for pk, f in _index(rows, "parodynews.message").items():
        if f.get("thread") in threads:
            said[f["thread"]].append((f.get("created_at") or "", str(pk), pk, f))
    for thread, messages in said.items():
        conversation = threads[thread]
        for _, _, pk, f in sorted(messages):
            existing = Message.objects.filter(public_id=stable_id("parodynews.message", pk)).first()
            last = conversation.messages.aggregate(m=Max("seq"))["m"] or 0
            status = MESSAGE_STATUS.get(f.get("status"))
            row = write.owned(
                Message,
                "message",
                pk,
                conversation=conversation,
                seq=existing.seq if existing else last + 1,
                role=f.get("role") or Message.USER,
                text=items.get(f.get("contentitem"), {}).get("content_text", ""),
                assistant=assistants.get(f.get("assistant")),
                status=status or Message.FAILED,
                provider=SLUGS.get(f.get("provider") or "", f.get("provider") or ""),
                model=f.get("model_id") or "",
                usage=f.get("usage") or {},
                error=f.get("error") or ("" if status else "interrupted before the import"),
            )
            if row is not None and f.get("created_at"):
                Message.objects.filter(pk=row.pk).update(created_at=f["created_at"])
            report.messages += 1
