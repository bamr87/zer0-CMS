"""The outbox harness library (bamr87/outbox), loaded under the name `outbox_harness`.

The library's import package is `outbox`, which is also the name of this platform's transactional-outbox app
(`content/outbox/`). The platform's directory is first on every process's path — manage.py, gunicorn, Celery and
pytest all put it there — so `import outbox.belt` can never reach the library, and must not: the platform's app has
to win that name. This module asks the installed distribution named `outbox` where its package lives
(`importlib.metadata`) and loads it under another name; the library's modules import each other relatively, so they
load unchanged. A regular install (a wheel, a git URL, a directory) records its files; an editable install does not,
and is refused with a reason. ADR 0007 records the collision and the owner's choice it leaves open.

Nothing loads the library until the desk is used, so a platform whose installed harness lacks a module (an `outbox`
older than the belt) still starts: the desk answers 503 `outbox.unavailable`, and a worker records the failure.
"""

import importlib
import importlib.util
import sys
from importlib import metadata
from types import ModuleType

from ops.errors import Unavailable

NAME = "outbox_harness"
DISTRIBUTION = "outbox"


class HarnessMissing(ImportError):
    pass


def _package() -> ModuleType:
    if NAME in sys.modules:
        return sys.modules[NAME]
    try:
        dist = metadata.distribution(DISTRIBUTION)
    except metadata.PackageNotFoundError as e:
        raise HarnessMissing("the outbox harness is not installed: pip install -r requirements.txt") from e
    init = next((f for f in dist.files or () if f.as_posix() == "outbox/__init__.py"), None)
    if init is None:
        raise HarnessMissing("the outbox distribution records no outbox/__init__.py (an editable install?)")
    path = dist.locate_file(init)
    spec = importlib.util.spec_from_file_location(NAME, path, submodule_search_locations=[str(path.parent)])
    if spec is None or spec.loader is None:
        raise HarnessMissing(f"cannot load the outbox harness from {path}")
    package = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = package
    try:
        spec.loader.exec_module(package)
    except BaseException:
        del sys.modules[NAME]
        raise
    return package


def module(name: str) -> ModuleType:
    """One of the library's modules: `belt`, `claimdesk`, `arena`, `score`, `mailbox`."""
    try:
        _package()
        return importlib.import_module(f"{NAME}.{name}")
    except ImportError as e:
        raise Unavailable(f"the outbox harness cannot load {name}: {e}", code="outbox.unavailable") from e


def version() -> str:
    return metadata.version(DISTRIBUTION)
