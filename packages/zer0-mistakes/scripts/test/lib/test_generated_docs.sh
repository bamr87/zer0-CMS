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

assert_true "(cd '$REPO_ROOT' && LC_ALL=C LANG=C ruby scripts/generate-reference.rb --check >/dev/null 2>&1)" \
    "docs/reference/ matches its sources (fix: ruby scripts/generate-reference.rb)"

echo -e "\n${GREEN}generated-documentation tests complete${NC}"
