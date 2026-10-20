---
description: Executes a gbuild graph as dataflow — each node starts the moment its own dependencies complete and runs its own implement → review → land → record pipeline in background subagents (each file-touching node in its own git worktree), handing agents only slugs and paths, recording a node complete only after gbuild-reviewer passes it, and resuming only the remaining frontier on re-invocation. Use after /gbuild:plan has charted the graph.
---

Run the graph for the feature `$ARGUMENTS` (the slug; step 0 resolves `DB`, the store — the feature
branch lives in its own worktree, so this skill never changes the branch of the user's checkout).

**CRITICAL: this skill must run in the main context, not inside a forked agent.** It dispatches its own
subagents per node; a subagent cannot itself fan out further subagents reliably. It is also the store's
**only writer**: agents read their brief from the store themselves and leave their result in the inbox;
this skill passes them slugs and paths, reads their one-line replies, and records.

## Store rules

- `cypherlite --version` first. If it's missing, stop: gbuild needs it
  (`curl -sSfL https://neo4j-labs.github.io/cypherlite/install.sh | bash`).
- You are the only writer: `dispatch`, `set-status` and `record` run only here, one `cypherlite` command
  at a time against `DB` — never parallel tool calls on it. Subagents may run `cypherlite` only with
  `--read-only` (a read opens beside the writer); their agent files say what they read.
- Always `--mode jsonl`: one JSON object per row, no output = no rows. Every `--param` value is JSON,
  single-quoted for the shell (`--param 'slugs=["a","b"]'`); write a `'` inside it as `\u0027`.
- Pure reads (validate, attention, progress below) open the store `--read-only`; the writes
  (dispatch, set-status, record) stay writable — the CLI checkpoints a writable store on exit itself.
- `storage locked` (exit 5) → another writer holds the store: wait a few seconds, retry up to 3 times,
  then stop. Exit code 1 = failure; read stderr. Anything beyond the scripts below:
  `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`.
- Hold only what routes: dispatch rows, one reply line per agent, record rows. Never open a result file,
  a review file or a diff, and never type acceptance text or output values — the store and the inbox
  carry them.

## Step 0: Establish VCS facts, then check and recover

Default to `git`. Resolve these facts first, absolute paths, and reuse them throughout:

- `GC` = `git rev-parse --git-common-dir`, resolved to an absolute path; `WT` = `GC/gbuild/$ARGUMENTS`
  (the worktree root — inside `.git/`, so worktrees never appear in `git status` or get committed).
- `FT` = the feature worktree and `BRANCH` = the feature branch — the one place `BRANCH` is checked
  out, and where every merge below lands:
  1. `WT/tree` is a registered worktree (`git worktree list --porcelain`) → `FT` = it, `BRANCH` =
     `git -C FT branch --show-current`.
  2. Else a worktree whose branch is `$ARGUMENTS` or ends `/$ARGUMENTS` → `FT` = that worktree's path
     (a feature charted before the worktree layout usually has its branch in the main tree).
  3. Else such a branch exists but is checked out nowhere → attach it: `git worktree add WT/tree
     <branch>`, `FT` = `WT/tree`.
  4. Else → stop: there is no feature branch for `$ARGUMENTS` — chart it with `/gbuild:plan` first.
- `DB` = `WT/db` — the feature's store, beside the worktree: machine-local, never committed (a gbuild ≤ 0.7.1
  store needs the move in `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`).
- `INBOX` = `WT/inbox` — beside `DB`, outside every worktree: each implementer writes `<slug>.json`
  there and each reviewer `<slug>.review.json`; only `record.cypher` reads them, on your behalf.

Then check and recover:

```
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/validate.cypher
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/attention.cypher
```

- `validate` printing anything → stop and report the rows; do not run a graph `plan` didn't finish
  correctly.
- `attention` rows with reason `in_progress` are left over from an interrupted run (this skill is the
  only writer and records every node before finishing). Check each one's worktree branch for commits
  its agent already made (`git log BRANCH..gbuild/<feature>/<slug>` — empty
  means it never got that far) and leave the worktree in place: the re-dispatch reuses it. Then reset
  them all in one call so they re-dispatch, and mention it in the report:

  ```
  cypherlite query --database DB --mode jsonl --param 'slugs=["<slug>", ...]' --param 'status="pending"' \
    < ${CLAUDE_PLUGIN_ROOT}/cypher/set-status.cypher
  ```

- Sweep the worktree root `WT` for leaks from an interruption that struck mid-cleanup: any registered
  worktree under `WT` (`git worktree list --porcelain` — `db/` and `inbox/` are not worktrees) — **except
  `FT` itself (`WT/tree`)** — whose slug is *not* among the slugs just reset does not belong to live
  work — remove it (`git worktree remove --force`) and delete its branch (`git branch -D`). An unmerged
  branch is unaccepted work, which must never land — that is what the isolation is for.
