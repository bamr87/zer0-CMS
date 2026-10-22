#!/bin/bash

# Generated-documentation freshness (fleet docs framework UPS-DOC-03, UPS-DOC-05)
#
# docs/reference/*.md is generated from the files it describes by
# scripts/generate-reference.rb, and the index span in docs/README.md by
# tools/docs_index.py. Changing a source — a workflow, a Make target, an
# instruction file's applyTo, a document's summary line — without
# regenerating fails here, and the message names the command that fixes it.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

echo "Testing generated documentation..."

# The read-only mirror (bamr87/zer0-mistakes) carries no workflows but
# pages.yml, so the workflow inventory describes files it does not have.
if [[ -f "$REPO_ROOT/.github/workflows/ci.yml" ]]; then
    assert_true "(cd '$REPO_ROOT' && LC_ALL=C LANG=C ruby scripts/generate-reference.rb --check >/dev/null 2>&1)" \
        "docs/reference/ matches its sources (fix: ruby scripts/generate-reference.rb)"
else
    echo -e "${YELLOW}⚠${NC} skipped docs/reference/ check: .github/workflows/ is not part of this checkout"
fi

if command -v python3 >/dev/null 2>&1; then
    assert_true "(cd '$REPO_ROOT' && LC_ALL=C LANG=C python3 tools/docs_index.py --check >/dev/null 2>&1)" \
        "docs/README.md index matches the documents (fix: python3 tools/docs_index.py --write)"
    assert_true "(cd '$REPO_ROOT' && LC_ALL=C LANG=C python3 tools/docs_index.py --lint >/dev/null 2>&1)" \
        "every indexed document has one H1 and a summary line (see: python3 tools/docs_index.py --lint)"
else
    echo -e "${YELLOW}⚠${NC} skipped docs index checks: python3 not found"
fi

echo -e "\n${GREEN}generated-documentation tests complete${NC}"
