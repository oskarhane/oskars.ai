---
description: Executes a gbuild graph — dispatches every ready-and-independent node in the current wave concurrently, reviews each node's output with gbuild-reviewer before recording it complete, and resumes only the remaining frontier on re-invocation. Use after /gbuild:plan has charted the graph.
---

Run the graph in `.gbuild/$ARGUMENTS/db` (the feature slug is `$ARGUMENTS`; `DB` below).

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

## Step 0: Check and recover

```
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/validate.cypher
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/attention.cypher
```

- `validate` printing anything → stop and report the rows; do not run a graph `plan` didn't finish
  correctly.
- `attention` rows with reason `in_progress` are left over from an interrupted run (this skill is the
  only writer and records every node before finishing). Check `git log` for commits their agents already
  made, then reset them all in one call so they re-dispatch, and mention it in the report:

  ```
  cypherlite DB --mode jsonl --param 'slugs=["<slug>", ...]' --param 'status="pending"' \
    < ${CLAUDE_PLUGIN_ROOT}/cypher/set-status.cypher
  ```

## Step 1: Establish VCS facts

Default to `git`. `git check-ignore -q .gbuild/` tells you whether to commit the store at all.

## Step 2: Pick a backend

**Workflow tool**, if this session has opted into multi-agent orchestration (ultracode, or the user
asked for a workflow explicitly) — translate each claimed wave into a `pipeline()`/`parallel()` script:
each node is an `agent()` implement call, immediately followed by a `gbuild-reviewer` `agent()` review
call scoped to that node's outputs + `acceptance`, using `schema` for the pass/fail verdict. Code nodes
touching files that could conflict with a concurrent sibling get `isolation: 'worktree'`.
Controlled-cycle clusters become a bounded `while` loop per `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md`'s
round cap. Route `model_tier: strong` nodes via `opts.model` where the harness supports an override. The
script never touches the store: collect the results and record them from the main context (step 3.4).

**Fallback** (default — no opt-in required, and always what step 3 below assumes): fire one `Agent`
tool call per claimed node, **all in a single message** — this is what makes the fan-out real rather
than claimed. Do not dispatch them one at a time across separate messages; that's exactly the serial
behavior this plugin replaces.

## Step 3: One wave

1. **CLAIM.**

   ```
   cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/dispatch.cypher
   ```

   It moves the whole frontier to `in_progress` and prints one row per claimed node with everything its
   agent needs: `slug`, `title`, `type`, `acceptance`, `failure_policy`, `model_tier`, `verify`,
   `inputs` (an input with a `value` came from an upstream node; one without is external — its `shape`
   says where to find it), and `outputs`. **No rows** → nothing is ready: go to step 5.

2. **IMPLEMENT.** In one message, spawn one `Agent` per claimed node with its row. Tell it to:
   - actually do the work — for `code`/`test`/`chore` nodes make the change in the working tree (not
     describe it) and commit it, message `<feature>/<slug>: <what changed>`;
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
   installed). Give it the node's row, the agent's reported outputs, and where the diff is. Never let
   the implementing agent review its own work.

4. **RECORD** the whole wave in one call — one result per node, `verdict` from the reviewer's
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

5. **FAILURES.** For each row with `completed: false` (a failed review, or a pass `record` downgraded
   because `missing_outputs` is non-empty), apply the node's `failure_policy`
   (`${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`), using its `attempt` as the count:
   - `retry` / `repair` → re-dispatch implement → review with the failed criteria fed back in, reusing
     the row you already hold, then record just those nodes. Bounded: 2 attempts.
   - `fallback` → dispatch the named alternate approach the same way.
   - `skip` → `cancelled`; `escalate` (or an exhausted retry/repair) → `failed`, its dependents stay
     blocked while siblings elsewhere keep going; `stop` → `failed` and halt the entire run. One
     `set-status.cypher` call per status, with every slug that gets it.
   - A completed router (`decision` choosing a branch) → cancel the unselected branches with
     `set-status.cypher` before the next claim.

Nodes in the same wave never read each other's outputs, so true concurrent dispatch is safe by
construction — only the store calls are serialized.

## Step 4: Next wave

If `.gbuild/` isn't ignored, commit the store: `git add .gbuild/<feature>/db` and
`git commit -m "<feature>: record wave <n>"`. Then claim again (step 3). Keep going until a claim
returns no rows.

## Step 5: Report and stop

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

Re-invoking `/gbuild:run <feature>` after an interruption re-runs step 0 fresh: nodes an interrupted
wave left `in_progress` are reset, and the next claim picks up exactly the remaining frontier. Nothing
needs to be told what already finished — the store is the memory.
