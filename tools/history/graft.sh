#!/usr/bin/env bash
# tools/history/graft.sh — restore import history that a squash merge dropped (zer0-CMS PLAN C0).
#
#   tools/history/graft.sh <worktree> <base-ref> <squash-commit> <tip>:<path> [<tip>:<path> ...]
#
# On a fresh branch at <base-ref> (the target's current main) it:
#   1. lifts every imported <path> out in one commit (root .gitmodules kept as is);
#   2. merges each rewritten history <tip> back with --allow-unrelated-histories;
#   3. replays every <base-ref> commit from <squash-commit> on that touched an imported
#      path, setting those paths to that commit's state, with its author and message;
# and then asserts the branch's tree equals <base-ref>'s. Landing it as a FAST-FORWARD
# is what makes `git log`/`git blame` reach the original commits; a merge commit does not.
set -euo pipefail
WT=$1; BASE=$2; SQUASH=$3; shift 3
E=10567847+bamr87@users.noreply.github.com
cd "$WT"
git -c submodule.recurse=false switch -q --detach "$BASE"
paths=(); tips=()
for spec in "$@"; do tips+=("${spec%%:*}"); paths+=("${spec#*:}"); done

# Each tip must hold its own path and nothing else.
for i in "${!tips[@]}"; do
  top=$(git ls-tree --name-only -r "${tips[$i]}" | grep -v "^${paths[$i]}/" | head -1 || true)
  [ -z "$top" ] || { echo "tip ${tips[$i]} has files outside ${paths[$i]}: $top" >&2; exit 1; }
done

# 1. Lift the squashed trees out.
git rm -rq --cached -- "${paths[@]}"
git checkout "$BASE" -- .gitmodules 2>/dev/null || true
git -c user.email=$E commit -q -m "chore(history): lift the squash-imported trees out, to graft their history back (C0)

The import pull requests were squash-merged, so each imported tree arrived as a
single commit. The next commits merge each original's rewritten history back in,
then replay every later change, ending on a tree identical to the one before this
commit. See docs/plan/PLAN.md C0."
rm -rf -- "${paths[@]}"   # run it in a throwaway worktree: ignored-but-tracked files (assets/vendor) survive git clean

# 2. Graft each rewritten history. The merge commit is built by hand (commit-tree) rather
#    than with `git merge`, which refuses with "Already up to date" once a tip is already an
#    ancestor of <base-ref> — the state after a graft branch was merged with a merge commit.
for i in "${!tips[@]}"; do
  git checkout "${tips[$i]}" -- "${paths[$i]}"
  git checkout "$BASE" -- .gitmodules 2>/dev/null || true
  m=$(git -c user.email=$E commit-tree "$(git write-tree)" -p HEAD -p "${tips[$i]}" \
        -m "chore(history): graft the history of ${paths[$i]} (C0)")
  git reset -q "$m"
done

# 3. Replay the later commits that touched an imported path. First-parent only: once a
#    graft has been merged (even as a merge commit), the grafted histories are ancestors
#    of <base-ref> too, and walking into them would replay every original commit again.
for c in $(git rev-list --reverse --first-parent "$SQUASH^..$BASE" -- "${paths[@]}"); do
  touched=()
  for p in "${paths[@]}"; do
    if ! git diff --quiet "$c^" "$c" -- "$p"; then touched+=("$p"); fi
  done
  [ ${#touched[@]} -gt 0 ] || continue
  for p in "${touched[@]}"; do
    git rm -rq --cached --ignore-unmatch -- "$p"
    rm -rf -- "$p"
    if git cat-file -e "$c:$p" 2>/dev/null; then git checkout "$c" -- "$p"; fi
  done
  git checkout "$BASE" -- .gitmodules 2>/dev/null || true
  if git diff --cached --quiet; then continue; fi
  msg=$(git log -1 --format=%B "$c")
  GIT_AUTHOR_NAME=$(git log -1 --format=%an "$c") GIT_AUTHOR_EMAIL=$(git log -1 --format=%ae "$c") \
  GIT_AUTHOR_DATE=$(git log -1 --format=%aI "$c") \
    git -c user.email=$E commit -q -m "$msg" -m "(Replayed from $(git rev-parse --short "$c") onto the grafted history — C0. Only its changes under ${touched[*]} are here; $(git rev-parse --short "$c") itself stays in main.)"
done

# The whole point: nothing but history changed.
if ! git diff --quiet "$BASE" HEAD; then
  echo "TREE MISMATCH against $BASE:" >&2; git diff --stat "$BASE" HEAD >&2; exit 1
fi
echo "OK: $(git rev-list --count "$BASE"..HEAD) commits on top of $(git rev-parse --short "$BASE"), tree identical"
