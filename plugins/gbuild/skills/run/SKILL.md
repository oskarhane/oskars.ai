---
description: Executes a gbuild graph — dispatches every ready-and-independent node in the current wave concurrently, reviews each node's output with gbuild-reviewer before recording it complete, and resumes only the remaining frontier on re-invocation. Use after /gbuild:plan has charted the graph.
---

Run the graph in `.gbuild/$ARGUMENTS/db` (the feature slug is `$ARGUMENTS`).

**CRITICAL: this skill must run in the main context, not inside a forked agent.** It dispatches its own
subagents per node; a subagent cannot itself fan out further subagents reliably. It is also the store's
**only writer**: subagents never run `cypherlite` — they get what they need in their prompt and report
back in their final message, and this skill records it. Read `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`
first and run its version check; `DB` below is `.gbuild/<feature>/db`.

## Step 0: Load and query

**Confirm the graph is well-formed:**

```
cypherlite DB -json < ${CLAUDE_PLUGIN_ROOT}/cypher/validate.cypher
```

Anything but `[]` → stop and report the rows; do not run a graph `plan` didn't finish correctly. Then:

```
cypherlite DB -json < ${CLAUDE_PLUGIN_ROOT}/cypher/status.cypher
```

- **Rows with `state: in_progress`** at this point are left over from an interrupted run (this skill is
  the only writer, and it records every node before finishing). Check `git log` for commits the node's
  agent already made, reset each to `pending` with `set-status.cypher` (`--param 'status="pending"'`) so
  it re-dispatches, and mention it in the report.
- The rows with `state: frontier` are the set ready right now — not a judgement call; the query already
  excludes anything blocked, in flight, or done.
- If there is no frontier and every row is `completed` or `cancelled`, the graph is done — report that
  and stop. If there is no frontier but nodes remain incomplete, there's a stuck cluster (likely an
  `escalate`d or `stop`ped node, now `failed`) — report what's blocking and stop.

## Step 1: Establish VCS facts

Default to `git`. `git check-ignore -q .gbuild/` tells you whether to commit the store at all.

## Step 2: Pick a backend

**Workflow tool**, if this session has opted into multi-agent orchestration (ultracode, or the user
asked for a workflow explicitly) — translate the frontier into a `pipeline()`/`parallel()` script: each
node is an `agent()` implement call, immediately followed by a `gbuild-reviewer` `agent()` review call
scoped to that node's outputs + `acceptance`, using `schema` for the pass/fail verdict. Code nodes
touching files that could conflict with a concurrent sibling get `isolation: 'worktree'`.
Controlled-cycle clusters become a bounded `while` loop per `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md`'s
round cap. Route `model_tier: strong` nodes via `opts.model` where the harness supports an override. The
script never touches the store: collect every implement and review result, then record them from the
main context exactly as step 3.4 describes.

**Fallback** (default — no opt-in required, and always what step 3 below assumes): fire one `Agent`
tool call per frontier node, **all in a single message** — this is what makes the fan-out real rather
than claimed. Do not dispatch them one at a time across separate messages; that's exactly the serial
behavior this plugin replaces.

## Step 3: One wave (fallback backend)

1. **MARK.** Move the whole frontier to `in_progress` in one call and check that `dispatched` lists every
   slug you passed:

   ```
   cypherlite DB -json --param 'slugs=["<slug>", ...]' < ${CLAUDE_PLUGIN_ROOT}/cypher/dispatch.cypher
   ```

   Then fetch each node's definition — `node.cypher` with `--param 'slug="<slug>"'`, one call per node,
   one after the other. Its `inputs` are already resolved: each input read from another node carries
   the upstream `value`.

