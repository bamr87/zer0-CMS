"""Where the tests find a real site's tree, now that five of them live outside
this repository (ADR 0012).

lifehacker.dev is the content source: 1987, 2005, drsai, irony-works and
wargames moved there whole, as trees under its `agencies/` directory, and the
platform still has to import, round-trip and export them. So the tests that
read those trees resolve them here, in one place. The agencies directory is
`ZER0_AGENCIES_DIR` (a relative value is taken from this repository's root),
else a sibling checkout: `<this repository>/../lifehacker.dev/agencies`.
content.yml fetches it from bamr87/lifehacker.dev. A tree that is absent skips
its cases with a reason that names the variable, so a checkout without the
content source still runs everything else.
"""

import os
from pathlib import Path

import pytest
from django.conf import settings

ENV = "ZER0_AGENCIES_DIR"
PREFIX = "agencies/"
# The Jekyll sites that moved, by the name this repository held each under (`sites/<name>`), and its
# tree in the agencies directory. (1987 moved too, to `1987`; it has no Jekyll config, so no test reads it.)
MOVED = {"2005": "year-of-ai/2005", "drsai": "drsai", "irony-works": "irony-works", "wargames": "wargames"}


def agencies_dir() -> Path:
    repo = Path(settings.REPO_ROOT)
    value = os.environ.get(ENV, "").strip()
    return repo / Path(value).expanduser() if value else repo.parent / "lifehacker.dev" / "agencies"


def agency(tree: str, needs: str = "_config.yml") -> Path:
    """The tree of one agency (`drsai`, `year-of-ai/2005`), or a skip when it, or
    the file a test `needs` in it, is not there."""
    root = agencies_dir() / tree
    if not (root / needs).is_file():
        pytest.skip(
            f"{PREFIX}{tree} is not under {agencies_dir()} (no {needs}): "
            f"point {ENV} at lifehacker.dev's agencies/ directory (ADR 0012)"
        )
    return root


def real_site(site: str) -> Path:
    """A real site's Jekyll root: `agencies/<tree>` in the agencies directory (or
    a skip), anything else a path in this repository."""
    if site.startswith(PREFIX):
        return agency(site.removeprefix(PREFIX))
    return Path(settings.REPO_ROOT) / site


def site_named(name: str) -> Path:
    """`sites/<name>` as a recording made before ADR 0012 names it: its tree in the
    agencies directory (or a skip) when it moved, else in this repository."""
    return real_site(f"{PREFIX}{MOVED[name]}" if name in MOVED else f"sites/{name}")
