# Tech notes

This file has no front matter, so it is not a page. `buildIndex` records its mtime under `cache.skipped` and never reads it again while that mtime holds — which is what makes "the second run re-parses zero files" true rather than nearly true.

Do not add front matter to this file. Several assertions count on its absence.
