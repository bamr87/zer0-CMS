# tools/history

`graft.sh` restores history that a squash merge dropped: it builds a branch on top of `main` that lifts the imported paths out, merges each original's rewritten history back, replays every later change, and ends on a tree identical to `main`'s. It is cutover milestone C0 (`docs/plan/PLAN.md`), and it has to land as a **fast-forward** — a merge commit leaves `git log` and `git blame` stopping at the squash. Run it in a throwaway worktree, never in a checkout you are working in.

The zer0-CMS invocation, with the tips taken from `refs/pull/29/head` and `refs/pull/36/head` (each is the second parent of that PR's `import … with full history` merge):

```bash
git fetch origin main refs/pull/29/head refs/pull/36/head
git worktree add --detach /tmp/c0 origin/main
tools/history/graft.sh /tmp/c0 origin/main 5bd4bd18 \
  af43e7f2169040fa447f405cbfd83b923d9f8f65:packages/zer0-mistakes \
  4c4b9ee9cffa4212721dae0a4a2decb81bae18c6:packages/zer0-image-generator \
  e2d0a8ec3a97eecdbf682a01a078558a633a171f:packages/books \
  5b6208af3b4ce1fa32c5a678fee763b782b176e9:apps/barodybroject \
  8b031fec88a67e7f0570f40dc216b83f75f63d5c:sites/drsai \
  0162b68bbfb7853bde3d2e7cff01e977d68adfd5:sites/zer0-pages \
  a04cbe931f66694e826b86c03f214fc40eb648b2:sites/zer0-pages-remote \
  1da213179097769ebc7c0721c2f5bad6075a2e59:sites/zer0-demo-cookbook \
  30ec5fba3868323896d036d99b3165c3d33f3ed7:sites/zer0-demo-garden \
  d04e3ce0e1e28c0a697332240af024f6332bb7b7:sites/1987 \
  aabf7ed47ca785cc9303833bb728281dc824dfd3:sites/2005
```

If `main` moves before the branch lands, run it again on the new `main` instead of rebasing: a rebase flattens the merges that carry the history.
