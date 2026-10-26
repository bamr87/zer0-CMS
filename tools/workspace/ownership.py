"""Which project owns a file, and which projects a set of changed files affects.

A file belongs to the project whose glob matches it most specifically (the
longest literal prefix wins), so `packages/zer0-image-generator/x` belongs to
the image generator even though nothing else claims `packages/`. A root
workflow belongs to every project whose `ci:` names it. Anything left over —
docs/, workspace.yml, tools/ — is workspace infrastructure and affects no
project by itself. A change to a project also affects every project that
depends on it.
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase

from .manifest import Manifest

WORKFLOWS = ".github/workflows/"


def match(glob: str, file: str) -> bool:
    """A `dir/**` glob owns everything under dir. Any other glob matches like
    Ruby's File.fnmatch with FNM_PATHNAME | FNM_DOTMATCH | FNM_EXTGLOB, which
    the manifest's globs were written for: `*` stays inside one path segment
    (so "*.json" does not cross a slash) and matches dotfiles, `**/` spans
    directories, and `{a,b}` is either. fnmatch matches each segment."""
    if glob.endswith("/**"):
        return file.startswith(glob[:-2])
    return any(_segments(g.split("/"), file.split("/")) for g in _braces(glob))


def literal_prefix(glob: str) -> str:
    return re.match(r"[^*?\[{]*", glob)[0]


def _braces(glob: str) -> list:
    m = re.search(r"\{([^{}]*)\}", glob)
    if not m:
        return [glob]
    return [g for alt in m[1].split(",") for g in _braces(glob[: m.start()] + alt + glob[m.end() :])]


def _segments(pattern: list, parts: list) -> bool:
    if not pattern:
        return not parts
    if pattern[0] == "**" and len(pattern) > 1:  # "**/": zero or more directories
        return any(_segments(pattern[1:], parts[i:]) for i in range(len(parts)))
    return bool(parts) and fnmatchcase(parts[0], pattern[0]) and _segments(pattern[1:], parts[1:])


class Ownership:
    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest

    def owner(self, file: str) -> str | None:
        """The project that owns `file`, or None for workspace infrastructure."""
        owners = self.owners(file)
        return owners[0] if owners else None

    def owners(self, file: str) -> list:
        """Every project `file` belongs to: one for a project file, every project a
        shared workflow gates (sites.yml gates five), none for infrastructure."""
        if file.startswith(WORKFLOWS) and "/" not in file[len(WORKFLOWS) :]:
            return [p.name for p in self.manifest.projects if p.workflow == file[len(WORKFLOWS) :]]
        best, longest = None, -1
        for project in self.manifest.projects:
            for glob in project.globs:
                if match(glob, file) and len(literal_prefix(glob)) > longest:
                    best, longest = project.name, len(literal_prefix(glob))
        return [] if best is None else [best]

    def affected(self, files: list) -> dict:
        """{"affected": [names in manifest order], "direct": [...], "unowned": [files]}"""
        direct, unowned = [], []
        for file in files:
            names = self.owners(file)
            if not names:
                unowned.append(file)
            direct += [n for n in names if n not in direct]
        everything = set(direct)
        for name in direct:
            everything.update(self.manifest.dependents_of(name))
        order = self.manifest.names
        return {
            "affected": [n for n in order if n in everything],
            "direct": [n for n in order if n in direct],
            "unowned": unowned,
        }
