"""bookshelf -- manage a shelf of book ideas and their contents.

The library is plain markdown and YAML on disk (``library/<slug>/``). This
package is a thin read/write layer over it: discovery, schema validation,
continuity checks, manuscript compilation and a static HTML dashboard.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