- Create the inbox empty. This discards the files of the nodes just reset — an interrupted attempt is
  never recorded; they re-dispatch from scratch on top of their surviving worktrees:

  ```
  mkdir -p WT/inbox
  find WT/inbox -type f -delete
  ```

## Step 1: Pick a backend

**Workflow tool**, if this session has opted into multi-agent orchestration (ultracode, or the user
asked for a workflow explicitly) — one `pipeline()` per claimed node: its implement `agent()`, then its
`gbuild-reviewer` `agent()`, prompted exactly as in step 2.2 and read as in step 2.3, so a review starts
the moment its implementer finishes and no node waits on another. Nodes use the worktrees step 2.2
creates (no `isolation` option: the prompt names the worktree). Controlled-cycle clusters become a
bounded `while` loop per `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md`'s round cap. Route
`model_tier: strong` nodes via `opts.model` where the harness supports an override. The script never
touches the store: as each pipeline returns, land and record that node from the main context (steps
2.4–2.6), then claim again (step 3) and start pipelines for the new rows.

**Fallback** (default — no opt-in required, and always what step 2 below assumes): one background
subagent call per agent. When several nodes become ready at once, dispatch them all in a single
message — never one per message, which is exactly the serial behavior this plugin replaces.

## Step 2: One node's pipeline

Every claimed node runs this pipeline on its own — implement → review → land → record — and different
nodes are at different steps at the same time. Handle each completion the moment it arrives; never hold
a node back for another.

1. **CLAIM.**

   ```
   cypherlite query --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/dispatch.cypher
   ```

   It moves every pending node whose dependencies are all completed or cancelled to `in_progress` and
   prints one routing row per claimed node: `slug`, `type`, `model_tier`, `failure_policy`. That is all
   you need — agents read the rest themselves. **No rows** → nothing newly ready (step 3).

2. **IMPLEMENT.** A `code`/`test`/`chore` node first gets its own worktree (`research`/`decision`/`verify`
   nodes edit no files and get none) — idempotent, so a reset or re-dispatched node keeps its earlier work:

   ```
   git worktree list --porcelain | grep -q "^worktree .*/<slug>$" \
     || git worktree add WT/<slug> -b gbuild/<feature>/<slug> BRANCH 2>/dev/null \
     || git worktree add WT/<slug> gbuild/<feature>/<slug>
   ```

   (reuse an existing worktree; else fork a fresh branch off `BRANCH`, or attach the branch an earlier
   attempt left — nothing is redone). Then dispatch the implementer — `Agent` tool, `subagent_type`
   `gbuild-implementer` / `gbuild-reviewer` (`gbuild:`-prefixed when namespaced), description
   `implement <slug>` / `review <slug>`, `run_in_background: true` — with this one prompt for both agents:

   ```
   gbuild node `<slug>`. Store: <DB>. Worktree: <worktree>. Feature branch: <BRANCH>. Agent file: ${CLAUDE_PLUGIN_ROOT}/agents/gbuild-<implementer|reviewer>.md.
   ```

   `<DB>`, `<BRANCH>` are `DB`, `BRANCH`; `<implementer|reviewer>` names the agent; `<worktree>` is
   `WT/<slug>` for `code`/`test`/`chore` and `FT` (read-only) otherwise — every path absolute. The
   implementer gets a model per its `model_tier` where the harness offers one
   (`${CLAUDE_PLUGIN_ROOT}/reference/cost-model.md`).
   Append nothing — no acceptance, inputs, outputs, notes, failed criteria or agent-file text. Retries,
   repairs and fallbacks use the same prompt: the agent's brief carries the failed criteria.

3. **REVIEW.** The implementer replies with one line; read nothing else:
   - `done <slug>` and `test -s INBOX/<slug>.json` → dispatch its reviewer right away with the same
     prompt naming `gbuild-reviewer.md` — a fresh agent, never the implementer.
   - `done <slug>` but no file → no review; record a fail: `["implementer reported done but <slug>.json is missing"]`.
   - `failed <slug>: <reason>` → no review; record a fail: `["implementer failed: <reason>"]`.

   The reviewer replies `VERDICT: pass`, or `VERDICT: fail` plus one `[fail] <criterion> — <reason>`
   line per failed check. It is a pass only with a line exactly `VERDICT: pass` and no `[fail]` lines;
   `failed_criteria` is the text after `[fail] ` on each line, verbatim and in order. No `VERDICT` line
   → re-dispatch that reviewer once in the foreground (no background flag); still none →
   `["reviewer returned no verdict"]`. A `[fail] CONTRADICTS <upstream-slug>` line also hands that
   upstream node to its own `failure_policy` (step 2.6). The verdict comes only from this reply — never
   from `INBOX/<slug>.review.json`.

