---
description: Reports a gbuild feature's graph — frontier, blocked, in-flight, completed, each node's review verdict, and the cluster shapes with evidence of what actually ran concurrently. Use to check progress or diagnose a stuck run.
---

Report status for `$ARGUMENTS`.

## Mode

| arguments         | mode                                  |
| ------------------ | -------------------------------------- |
| empty              | every feature under `.gbuild/`         |
| a feature slug     | that feature only                      |

## Single feature

### 1. Load

`.gbuild/<feature>/graph.json` and every `.gbuild/<feature>/nodes/*.json` checkpoint. This is a small,
bounded read — status doesn't scale with graph size the way loading full node prose would.

### 2. Compute

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph.py .gbuild/<feature>/graph.json --status
```

Gives `frontier` / `blocked` / `in_flight` / `completed` / `cancelled` / `failed` / `waves` directly —
don't re-derive these by hand.

### 3. Render the graph

Draw the DAG with a marker per node status:

```
✓ completed   ◐ in_progress   ○ pending (frontier)   ● pending (blocked)   ✗ failed
```

Annotate blocked nodes with what they're waiting on: `● d-join-and-sum ← b-consume-doubled, c-consume-squared`.

Group by wave (from `--waves`) so fan-out is visible in the layout, not just in the dependency list.

### 4. Review verdicts

For every `completed` node, one line: pass outright, or passed after N repair attempts, from its
checkpoint's `review` field. For `failed` nodes, the last review's failed acceptance bullets verbatim —
this is what a human needs to make the `escalate`/`stop` call.

### 5. Concurrency evidence

For each wave with more than one node, compare `started_at` timestamps across that wave's checkpoints.
Report whether they actually overlapped (real concurrent dispatch) or ran sequentially despite being in
the same wave (a sign the fallback backend was invoked one node at a time — a bug in how `run` was
driven, not a graph problem).

### 6. Next action

One priority-ordered list: what `/gbuild:run <feature>` would do next (the current frontier), and
anything needing a human decision first (`failed`/`escalate`d nodes, an empty frontier with incomplete
nodes remaining).

### 7. Invariant checks

Numbered, only reporting violations (silence on an item means it passed, not that it was skipped):

1. Every node has non-empty `acceptance` (should already be caught by `graph.py`'s own validation —
   report if a node manages to lack it anyway, since that means the file was hand-edited or written by
   something other than `plan`).
2. Every global `acceptance` bullet is `satisfies`-covered by at least one node.
3. `dependencies` is acyclic (validated by `graph.py` already; report if it somehow wasn't checked).
4. No `completed` node's checkpoint is missing a `review` field with `verdict: pass` — a node marked
   complete without a passing review means `run` skipped the review step.
5. Every `chore` node is depended on by at least one other node.

If all five are clear, say so in one line — don't let silence be ambiguous between "checked, clear" and
"not checked."

## All-features mode

For each `.gbuild/<slug>/graph.json` found, one line: slug, node counts by status, and whether the
frontier is empty (done or stuck) or has ready work. Point at `/gbuild:status <slug>` for detail.
