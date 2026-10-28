"""Managing sites (PLAN G4): registering and discovering them, changing their
registry fields and settings, and the work their jobs do.

**Register.** A site is registered from its checkout — a directory holding a
`_config.yml` inside this repository or under `SITES_DIR`, resolved through
symlinks — which becomes its Wagtail `Site` and `SiteRootPage` (the importer's
`ensure_site_root`) and its `ManagedSite`; its first sync is started at once.
`discover` lists what could be registered: every site workspace.yml declares
(with its `render:` setting, PLAN P2) and every Jekyll root one or two levels
under `SITES_DIR`.

**Sync** (a job) is `import_site`: the site's files, read by the catalog, become
its pages; a file changed by hand updates its page unless the page changed here
since (a conflict, reported). The digest of every file the platform read is
recorded on the `ManagedSite`.

**Write-back** (`export`, a job) writes what `exporters.jekyll.site_files`
renders — the live pages, or with `include_drafts` their latest revisions —
into the checkout, under the stale-write guard ported from the Rails
`PageEditor`: a file is written only while its bytes on disk still have the
digest the platform last read or wrote (the indexed digest), and — when the
job names one (`base`, the digests a person saw before asking) — while that
digest is still the indexed one; the bytes are compared again right before the
atomic rename (sites/writer.py). A file whose rendering equals what is on disk
is not written at all. A file changed by hand since is a conflict, kept as it
is: sync it first. The file of a page deleted here is removed while it is
unchanged since. What it writes is recorded both ways — the digest on the site,
the text on the page's `ImportedSource` — so the next sync sees the file as the
platform's own and the next write-back writes it verbatim.

Every write-back covers the pages that are not live, not only one with
`include_drafts`: a page unpublished here is taken down on the site by the
next write-back of any kind. Its file gets `published: false`
(`exporters.jekyll.mark`) under the same guard; a write-back of the live pages writes
only that marker onto the file as the platform last read or wrote it — never a
draft's content, never a new file — and a page that goes live again loses it.

**Doctor** (a job) runs sites/doctor.py over the checkout and keeps its
findings on the site and as the job's artifacts.
"""

import os
from collections import Counter
from pathlib import Path

import yaml
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from wagtail.models import Site

from exporters.jekyll import site_files
from importers.jekyll import ensure_site_root, import_site, read_config
from importers.models import ImportedSource
from jobs import services as jobs

from . import catalog, doctor, writer
from .models import ManagedSite

KINDS = ("sync", "export", "doctor")


class SiteError(ValueError):
    """A request about a site the rules refuse; the message says why."""


# ── where checkouts may be ──────────────────────────────────────────────────


def _bases() -> list[Path]:
    bases = [Path(os.path.realpath(settings.REPO_ROOT))]
    if settings.SITES_DIR:
        bases.append(Path(os.path.realpath(settings.SITES_DIR)))
    return bases


def label_for(root: Path) -> str:
    """How a checkout is recorded: relative to the repository when inside it."""
    repo = Path(os.path.realpath(settings.REPO_ROOT))
    try:
        return root.relative_to(repo).as_posix()
    except ValueError:
        return root.as_posix()


def resolve_checkout(path: str) -> Path:
    text = str(path or "").strip()
    if not text:
        raise SiteError("name the site's checkout: the directory that holds its _config.yml")
    repo = Path(settings.REPO_ROOT)
    root = Path(os.path.realpath(text if os.path.isabs(text) else repo / text))
    if not any(root == base or str(root).startswith(f"{base}/") for base in _bases()):
        raise SiteError(f"{text} is outside this repository and SITES_DIR")
    if not (root / "_config.yml").is_file():
        raise SiteError(f"{text} has no _config.yml — not a Jekyll site")
    return root


# ── what could be registered ────────────────────────────────────────────────


def workspace_sites() -> list[dict]:
    """The sites workspace.yml declares (`site:`), with their `render:` setting."""
    path = Path(settings.REPO_ROOT) / "workspace.yml"
    try:
        projects = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("projects") or {}
    except (OSError, yaml.YAMLError):
        return []
    found = []
    for name, project in projects.items():
        if not isinstance(project, dict) or project.get("site") is None:
            continue
        base, site = str(project.get("path", "")).rstrip("/"), str(project["site"]).strip("/")
        render = project.get("render") if isinstance(project.get("render"), dict) else {}
        route = str(project.get("route") or "")
        found.append(
            {
                "key": slugify(name),
                "checkout": base if site in ("", ".") else f"{base}/{site}",
                "render": "jekyll-theme" if render.get("as") == "jekyll-theme" else "react",
                "theme_tag": str(render.get("theme") or ""),
                "server": str(render.get("server") or ""),
                "deploy_target": route if route.startswith("/") else "",
            }
        )
    return found


