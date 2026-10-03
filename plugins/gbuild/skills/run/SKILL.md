---
description: Executes a gbuild graph — dispatches every ready-and-independent node in the current wave concurrently, each file-touching node in its own git worktree, reviews each node's output with gbuild-reviewer before merging its branch and recording it complete, and resumes only the remaining frontier on re-invocation. Use after /gbuild:plan has charted the graph.
---

Run the graph for the feature `$ARGUMENTS` (the slug; step 0 resolves `DB`, the store — it lives in
the feature's own worktree, so this skill never changes the branch of the user's checkout).

**CRITICAL: this skill must run in the main context, not inside a forked agent.** It dispatches its own
subagents per node; a subagent cannot itself fan out further subagents reliably. It is also the store's
**only writer**: subagents never run `cypherlite` — they get what they need in their prompt and report
back in their final message, and this skill records it.

## Store rules

- `cypherlite --version` first. If it's missing, stop: gbuild needs it
  (`curl -sSfL https://neo4j-labs.github.io/cypherlite/install.sh | bash`).
- One `cypherlite` command at a time against `DB` — never parallel tool calls on it, never from a subagent.
- Always `--mode jsonl`: one JSON object per row, no output = no rows. Every `--param` value is JSON,
  single-quoted for the shell (`--param 'slugs=["a","b"]'`).
- `storage locked` → another process holds the store: wait a few seconds, retry up to 3 times, then stop.
  Exit code 1 = failure; read stderr. Anything beyond the scripts below: `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`.
- Never re-read what you already hold. The claimed wave's definitions stay valid for its retries.

## Step 0: Establish VCS facts, then check and recover

Default to `git`. Resolve these facts first, absolute paths, and reuse them throughout:

- `GC` = `git rev-parse --git-common-dir`, resolved to an absolute path; `WT` = `GC/gbuild/$ARGUMENTS`
  (the worktree root — inside `.git/`, so worktrees never appear in `git status` or get committed).
- `FT` = the feature worktree and `BRANCH` = the feature branch — the one place `BRANCH` is checked
  out, and where every merge and store commit below lands:
  1. `WT/tree` is a registered worktree (`git worktree list --porcelain`) → `FT` = it, `BRANCH` =
     `git -C FT branch --show-current`.
  2. Else a worktree whose branch is `$ARGUMENTS` or ends `/$ARGUMENTS` → `FT` = that worktree's path
     (a feature charted before the worktree layout usually has its branch in the main tree).
  3. Else such a branch exists but is checked out nowhere → attach it: `git worktree add WT/tree
     <branch>`, `FT` = `WT/tree`.
  4. Else → stop: there is no feature branch for `$ARGUMENTS` — chart it with `/gbuild:plan` first.
- `DB` = `FT/.gbuild/$ARGUMENTS/db`. `git -C FT check-ignore -q .gbuild/` tells you whether to commit
  the store at all.

Then check and recover:

```
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/validate.cypher
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/attention.cypher
```

- `validate` printing anything → stop and report the rows; do not run a graph `plan` didn't finish
  correctly.
- `attention` rows with reason `in_progress` are left over from an interrupted run (this skill is the
  only writer and records every node before finishing). Check each one's worktree branch for commits
  its agent already made (`git log BRANCH..gbuild/<feature>/<slug>` — empty
  means it never got that far) and leave the worktree in place: the re-dispatch reuses it. Then reset
  them all in one call so they re-dispatch, and mention it in the report:

  ```
  cypherlite DB --mode jsonl --param 'slugs=["<slug>", ...]' --param 'status="pending"' \
    < ${CLAUDE_PLUGIN_ROOT}/cypher/set-status.cypher
  ```

- Sweep the worktree root `WT` for leaks from an interruption that struck mid-cleanup: any worktree
  under `WT` — **except `FT` itself (`WT/tree`)** — whose slug is *not* among the slugs just reset does
  not belong to live work — remove it
  (`git worktree remove --force`) and delete its branch (`git branch -D`). An unmerged branch is
  unaccepted work, which must never land — that is what the isolation is for.

## Step 1: Pick a backend