2. **IMPLEMENT.** In one message, spawn one `Agent` per node. Give each the node's `slug`, `title`,
   `type`, `inputs` (name, shape, value — or for an input with no `from`, where to find it),
   `outputs` (name, shape), and `acceptance`. Tell it to:
   - actually do the work — for `code`/`test`/`chore` nodes make the change in the working tree (not
     describe it) and commit it, message `<feature>/<slug>: <what changed>`;
   - produce a value for every output field: a scalar or a list of scalars, JSON-encoding anything
     nested into a string;
   - record its own UTC start and finish (`date -u +%Y-%m-%dT%H:%M:%SZ`) and end its final message with
     a JSON object `{"started_at": "...", "completed_at": "...", "outputs": {...}}`;
   - **not** run `cypherlite` or touch `.gbuild/`.

3. **REVIEW.** Once IMPLEMENT returns, spawn a `gbuild-reviewer` agent per node, again all in one message
   (`agents/gbuild-reviewer.md` — this plugin's own copy, gbuild does not depend on hone-ai being
   installed). Give it the node definition from `node.cypher`, the implementing agent's reported
   outputs, and where the diff is. Never let the implementing agent review its own work.

4. **RECORD** — sequentially, one `cypherlite` call at a time, after the agents returned. For each node:

   ```
   cypherlite DB -json --param 'slug="<slug>"' --param 'verdict="pass"' --param 'failed_criteria=[]' \
     < ${CLAUDE_PLUGIN_ROOT}/cypher/record-review.cypher
   ```

   (`verdict="fail"` and the reviewer's failed criteria as `failed_criteria` on a fail.)

   - **Pass** (`VERDICT: pass`): record it complete with the agent's outputs and times.

     ```
     cypherlite DB -json --param 'slug="<slug>"' --param 'outputs={...}' \
       --param 'started_at="<iso>"' --param 'completed_at="<iso>"' < ${CLAUDE_PLUGIN_ROOT}/cypher/complete.cypher
     ```

     Check `completed: true`. If it is `false`, `missing_outputs` names the output fields the agent didn't
     produce — treat that as a failed review with those as the failed criteria. An `InvalidPropertyType`
     error means an output value was a map: JSON-encode it into a string and record again.
   - **Fail**: apply the node's `failure_policy` (`${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`).
     `retry`/`repair` re-dispatch implement → review (bounded: 2 attempts — `review_attempts` in
     `status.cypher` counts them) with the reviewer's failed criteria fed back in; the node stays
     `in_progress`. `fallback` dispatches the named alternate approach. `skip` sets it `cancelled`,
     `escalate` sets it `failed` (its dependents stay blocked; siblings elsewhere keep going), both with
     `set-status.cypher`. `stop` sets it `failed` and halts the entire run.

Nodes in the same wave never read each other's outputs, so true concurrent dispatch is safe by
construction — only the recording is serialized.

## Step 4: Next wave

If `.gbuild/` isn't ignored, commit the store: `git add .gbuild/<feature>/db` and
`git commit -m "<feature>: record wave <n>"`. Re-run `status.cypher`. If the wave that just finished
unblocked new frontier nodes, repeat step 3 for them. Keep going until there is no frontier (done, or
stuck — see step 0's exit conditions).

## Step 5: Report and stop

Report: which nodes ran this invocation, which passed review outright vs. needed a repair pass, what's
newly on the frontier or still blocked, and any `failed` nodes needing a decision.

Close with the next step:

- **Graph fully done** (every node `completed` or `cancelled`) → say so plainly, then
  `next: /gbuild:review <feature>` — the per-node reviews graded each node against its own contract;
  nothing has yet looked at what the accumulated diff did to the codebase.
- **Work remains** (frontier non-empty, or nodes `failed` awaiting a decision) →
  `next: /gbuild:status <feature>`.

## Resuming

Re-invoking `/gbuild:run <feature>` after an interruption re-runs step 0 fresh: completed and cancelled
nodes are excluded from the frontier automatically, and nodes an interrupted wave left `in_progress` are
reset and re-dispatched. Nothing needs to be told what already finished — the store is the memory.