def discover() -> list[dict]:
    """What could be registered: workspace.yml's sites and the Jekyll roots one or
    two levels under `SITES_DIR`, less the ones already registered."""
    registered = set(ManagedSite.objects.values_list("checkout", flat=True))
    found = {entry["checkout"]: entry for entry in workspace_sites()}
    if settings.SITES_DIR and Path(settings.SITES_DIR).is_dir():
        mount = Path(settings.SITES_DIR)
        for config in sorted([*mount.glob("*/_config.yml"), *mount.glob("*/*/_config.yml")]):
            root = Path(os.path.realpath(config.parent))
            label = label_for(root)
            found.setdefault(
                label,
                {
                    "key": slugify(root.name),
                    "checkout": label,
                    "render": "react",
                    "theme_tag": "",
                    "server": "",
                    "deploy_target": "",
                },
            )
    return [entry for label, entry in sorted(found.items()) if label not in registered]


# ── the registry ────────────────────────────────────────────────────────────


def register(checkout: str, *, user=None, key: str = "") -> tuple[ManagedSite, object]:
    """Register the site at `checkout` and start its first sync: (site, job)."""
    root = resolve_checkout(checkout)
    label = label_for(root)
    if ManagedSite.objects.filter(checkout=label).exists():
        raise SiteError(f"{label} is already registered")
    declared = next((e for e in workspace_sites() if e["checkout"] == label), {})
    key = slugify(key or declared.get("key") or root.name)
    if not key:
        raise SiteError("the site needs a key: letters, digits and hyphens")
    if ManagedSite.objects.filter(key=key).exists():
        raise SiteError(f"a site with the key {key} is already registered")
    try:
        config = read_config(root)
    except ValueError as e:  # a _config.yml Jekyll could not read either
        raise SiteError(str(e)) from e
    with transaction.atomic():
        site_root = ensure_site_root(key, root, config, Path(settings.REPO_ROOT))
        site = Site.objects.filter(root_page=site_root).first()
        if site is None:
            raise SiteError(f"{key}.localhost already serves another site")
        managed = ManagedSite.objects.create(
            site=site,
            key=key,
            checkout=label,
            render=declared.get("render") or ManagedSite.Render.REACT,
            theme_tag=declared.get("theme_tag", ""),
            server=declared.get("server", ""),
            deploy_target=declared.get("deploy_target", ""),
        )
        job = jobs.start("sync", user=user, site=site)
    return managed, job


EDITABLE = ("content_source", "render", "theme_tag", "server", "domains", "deploy_target")


def update(managed: ManagedSite, changes: dict) -> ManagedSite:
    """Change a site's registry fields (the serializer validated each one)."""
    for name in EDITABLE:
        if name in changes:
            setattr(managed, name, changes[name])
    if managed.render == ManagedSite.Render.JEKYLL_THEME and not (managed.theme_tag and managed.server):
        raise SiteError("the Jekyll-theme option needs the theme's tag and a Jekyll server")
    managed.save()
    return managed


def start(kind: str, managed: ManagedSite, *, user=None, params: dict | None = None, enqueue: bool = True):
    if kind not in KINDS:
        raise SiteError(f"no {kind} job for a site")
    return jobs.start(kind, user=user, site=managed.site, params=params or {}, enqueue=enqueue)


# ── sync ────────────────────────────────────────────────────────────────────


@jobs.handler("sync", exclusive=True)
def run_sync(job, ctx):
    managed = job.site.managed
    ctx.log(f"Reading {managed.checkout} the way Jekyll 4.4 reads it …")
    try:
        report = import_site(managed.root, managed.key, force=bool(job.params.get("force")))
    except (OSError, ValueError, catalog.UnsafePath) as e:
        ctx.log(str(e), "error")
        raise jobs.Failed(str(e)) from e
    for rel in report.created:
        ctx.log(f"new page from {rel}")
    for rel in report.updated:
        ctx.log(f"updated from {rel}")
    for line in report.conflicts:
        ctx.log(line, "warning")
    for line in report.errors:
        ctx.log(line, "error")
    read = report.created + report.updated + report.unchanged
    digests = dict(managed.digests)
    digests.update(
        ImportedSource.objects.filter(site_key=managed.key, legacy_path__in=read).values_list(
            "legacy_path", "source_digest"
        )
    )
    gone = sorted(rel for rel in digests if not (managed.root / rel).exists())
    for rel in gone:
        ctx.log(f"{rel} is gone from the checkout; its page stays, and a write-back will not bring it back", "warning")
    managed.digests, managed.last_synced_at = digests, timezone.now()
    managed.save(update_fields=["digests", "last_synced_at"])
    ctx.log(report.summary())
    return {
        "created": len(report.created),
        "updated": len(report.updated),
        "unchanged": len(report.unchanged),
        "conflicts": len(report.conflicts),
        "errors": len(report.errors),
        "gone": len(gone),
    }


# ── write-back ──────────────────────────────────────────────────────────────


