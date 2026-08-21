---
description: Executes a gbuild graph — dispatches every ready-and-independent node in the current wave concurrently, reviews each node's output with gbuild-reviewer before checkpointing it complete, and resumes only the remaining frontier on re-invocation. Use after /gbuild:plan has written graph.json.
---

Run `.gbuild/$ARGUMENTS/graph.json` (the feature slug is `$ARGUMENTS`).

**CRITICAL: this skill must run in the main context, not inside a forked agent.** It dispatches its own
subagents per node; a subagent cannot itself fan out further subagents reliably.

## Step 0: Load and query

Load `.gbuild/<feature>/graph.json`. Confirm it validates:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph.py .gbuild/<feature>/graph.json --status
```

If it prints `invalid graph: ...`, stop and report — do not attempt to run a graph `plan` didn't finish
correctly. Otherwise take the `frontier` list from the status report. This is the set of nodes ready
right now — not a judgement call, the query already excludes anything blocked, in-flight, or done.

If `frontier` is empty and `completed` + `cancelled` covers every node, the graph is done — report that
and stop. If `frontier` is empty but nodes remain incomplete, there's a stuck cluster (likely an
`escalate`d or `stop`ped node) — report what's blocking per the last checkpoint and stop.

## Step 1: Establish VCS facts

Default to `git`. `git check-ignore -q .gbuild/` tells you whether to stage anything under it at all.

## Step 2: Pick a backend

**Workflow tool**, if this session has opted into multi-agent orchestration (ultracode, or the user
asked for a workflow explicitly) — translate `frontier` into a `pipeline()`/`parallel()` script: each
node is an `agent()` implement call, immediately followed by a `gbuild-reviewer` `agent()` review call
scoped to that node's `contract.output` + `acceptance`, using `schema` for the pass/fail verdict. Code
nodes touching files that could conflict with a concurrent sibling get `isolation: 'worktree'`.
Controlled-cycle clusters become a bounded `while` loop per `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md`'s round cap. Route
`model_tier: strong` nodes via `opts.model` where the harness supports an override.

**Fallback** (default — no opt-in required, and always what step 3 below assumes): fire one `Agent`
tool call per node in the current `frontier`, **all in a single message** — this is what makes the fan-
out real rather than claimed. Do not dispatch them one at a time across separate messages; that's
exactly the serial behavior this plugin replaces.

## Step 3: Per-node dispatch (fallback backend)

For every node in the current wave's `frontier`, in one message, spawn one `Agent` call per node:

1. **IMPLEMENT.** Give the agent the node's `id`, `title`, `type`, `contract.input` (resolved: read the
   actual `output` values from each dependency's `.gbuild/<feature>/nodes/<dep-id>.json`), and
   `acceptance`. Tell it to produce `contract.output`'s declared shape and, for `code`/`test`/`chore`
   nodes, to actually make the change in the working tree (not describe it) and commit it — message
   `<feature>/<node-id>: <what changed>`.
2. **REVIEW.** Once IMPLEMENT returns, spawn a `gbuild-reviewer` agent (agents/gbuild-reviewer.md — this
   plugin's own copy, gbuild does not depend on hone-ai being installed) against the actual diff and
   output. Never let the implementing agent review its own work.
3. **PASS or FAIL:**
   - **Pass** (`VERDICT: pass`): write `.gbuild/<feature>/nodes/<id>.json` with `status: completed`,
     the `output`, the review verdict, and timestamps.
   - **Fail**: apply the node's `failure_policy` (`${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`) — `retry`/`repair`
     re-dispatch (bounded, 2 attempts) with the reviewer's per-criterion failures fed back in;
     `fallback` dispatches the named alternate approach; `skip` checkpoints `cancelled`; `escalate`
     checkpoints `failed` and stops that node's downstream only; `stop` halts the entire run.

Each node's checkpoint write is independent — nodes in the same wave never touch each other's files, so
true concurrent dispatch is safe by construction.

## Step 4: Next wave

Re-run `graph.py --status`. If the wave that just finished unblocked new frontier nodes, repeat step 3
for them. Keep going until `frontier` is empty (done, or stuck — see step 0's exit conditions).

## Step 5: Report and stop

Report: which nodes ran this invocation, which passed review outright vs. needed a repair pass, what's
newly in the frontier or still blocked, and any `failed`/`escalate`d nodes needing a decision.

Close with the next step:

- **Graph fully done** (every node `completed` or `cancelled`) → say so plainly, then
  `next: /gbuild:review <feature>` — the per-node reviews graded each node against its own contract;
  nothing has yet looked at what the accumulated diff did to the codebase.
- **Work remains** (frontier non-empty, or nodes `failed`/`escalate`d awaiting a decision) →
  `next: /gbuild:status <feature>`.

## Resuming

Re-invoking `/gbuild:run <feature>` after an interruption re-runs step 0 fresh: anything with a
`completed` or `cancelled` checkpoint is excluded from `frontier` automatically, so only the genuinely
remaining work re-dispatches. Nothing needs to be told what already finished — the checkpoint files are
the memory.
