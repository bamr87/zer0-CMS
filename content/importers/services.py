"""Which pages a file became: the import's record read backwards.

A client that edits files — the VS Code extension — knows a file by its path
from the folder it has open, starting with that folder's name; the platform
knows a page by the path its import recorded (`ImportedSource.legacy_path`,
within the site) and the site's folder (`SiteRootPage.source_root`).
`pages_imported_from` finds the pages whose two halves meet in the client's
path, so the extension can open the page behind the open file (PLAN G10) — or
say plainly that there is none. The folders above the file are the evidence of
which site it belongs to: two sites can each have a `_posts/a.md`, and a path
with no folder above it names neither.
"""

from pathlib import PurePosixPath

from cms.models import SiteRootPage

from .models import ImportedSource


def _same_folder(above: str, source_root: str) -> bool:
    """Whether the folders the client sees above the file can be the site's:
    one must end with the other — the site's own folder (`drsai` for
    `sites/drsai`), a folder above the repository (`code/zer0-CMS/sites/a` for
    `sites/a`), or a site imported by an absolute path (`it-journey` for
    `/home/me/it-journey`). No folder at all is no evidence, and matches no site.
    """
    root = source_root.strip("/")
    return bool(above and root) and (above == root or above.endswith("/" + root) or root.endswith("/" + above))


def pages_imported_from(path: str) -> list[int]:
    """The ids of the pages imported from the file at `path`, a POSIX path
    from the folder the client has open, starting with that folder's name:
    the site's folder (`drsai/_posts/a.md`) or one above it
    (`zer0-CMS/sites/drsai/_posts/a.md`). An absolute path or one with `..`
    names no file the client could have opened inside a folder, and finds
    nothing."""
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        return []
    parts = pure.parts
    above = {"/".join(parts[i:]): "/".join(parts[:i]) for i in range(len(parts))}
    rows = list(ImportedSource.objects.filter(legacy_path__in=above).values_list("page_id", "site_key", "legacy_path"))
    roots = dict(
        SiteRootPage.objects.filter(site_key__in={key for _, key, _ in rows}).values_list("site_key", "source_root")
    )
    return [page for page, key, legacy in rows if _same_folder(above[legacy], roots.get(key, ""))]
