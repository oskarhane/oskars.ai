---
description: Reports a gbuild feature's graph — frontier, blocked, in-flight, completed, each node's review verdict, and the cluster shapes with evidence of what actually ran concurrently. Use to check progress or diagnose a stuck run.
---

Report status for `$ARGUMENTS`. This skill only reads the store. `DB` below is the feature's store:
`<git-common-dir>/gbuild/<feature>/db`, beside the feature worktree `FT` at
`<git-common-dir>/gbuild/<feature>/tree` — machine-local, never committed (a gbuild ≤ 0.7.1 store needs the
move in `reference/cypher.md`). Status never creates or attaches worktrees — if the store is missing,
the feature is gone (or was never charted here); say so.

## Store rules

- `cypherlite --version` first. If it's missing, stop: gbuild needs it
  (`curl -sSfL https://neo4j-labs.github.io/cypherlite/install.sh | bash`).
- One `cypherlite` command at a time — never parallel tool calls on the same store.
- Always `--read-only`: status never writes, and a missing store fails fast instead of being created.
- Always `--mode jsonl`: one JSON object per row, no output = no rows.
- `storage locked` → another process (likely a running `/gbuild:run`) holds the store: wait a few
  seconds, retry up to 3 times, then say so. Anything else: `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`.

## Mode

| arguments         | mode                                  |
| ------------------ | -------------------------------------- |
| empty              | every feature store                    |
| a feature slug     | that feature only                      |

## Single feature

This is the human-facing report, so it's the one place that reads every node.

### 1. Load

```
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/status.cypher
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/validate.cypher
```

One call after the other. `status.cypher` gives one row per node with its derived `state`
(`frontier` / `blocked` / `in_progress` / `completed` / `cancelled` / `failed`), `wave`, `waiting_on`,
review summary and timestamps — don't re-derive any of these by hand.

### 2. Render the graph

Draw the DAG with a marker per node state:

```
✓ completed   ◐ in_progress   ○ frontier   ● blocked   ✗ failed   – cancelled
```

Annotate blocked nodes with what they're waiting on (`waiting_on`):
`● d-join-and-sum ← b-consume-doubled, c-consume-squared`.

Group by `wave` so fan-out is visible in the layout, not just in the dependency list.

### 3. Review verdicts

For every `completed` node, one line: passed outright (`review_attempts: 1`), or passed after N repair
attempts. For `failed` nodes, `last_failed_criteria` verbatim — this is what a human needs to make the
`escalate`/`stop` call.

### 4. Concurrency evidence

`run` schedules as dataflow: a node is claimed the moment its last dependency completes, not when its
wave does. Nodes sharing a `wave` need not overlap — a short chain can finish before a slow node beside
it — so don't judge by overlap; check dispatch timing instead. One more read:

```
cypherlite query "MATCH (n:GbuildNode)-[:DEPENDS_ON]->(d:GbuildNode {status: 'completed'}) WHERE n.started_at IS NOT NULL RETURN n.slug AS slug, n.started_at AS started_at, max(d.completed_at) AS last_dependency_at ORDER BY slug LIMIT 100" --read-only --database DB --mode jsonl
```

For each row, report the gap from `last_dependency_at` (the `completed_at` of its last dependency) to
the node's `started_at`. A few minutes is the dependency's review, merge and record — dataflow working.
A much longer gap, e.g. a start that waited for an unrelated slower node to complete, means the node sat
ready while something else held it back (`run` driven wave by wave, or a lost completion notification)
— a bug in how `run` was driven, not a graph problem. A node with repair attempts (`review_attempts` >
1) started late by design: its times are the passing attempt's. Nodes with no dependencies should have
started together at the beginning of the run.

### 5. Next action

One priority-ordered list: what `/gbuild:run <feature>` would do next (the current frontier), and
anything needing a human decision first (`failed` nodes, an empty frontier with incomplete nodes
remaining, `in_progress` nodes when no run is active — interrupted work `run` will reset).

### 6. Invariant checks

`validate.cypher` is the invariant check — it covers non-empty acceptance, acceptance coverage,
acyclicity, completed nodes without a passing review or missing an output value, orphan chores, and the
`FROM` cut test. Report every row it returned, numbered. If it returned nothing, say so in one line —
don't let silence be ambiguous between "checked, clear" and "not checked."

## All-features mode

Don't read every node of every feature. For each store found — `<git-common-dir>/gbuild/*/db` — one
store at a time:

```
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher
```

Print one line per feature: slug, node counts by state summed over its waves, and whether it's done
(every `open` empty), has ready work (`frontier` > 0), or is stuck. Point at `/gbuild:status <slug>` for
detail.