**Workflow tool**, if this session has opted into multi-agent orchestration (ultracode, or the user
asked for a workflow explicitly) — translate each claimed wave into a `pipeline()`/`parallel()` script:
each node is an `agent()` implement call, immediately followed by a `gbuild-reviewer` `agent()` review
call scoped to that node's outputs + `acceptance`, using `schema` for the pass/fail verdict. Every
file-touching (`code`/`test`/`chore`) node gets `isolation: 'worktree'`.
Controlled-cycle clusters become a bounded `while` loop per `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md`'s
round cap. Route `model_tier: strong` nodes via `opts.model` where the harness supports an override. The
script never touches the store: collect the results, land each accepted node's branch from the main
context (step 2.4), then record (step 2.5).

**Fallback** (default — no opt-in required, and always what step 2 below assumes): fire one `Agent`
tool call per claimed node, **all in a single message** — this is what makes the fan-out real rather
than claimed. Do not dispatch them one at a time across separate messages; that's exactly the serial
behavior this plugin replaces.

## Step 2: One wave

1. **CLAIM.**

   ```
   cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/dispatch.cypher
   ```

   It moves the whole frontier to `in_progress` and prints one row per claimed node with everything its
   agent needs: `slug`, `title`, `type`, `acceptance`, `failure_policy`, `model_tier`, `verify`,
   `inputs` (an input with a `value` came from an upstream node; one without is external — its `shape`
   says where to find it), and `outputs`. **No rows** → nothing is ready: go to step 4.

2. **IMPLEMENT.** First, give every claimed `code`/`test`/`chore` node its own worktree — one shell
   loop over the wave's slugs, idempotent so an interrupted or re-dispatched node keeps its earlier
   work (`research`/`decision` nodes touch no files and get no worktree):

   ```
   mkdir -p WT
   git worktree list --porcelain | grep -q "^worktree .*/<slug>$" \
     || git worktree add WT/<slug> -b gbuild/<feature>/<slug> BRANCH 2>/dev/null \
     || git worktree add WT/<slug> gbuild/<feature>/<slug>
   ```

   (skip if the worktree already exists; else fork a fresh branch off `BRANCH` — just a ref here, the
   cwd doesn't matter; if the branch already
   exists from an earlier attempt, attach to it instead — nothing is redone). Then, in one message,
   spawn one `Agent` per claimed node with its row. Tell it to:
   - actually do the work — for `code`/`test`/`chore` nodes make the change **in its worktree**
     (`WT/<slug>`), never the main working tree: every edit, every check, and every git command runs
     there, and it commits on the node branch, message `<feature>/<slug>: <what changed>`. A worktree
     is a fresh checkout — if the project needs installed dependencies to build or test
     (`node_modules`, `.venv`, …), install or symlink them in the worktree first;
   - before finishing, run the checks relevant to its change — anything the node's `acceptance` names,
     and for `code`/`test` nodes the tests covering the files it touched — and leave them green. The
     per-node review will not re-run these; the full suite runs in the end-of-feature audit;
   - produce a value for every output field: a scalar or a list of scalars, JSON-encoding anything
     nested into a string;
   - record its own UTC start and finish (`date -u +%Y-%m-%dT%H:%M:%SZ`) and end its final message with
     `{"started_at": "...", "completed_at": "...", "outputs": {...}}`;
   - **not** run `cypherlite` or touch `.gbuild/`.

3. **REVIEW.** Once IMPLEMENT returns, spawn a `gbuild-reviewer` per node, again all in one message
   (`agents/gbuild-reviewer.md` — this plugin's own copy, gbuild does not depend on hone-ai being
   installed). Give it the node's row, the agent's reported outputs, and where the diff is — for a
   worktree'd node that is its branch, `git diff BRANCH...gbuild/<feature>/<slug>`, plus the worktree
   path so it can run just the checks `acceptance` names there (the worktree still exists at this
   point). Never let the implementing agent review its own work.