@jobs.handler("export", exclusive=True)
def run_export(job, ctx):
    managed = job.site.managed
    root = managed.root
    include_drafts = bool(job.params.get("include_drafts"))
    base = job.params.get("base") if isinstance(job.params.get("base"), dict) else {}
    what = "the latest revisions" if include_drafts else "the live pages, taking down those that are not live,"
    ctx.log(f"Writing {what} of {managed.key} into {managed.checkout} …")
    digests, counts, planned = dict(managed.digests), Counter(), set()
    for file in site_files(managed.key, include_drafts=include_drafts):
        ctx.check()
        owner = (
            ImportedSource.objects.filter(site_key=managed.key, legacy_path=file.rel)
            .exclude(page_id=file.page.pk)
            .first()
        )
        if owner is not None:  # a page made here whose path is another page's file — a draft's, say
            outcome = "conflict"
            note = f"the file of another page (#{owner.page_id}); this page was not written — change its slug"
        elif file.rel in planned:
            outcome, note = "conflict", "two pages want this file; the second was not written"
        else:
            planned.add(file.rel)
            outcome, note = _write(root, file, digests, base, managed.key)
        counts[outcome] += 1
        if outcome != "unchanged":
            ctx.log(
                f"{file.rel}: {note}",
                "warning" if outcome == "conflict" else "error" if outcome == "refused" else "info",
            )
    for rel in sorted(set(digests) - planned):
        ctx.check()
        if ImportedSource.objects.filter(site_key=managed.key, legacy_path=rel).exists():
            continue  # its page is still here, at another path now (a page moved: its old file stays)
        outcome, note = _remove(root, rel, digests)
        counts[outcome] += 1
        ctx.log(f"{rel}: {note}", "warning" if outcome == "conflict" else "info")
    managed.digests, managed.last_exported_at = digests, timezone.now()
    managed.save(update_fields=["digests", "last_exported_at"])
    summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "nothing to write"
    ctx.log(f"Done: {summary}.")
    return dict(counts)


def _write(root, file, digests, base, key) -> tuple[str, str]:
    indexed = digests.get(file.rel)
    if file.take_down and indexed != file.source.source_digest:
        # Not the file the platform last read or wrote for this page (it never had
        # one here, or the page moved since): nothing of its own to take down.
        return "unchanged", "unchanged"
    data = file.text.encode("utf-8")
    try:
        disk = writer.read_bytes(root, file.rel)
    except writer.Refused as e:
        return "refused", str(e)
    if disk == data:
        digests[file.rel] = writer.sha256(data)
        if not file.verbatim:
            _record(file, key)
        return "unchanged", "unchanged"
    if (writer.sha256(disk) if disk is not None else None) != indexed:
        state = "deleted" if disk is None else "changed"
        return "conflict", f"{state} on disk since the platform last read or wrote it; sync the site first"
    if file.rel in base and base[file.rel] != indexed:
        return "conflict", "re-indexed since this write-back was asked for; ask again"
    try:
        writer.write(root, file.rel, data, expected=disk)
    except writer.Stale as e:
        return "conflict", str(e)
    except writer.Refused as e:
        return "refused", str(e)
    digests[file.rel] = writer.sha256(data)
    _record(file, key)
    if file.take_down:
        return "written", "taken down: its page is not live (published: false)"
    return "written", "written" if disk is not None else "created"


def _record(file, key) -> None:
    """The file as written is what the page was last exported as. A take-down
    moved only the marker, so the content it holds — and the hash that says the
    page is still that content — stays."""
    fields = {"source_text": file.text, "source_digest": writer.sha256(file.text)}
    if not file.take_down:
        fields["import_hash"] = file.rendered.compute_content_hash()
    if file.source is not None:
        ImportedSource.objects.filter(pk=file.source.pk).update(**fields)
    else:
        ImportedSource.objects.update_or_create(
            page=file.page, defaults={"site_key": key, "legacy_path": file.rel, **fields}
        )


def _remove(root, rel, digests) -> tuple[str, str]:
    try:
        disk = writer.read_bytes(root, rel)
        if disk is None:
            digests.pop(rel)
            return "removed", "its page was deleted here, and the file was already gone"
        if writer.sha256(disk) != digests[rel]:
            return "conflict", "its page was deleted here, but the file changed by hand since; it stays"
        writer.remove(root, rel, expected=disk)
    except (writer.Stale, writer.Refused) as e:
        return "conflict", str(e)
    digests.pop(rel)
    return "removed", "removed: its page was deleted here"


# ── doctor ──────────────────────────────────────────────────────────────────


@jobs.handler("doctor")
def run_doctor(job, ctx):
    managed = job.site.managed
    ctx.log(f"Checking {managed.checkout} …")
    report = doctor.run(managed.root)
    for line in doctor.to_text(report).splitlines()[1:]:
        ctx.log(line, "error" if "ERROR" in line or (line.startswith("result") and report.errors) else "info")
    ctx.artifact("findings.jsonl", doctor.to_jsonl(report) + "\n", "application/x-ndjson")
    managed.findings, managed.last_doctor_at = report.findings, timezone.now()
    managed.save(update_fields=["findings", "last_doctor_at"])
    return {"errors": report.errors, "warnings": report.warnings}
