"""Which pages a file became: the import's record read backwards.

A client that edits files — the VS Code extension — knows a file by its path
in the folder it has open; the platform knows a page by the path its import
recorded (`ImportedSource.legacy_path`, within the site) and the site's folder
(`SiteRootPage.source_root`). `pages_imported_from` finds the pages whose two
halves meet in the client's path, so the extension can open the page behind
the open file (PLAN G10) — or say plainly that there is none.
"""

from pathlib import PurePosixPath

from cms.models import SiteRootPage

from .models import ImportedSource


def _same_folder(above: str, source_root: str) -> bool:
    """Whether the folder the client sees above the file can be the site's.

    Empty means the client opened the site itself; otherwise one must end with
    the other: a client folder above the repository (`code/zer0-CMS/sites/a`
    for `sites/a`), or a site imported by an absolute path that the client
    opened from a folder above it (`it-journey` for `/home/me/it-journey`).
    """
    if not above:
        return True
    root = source_root.strip("/")
    return bool(root) and (above == root or above.endswith("/" + root) or root.endswith("/" + above))


def pages_imported_from(path: str) -> list[int]:
    """The ids of the pages imported from the file at `path`, a POSIX path
    relative to the site's folder (`_posts/a.md`) or to a folder above it
    (`sites/drsai/_posts/a.md`). An absolute path or one with `..` names no
    file the client could have opened inside a folder, and finds nothing."""
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
