---
description: Removes a gbuild feature's entire local footprint — every worktree it opened (the feature worktree and each node's), its feature and node branches, the CypherLite store, and the inbox — after checking the graph's state and where its work landed, with one confirmation listing everything that dies. Local only — never the remote, never the user's own checkout. Use when the feature's PR is merged and the graph is no longer needed, or the feature is abandoned for good.
---

Remove the local footprint of the feature `$ARGUMENTS` (the slug): every worktree gbuild opened for it,
its branches, and its store — everything under `<git-common-dir>/gbuild/<slug>/` dies with the feature.
`pr` published the branch; this reclaims what it left behind on this machine.

**CRITICAL: local only, destructive, confirmed.** This skill never touches the remote — never pushes,
never deletes a remote branch, never closes a PR — and never removes or re-branches the user's own
checkout or another feature's worktrees. It deletes exactly one feature's local footprint, and only
after the step-3 confirmation.

## Step 0: Resolve the slug — never infer it

`$ARGUMENTS` must name the feature explicitly: the first token that isn't a flag. Cleanup deletes the
feature's whole local footprint, so it never guesses a slug the way `review` and `pr` do. Empty →
list what exists — one line per directory under `<git-common-dir>/gbuild/` — and stop, asking the user
to re-invoke with a slug. Nothing exists there → say so and stop: there is nothing to clean up.

## Step 1: Establish VCS facts

Default to `git`. Resolve, absolute: `GC` = `git rev-parse --git-common-dir`, `WT` = `GC/gbuild/<slug>`,
`DB` = `WT/db`, `INBOX` = `WT/inbox`. Locate the feature branch and worktree read-only — unlike
`/gbuild:run`'s step 0 this never attaches a worktree (creating one just to delete it is noise):

1. `WT/tree` is a registered worktree (`git worktree list --porcelain`) → `FT` = it, `BRANCH` =
   `git -C FT branch --show-current`.
2. Else a registered worktree whose branch is `<slug>` or ends `/<slug>` → `FT` = that worktree's path
   (a legacy feature). When `FT` is not under `WT` — usually the user's own checkout — gbuild did not
   open it: nothing is removed there, and a branch checked out there cannot be deleted; say so in the
   report.
3. Else a branch named `<slug>` or ending `/<slug>` exists (`git branch --list`) → `BRANCH` = it; no
   `FT` (it is checked out nowhere).
4. Else no feature branch: with `WT` present, only the store, inbox and leftovers remain — steps 2–4
   still clean them; without `WT` there is nothing left — say so and stop.

`NODE_WTS` = every registered worktree under `WT` except `FT`. `NODE_BRANCHES` =
`git branch --list 'gbuild/<slug>/*'`. Both are interrupted-run leftovers by definition — `run`
removes each the moment its node is accepted or terminally fails — so they are unaccepted work and
always removed with force, no questions asked.

## Step 2: Read the store

`DB` present → `cypherlite --version` first (missing → stop: gbuild needs it, and this skill will not
delete a store it could not read). Store rules as ever: one `cypherlite` command at a time,
`--read-only --mode jsonl` (no output = no rows), on `storage locked` wait and retry up to 3 times;
the full manual is `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`.

```
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/attention.cypher
```

No `DB` → the store is already gone (or was never charted); say so — the git work below is the whole
job. A gbuild ≤ 0.7.1 store may instead sit git-tracked at `FT/.gbuild/` — when `FT` survives cleanup
(a legacy feature in the user's checkout), list that directory in the inventory and leave removing it
to the user (`git rm -r --cached .gbuild`, per `reference/cypher.md`); when `FT` is removed, it dies
with the worktree.

## Step 3: Assemble the inventory, confirm once

Everything below dies in one confirmation, so gather it all first:

- **Graph state.** Every `progress` row with a non-empty `open` — the feature is not finished.
  `attention`: `in_progress` means a run may be active or interrupted — confirm no `/gbuild:run` is in
  flight before deleting anything; `failed` and `blocked-by-failed` name the stuck work being thrown
  away.
- **Uncommitted changes in `FT`** (`git -C FT status --porcelain`): they die with the worktree — list
  the files.
- **Where the work landed**, when `BRANCH` exists:
  - merged into its upstream — `git rev-parse --abbrev-ref BRANCH@{upstream}` resolves and
    `git merge-base --is-ancestor BRANCH <upstream>` is true → **landed**. (A squash-merged PR leaves
    the branch unmerged by ancestry, so also:)
  - else a merged PR — `gh pr list --head BRANCH --state merged` returns one, when `gh` is installed
    and authenticated → **landed**.
  - else another local branch contains it — `git branch --contains BRANCH` lists one besides
    `BRANCH` itself (which is always listed) → **landed** (merged locally, no remote involved).
  - else **not landed**. Show what a deletion would lose:
    `git log --oneline BRANCH --not --exclude=BRANCH --branches --remotes --tags | head -20` — the
    commits reachable from `BRANCH` and from no other ref. Empty list → every commit lives on
    somewhere (a pushed remote ref, another branch), so `-D` loses nothing local-only; non-empty →
    these commits exist only on this machine, and deleting the branch takes `git branch -D` and
    loses them.

Present the complete inventory — the feature and `BRANCH`; `NODE_WTS` and `NODE_BRANCHES` (always
deleted); `FT` (removed when under `WT`, otherwise left alone); the uncommitted files, if any; `DB`,
`INBOX` and everything else under `WT`, the feature's whole memory; the graph state; landed or not —
and ask once. Anything unfinished, uncommitted, unlanded, or possibly mid-run is called out
explicitly; the user confirms all of it or nothing. No → stop; nothing is deleted.

## Step 4: Delete

In this order — a worktree under `WT` cannot be `rm -rf`'d while registered, and a branch cannot be
deleted while checked out:

1. Node leftovers: `git worktree remove --force` each `NODE_WTS` entry, then `git branch -D` each
   `NODE_BRANCHES` entry.
2. `FT`, when it is under `WT`: `git worktree remove --force FT`.
3. `BRANCH`, when it exists: `git branch -d BRANCH` first — success is git's own proof that HEAD or the
   upstream contains the work. Refusal is not a verdict (git cannot see a squash-merged PR or a local
   merge), so fall back to the step-3 loss list: empty → `git branch -D BRANCH`, nothing local-only
   dies; non-empty → `git branch -D BRANCH` only on the user's confirmation of those commits. A
   refusal naming a worktree — the branch is checked out in a legacy `FT` — → leave it and report.
4. What is left of `WT`: `rm -rf WT` — the store, the inbox, anything else — then
   `rmdir GC/gbuild 2>/dev/null || true` (only succeeds when no other feature's directory remains),
   and `git worktree prune` to drop stale registrations an interrupted removal may have left.

## Step 5: Report

What was removed — worktrees, branches, the store — and what was kept, with its reason: the remote
branch (never touched), a legacy `BRANCH` still checked out in the user's own checkout, an unlanded
branch the user chose to keep (give its one-liner: `git branch -D <branch>`, should they change their
mind). A cleanup is the end of a feature — no `next:` line follows it.
