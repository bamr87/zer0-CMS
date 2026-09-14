# A page with no front matter at all

`buildIndex` does not call this a page, so `auditSite` never sees it. `auditPage` does, when a caller opens the file directly and hands over an empty projection with no block.
