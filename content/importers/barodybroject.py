"""barodybroject's database → the content plane (PLAN §4.4, M6).

Input is barodybroject's own `manage.py dumpdata parodynews` (the plan's
first step: dump before anything moves), read as data — this project never
imports barodybroject's code or connects to its database.

| barodybroject                         | here                                                |
|---------------------------------------|-----------------------------------------------------|
| `Post` + `PostFrontMatter` + `ContentDetail` | an `ArticlePage` under the `barodybroject` site, `posts` collection |
| `PostVersion` (in `version_number` order) | one revision each, authored by `legacy:import`, dated as the original |
| the post's current content           | the latest revision; published if the post's status is `published` |
| `Assistant` (+ `AIModel`)             | an `AgentDefinition` `legacy-<name>`, policy `off`, never live — a record to port from, not an agent to run |

`Thread` / `Message` are left in the dump: whether chat history becomes
`AgentRun` rows is still open (PLAN §4.4). Re-running the import changes
nothing that did not change in the dump.
"""

import hashlib
import json
from dataclasses import dataclass, field

import yaml
from django.db import transaction
from django.utils.text import slugify
from wagtail.models import Revision

from agents.models import AgentDefinition
from agents.principals import ensure_legacy_import_user
from cms.models import ArticlePage, CollectionPage, SiteRootPage
from cms.services import publish, save_draft

from . import frontmatter
from .markdown import to_blocks
from .models import ImportedSource

SITE_KEY = "barodybroject"


@dataclass
class Report:
    pages_created: list = field(default_factory=list)
    pages_unchanged: list = field(default_factory=list)
    revisions: int = 0
    agents: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"barodybroject: {len(self.pages_created)} page(s) created, {len(self.pages_unchanged)} unchanged, "
            f"{self.revisions} historical revision(s), {len(self.agents)} legacy agent definition(s)"
        )


def _index(rows, model):
    return {row["pk"]: row["fields"] for row in rows if row.get("model") == model}


def _parse_front_matter(text: str) -> dict:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data, _ = frontmatter.split(text if text.startswith("---") else f"---\n{text}\n---\n")
        except yaml.YAMLError:
            return {}
    return data if isinstance(data, dict) else {}


def _site():
    from importers.jekyll import _unique_slug

    root = SiteRootPage.objects.filter(site_key=SITE_KEY).first()
    importer = ensure_legacy_import_user()
    if root is None:
        from wagtail.models import Page

        top = Page.get_first_root_node()
        root = SiteRootPage(
            title="barodybroject", slug=_unique_slug(top, SITE_KEY), site_key=SITE_KEY, source_root="apps/barodybroject"
        )
        top.add_child(instance=root)
        publish(root, user=importer)
    posts = CollectionPage.objects.child_of(root).filter(collection="posts").first()
    if posts is None:
        posts = CollectionPage(title="Posts", slug="posts", collection="posts", output_dir="_posts")
        root.add_child(instance=posts)
        publish(posts, user=importer)
    return posts


def _apply(page, *, title, description, author, date, slug, body, extra):
    page.title = (title or slug or "Untitled")[:255]
    page.search_description = description or ""
    page.author = (author or "")[:200]
    page.date = frontmatter.parse_date(date) if isinstance(date, str) else date
    page.body = to_blocks(body or "")
    page.front_matter = {
        "title": page.title,
        "description": page.search_description,
        "author": page.author,
        **({"date": date} if isinstance(date, str) else {}),
        **extra,
    }


