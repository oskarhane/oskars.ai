---
description: Reports a gbuild feature's graph — frontier, blocked, in-flight, completed, each node's review verdict, and the cluster shapes with evidence of what actually ran concurrently. Use to check progress or diagnose a stuck run.
---

Report status for `$ARGUMENTS`. This skill only reads the store; `DB` below is `.gbuild/<feature>/db`.

## Store rules

- `cypherlite --version` first. If it's missing, stop: gbuild needs it
  (`curl -sSfL https://neo4j-labs.github.io/cypherlite/install.sh | bash`).
- One `cypherlite` command at a time — never parallel tool calls on the same store.
- Always `--mode jsonl`: one JSON object per row, no output = no rows.
- `storage locked` → another process (likely a running `/gbuild:run`) holds the store: wait a few
  seconds, retry up to 3 times, then say so. Anything else: `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`.

## Mode

| arguments         | mode                                  |
| ------------------ | -------------------------------------- |
| empty              | every feature under `.gbuild/`         |
| a feature slug     | that feature only                      |

## Single feature

This is the human-facing report, so it's the one place that reads every node.

### 1. Load

```
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/status.cypher
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/validate.cypher
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

For each wave with more than one completed node, compare the implementing agents' `started_at` /
`completed_at` intervals. Report whether they actually overlapped (real concurrent dispatch) or ran
back-to-back despite being in the same wave (a sign the fallback backend was invoked one node at a time —
a bug in how `run` was driven, not a graph problem).

### 5. Next action

One priority-ordered list: what `/gbuild:run <feature>` would do next (the current frontier), and
anything needing a human decision first (`failed` nodes, an empty frontier with incomplete nodes
remaining, `in_progress` nodes when no run is active — an interrupted wave `run` will reset).

### 6. Invariant checks

`validate.cypher` is the invariant check — it covers non-empty acceptance, acceptance coverage,
acyclicity, completed nodes without a passing review or missing an output value, orphan chores, and the
`FROM` cut test. Report every row it returned, numbered. If it returned nothing, say so in one line —
don't let silence be ambiguous between "checked, clear" and "not checked."

## All-features mode

Don't read every node of every feature. For each `.gbuild/<slug>/db` found, one store at a time:

```
cypherlite .gbuild/<slug>/db --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher
```

Print one line per feature: slug, node counts by state summed over its waves, and whether it's done
(every `open` empty), has ready work (`frontier` > 0), or is stuck. Point at `/gbuild:status <slug>` for
detail.