4. **LAND.** For each `pass` verdict on a `code`/`test`/`chore` node, merge its branch into the
   feature branch — in the feature worktree `FT`, never the user's checkout — and clean up:

   ```
   git -C FT merge --no-ff gbuild/<feature>/<slug> \
     && git worktree remove --force WT/<slug> \
     && git branch -d gbuild/<feature>/<slug>
   ```

   A merge conflict means two supposedly independent nodes touched the same lines: `git -C FT merge
   --abort`
   and treat the node as review-failed, the conflict as its failed criterion — step 5's policy decides
   (a retry/repair re-dispatch tells the agent to rebase its branch onto `BRANCH` and resolve it).
   Worktrees and branches are deleted only here, after acceptance — a failed node's stays for its next
   attempt (step 5).

5. **RECORD** the whole wave in one call — one result per node, `verdict` from the reviewer's
   `VERDICT:` line, `failed_criteria` from its `[fail]` lines:

   ```
   cypherlite DB --mode jsonl --param 'results=[
     {"slug": "<slug>", "verdict": "pass", "failed_criteria": [], "outputs": {...},
      "started_at": "<iso>", "completed_at": "<iso>"},
     {"slug": "<slug>", "verdict": "fail", "failed_criteria": ["<criterion>"]}
   ]' < ${CLAUDE_PLUGIN_ROOT}/cypher/record.cypher
   ```

   Each returned row says whether that node `completed`. A slug missing from the output was not
   recorded (it wasn't `in_progress`) — find out why before moving on. `InvalidPropertyType` means an
   output value was a map; the whole batch was rejected — JSON-encode it and send the batch again.

6. **FAILURES.** For each row with `completed: false` (a failed review, an aborted merge, or a pass
   `record` downgraded because `missing_outputs` is non-empty), apply the node's `failure_policy`
   (`${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`), using its `attempt` as the count:
   - `retry` / `repair` → re-dispatch implement → review with the failed criteria fed back in, reusing
     the row you already hold **and the node's existing worktree and branch** — the next attempt builds
     on them, it does not start over. Then record just those nodes. Bounded: 2 attempts.
   - `fallback` → dispatch the named alternate approach the same way, but remove the failed attempt's
     worktree and branch first (`git worktree remove --force`, `git branch -D`) — the alternate
     approach starts from a fresh branch off `BRANCH`.
   - `skip` → `cancelled`; `escalate` (or an exhausted retry/repair) → `failed`, its dependents stay
     blocked while siblings elsewhere keep going; `stop` → `failed` and halt the entire run. One
     `set-status.cypher` call per status, with every slug that gets it. A node reaching a terminal
     status gets cleaned up: `git worktree remove --force WT/<slug>` and
     `git branch -D gbuild/<feature>/<slug>` — its work was never accepted, so it never lands.
   - A completed router (`decision` choosing a branch) → cancel the unselected branches with
     `set-status.cypher` before the next claim.

Nodes in the same wave never read each other's outputs, and every file-touching node works in its own
worktree, so true concurrent dispatch is safe by construction — the store calls and the merges in `FT`
are the only serialized points, and since `FT` belongs to this feature alone, other features (or the
user) changing branches in their own checkouts cannot race them.

## Step 3: Next wave

If `.gbuild/` isn't ignored, commit the store in the feature worktree: `git -C FT add
.gbuild/<feature>/db` and `git -C FT commit -m "<feature>: record wave <n>"`. Then claim again (step 2).
Keep going until a claim returns no rows.

## Step 4: Report and stop

```
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/attention.cypher
```

Every `progress` row with `open: []` → the graph is done. Otherwise `attention` names what's stuck
(`failed` nodes with their last failed criteria, and what they block).

Report: which nodes ran this invocation, which passed review outright vs. needed a repair pass, and any
`failed` nodes needing a decision. Close with the next step:

- **Graph fully done** → say so plainly, then `next: /gbuild:review <feature>` — the per-node reviews
  graded each node against its own contract; nothing has yet looked at what the accumulated diff did to
  the codebase.
- **Work remains** (nodes `failed` awaiting a decision) → `next: /gbuild:status <feature>`.

## Resuming

Re-invoking `/gbuild:run <feature>` after an interruption re-runs step 0 fresh: the feature worktree is
resolved or re-attached, nodes an interrupted wave left `in_progress` are reset (their worktrees and any
commits on their branches survive — the re-dispatch reuses them), and the next claim picks up exactly
the remaining frontier. Nothing needs to be told what already finished — the store is the memory.