4. **LAND.** A `pass` on a `code`/`test`/`chore` node merges its branch into the feature worktree `FT`,
   never the user's checkout — one merge at a time, never two in parallel:

   ```
   git -C FT merge --no-ff gbuild/<feature>/<slug>
   ```

   A conflict means two supposedly independent nodes touched the same lines: list them
   (`git -C FT diff --name-only --diff-filter=U`), `git -C FT merge --abort`, and record a fail instead:
   `["merge conflict with BRANCH in <path>[, <path>] — rebase gbuild/<feature>/<slug> onto BRANCH and resolve"]`.

5. **RECORD** — one call per node, as soon as its verdict is settled:

   ```
   cypherlite query --database DB --mode jsonl \
     --param 'verdict={"slug":"<slug>","verdict":"pass","failed_criteria":[]}' \
     --fetch-params result=INBOX/<slug>.json --fetch-params review=INBOX/<slug>.review.json \
     < ${CLAUDE_PLUGIN_ROOT}/cypher/record.cypher
   ```

   `verdict` is all you type: `pass`, or `fail` with `failed_criteria` — the reviewer's `[fail]` lines
   or one of the fixed lines in steps 2.3–2.4, never your own words. Bind `result` from its file only on
   a pass (`--param 'result={}'` on every fail), and `review` from its file whenever `test -s` finds it
   (else `--param 'review={}'`) — all three are always bound. record.cypher takes the outputs, times,
   notes and symbols from the file itself.

   No row, or another slug → it wasn't recorded (the node wasn't `in_progress`) — find out why. Exit 1
   or 6 → re-run once with `--param 'review={}'`; still failing → re-run with `--param 'result={}'
   --param 'review={}'` and verdict `fail`,
   `["result file rejected by record.cypher: <error.kind>: <error.message, first 120 chars>"]`, which
   can't fail. Then `rm -f INBOX/<slug>.*` and:
   - `completed: true` → for a worktree'd node `git worktree remove --force WT/<slug>` and
     `git branch -d gbuild/<feature>/<slug>` — only now, so a pass downgraded after its merge repairs in
     place. Non-empty `unselected` (a router's unchosen branches) → cancel them with
     `set-status.cypher`. Then claim again (step 3).
   - `completed: false` (a failed review, a merge conflict, a failed implementer, or a pass downgraded
     because `missing_outputs` is non-empty) → step 2.6.

6. **FAILURES.** Apply the node's `failure_policy` (`${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`),
   using its `attempt` as the count:
   - `retry` / `repair` → back to step 2.2 with the same prompt, reusing the node's existing worktree
     and branch — the next attempt builds on them, it does not start over. Bounded: 2 attempts.
   - `fallback` → remove the failed attempt's worktree and branch first (`git worktree remove --force`,
     `git branch -D`), then step 2.2 — a fresh branch off `BRANCH`; the brief names the alternate
     approach.
   - `skip` → `cancelled`; `escalate` (or an exhausted retry/repair) → `failed`, its dependents stay
     blocked while everything else keeps going; `stop` → `failed` and halt the run. Set it with
     `set-status.cypher`, then clean up a worktree'd node: `git worktree remove --force WT/<slug>` and
     `git branch -D gbuild/<feature>/<slug>` — its work was never accepted, so it never lands.

   Then claim again (step 3) — except after `stop`: claim nothing more, finish the pipelines in flight,
   then step 4.

## Step 3: Claim again

After every `record.cypher` and `set-status.cypher` call, run dispatch.cypher (step 2.1) again and start
step 2.2 for every row it returns. That is the dataflow: a node starts the moment its own dependencies
complete, while unrelated slower nodes are still running. Between claims, wait for completion
notifications and handle each as it arrives.

A node is claimed only once everything it depends on has completed, so nodes in flight together never
read each other's outputs, and every file-touching node works in its own worktree — concurrency is safe
by construction. Your store calls and the merges into `FT` are the only serialized points; `FT` belongs
to this feature alone, so no other checkout can race them.

**Lost notifications.** Claude Code can drop a completion notification when 3 or more background agents
run at once. When an agent stays silent well past ones started after it, or you wake with nothing new to
handle, check instead of waiting: an implementer whose `INBOX/<slug>.json` exists counts as
`done <slug>` (it writes `.tmp` then renames, so presence means complete); otherwise, and for a
reviewer, fetch the reply by task id (`TaskOutput`) where the harness offers it. A reviewer whose reply
still can't be had is re-dispatched once in the foreground (step 2.3). Never take a verdict from a file.

Stop when a claim returns no rows and no agent is in flight: step 4.

## Step 4: Report and stop

```
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/attention.cypher
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
resolved or re-attached, nodes an interrupted run left `in_progress` are reset (their worktrees and any
commits on their branches survive — the re-dispatch reuses them; their inbox files are discarded), and
the next claim picks up exactly the remaining frontier. Nothing needs to be told what already finished —
the store is the memory.