def import_dump(path_or_rows) -> Report:
    rows = path_or_rows if isinstance(path_or_rows, list) else json.loads(open(path_or_rows, encoding="utf-8").read())
    posts = _index(rows, "parodynews.post")
    front = _index(rows, "parodynews.postfrontmatter")
    details = _index(rows, "parodynews.contentdetail")
    versions = sorted(
        (r for r in rows if r.get("model") == "parodynews.postversion"),
        key=lambda r: (r["fields"]["post"], r["fields"]["version_number"]),
    )
    models = _index(rows, "parodynews.aimodel")
    assistants = _index(rows, "parodynews.assistant")
    report = Report()
    importer = ensure_legacy_import_user()
    with transaction.atomic():
        parent = _site()
        for pk, post in sorted(posts.items()):
            legacy = f"parodynews.post:{pk}"
            digest = hashlib.sha256(
                json.dumps(
                    [post, [v for v in versions if v["fields"]["post"] == pk]], sort_keys=True, default=str
                ).encode()
            ).hexdigest()
            existing = ImportedSource.objects.filter(site_key=SITE_KEY, legacy_path=legacy).first()
            if existing is not None and existing.source_digest == digest:
                report.pages_unchanged.append(legacy)
                continue
            fm = front.get(post.get("postfrontmatter")) or next((f for f in front.values() if f.get("post") == pk), {})
            detail = details.get(post.get("content_detail"), {})
            title = fm.get("title") or detail.get("title")
            slug = slugify(fm.get("slug") or detail.get("slug") or title or f"post-{pk}")[:255]
            meta = {
                "title": title,
                "description": fm.get("description") or detail.get("description"),
                "author": fm.get("author") or detail.get("author"),
                "date": fm.get("published_at") or detail.get("published_at") or post.get("created_at"),
                "slug": slug,
            }
            extra = {"keywords": detail["keywords"]} if detail.get("keywords") else {}
            page = existing.page.specific if existing else ArticlePage(slug=slug)
            history = [v for v in versions if v["fields"]["post"] == pk]
            first = history[0]["fields"] if history else None
            _apply(
                page,
                body=(first["content"] if first else post.get("post_content")),
                extra=extra,
                **{
                    **meta,
                    **{
                        k: v
                        for k, v in _parse_front_matter(first["frontmatter"] if first else "").items()
                        if k in meta and v
                    },
                },
            )
            if existing is None:
                page.legacy_path = f"_posts/{post.get('filename') or slug + '.md'}"
                page.live = False
                parent.add_child(instance=page)
            for version in history:
                v = version["fields"]
                vmeta = {
                    **meta,
                    **{k: val for k, val in _parse_front_matter(v["frontmatter"]).items() if k in meta and val},
                }
                _apply(page, body=v["content"], extra=extra, **vmeta)
                revision = save_draft(page, user=importer)
                Revision.objects.filter(pk=revision.pk).update(created_at=v["created_at"])
                report.revisions += 1
            _apply(page, body=post.get("post_content"), extra=extra, **meta)
            if post.get("status") == "published":
                publish(page, user=importer)
            else:
                save_draft(page, user=importer)
            page = page.specific
            ImportedSource.objects.update_or_create(
                site_key=SITE_KEY,
                legacy_path=legacy,
                defaults={
                    "page": page,
                    "source_text": post.get("post_content") or "",
                    "source_digest": digest,
                    "import_hash": page.get_latest_revision_as_object().compute_content_hash(),
                },
            )
            report.pages_created.append(legacy)
        for pk, assistant in sorted(assistants.items(), key=lambda kv: str(kv[0])):
            slug = f"legacy-{slugify(assistant.get('name') or pk)}"[:64]
            model = models.get(assistant.get("model"), {})
            values = {
                "name": (assistant.get("name") or slug)[:120],
                "description": assistant.get("description") or "",
                "role": "author",
                "policy": "off",
                "tools": [],
                "system_prompt": "\n\n".join(p for p in (assistant.get("instructions"), assistant.get("prompt")) if p),
                "model": f"{model.get('provider', '')}/{model.get('model_id', '')}".strip("/"),
                "profile": {
                    "legacy_ref": f"parodynews.assistant:{pk}",
                    "tools": assistant.get("tools") or [],
                    "temperature": assistant.get("temperature"),
                },
            }
            definition = AgentDefinition.objects.filter(slug=slug).first()
            if definition is None:
                definition = AgentDefinition(slug=slug, live=False, **values)
                definition.save()
                definition.save_revision(log_action=False)
            report.agents.append(slug)
    return report
