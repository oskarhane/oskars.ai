# Cost model

`plan` sets `model_tier` per node. `run` uses it to route model choice when the backend supports it
(the `Workflow` tool's `agent()` `model` option); the Agent-tool fallback treats it as a hint in the
dispatched agent's prompt when the harness offers a model choice, and otherwise ignores it — it is
never load-bearing for correctness, only cost.

## `cheap`

Default. Use for:

- `chore` nodes — mechanical, no judgement call.
- `test` nodes covering already-specified behavior.
- `code` nodes with a narrow, well-specified contract and concrete acceptance criteria (the review pass
  is what catches a cheap model's mistakes, not the model tier).
- `gbuild-reviewer` passes against short, mechanical acceptance lists.

## `strong`

Reserve for:

- `decision` nodes — the thing being bought is judgement, not throughput.
- `research` nodes where the answer requires synthesizing several sources, not just one lookup.
- `code` nodes whose contract is underspecified or whose acceptance criteria require judgement to
  evaluate (if a node needs `strong` for this reason, consider whether `plan` should have written
  tighter acceptance criteria instead).
- `verify` nodes doing adversarial or fact-checking work beyond the standard review.

## Review tiers

`plan` sets `review` per node (optional — unset means `reviewer`); `run` routes the gate on it.

- `reviewer` — the default. A fresh `gbuild-reviewer` grades the node: outputs against the contract,
  acceptance bullet by bullet, duplication, and the bar as a ceiling. Choose it whenever judging the
  output takes judgement — `code` nodes with any subtlety, `research`/`decision` nodes whose
  conclusions downstream nodes build on, anything whose acceptance a command can't fully prove.
- `mechanical` — no reviewer agent: `run` records the node on `check-result.cypher` alone (every
  output present and shape-valid), and the implementer's own green run of what the acceptance names
  is the correctness gate. A bad output surfaces when its consumer breaks, or in the end-of-feature
  audit. Choose it only where the acceptance is itself mechanical — a scoped command's exit status, a
  file's presence, a value's shape: most `chore` and `test` nodes, narrow lookups, and `code` nodes
  whose whole bar one scoped test run proves. If you can't name the command that proves the node, it
  isn't mechanical.

The tier is a trust decision `plan` owns, like `model_tier` and `failure_policy`: a graph that marks
everything `mechanical` has no gate but the audit; one that marks everything `reviewer` pays a
reviewer per node. Both errors are planning failures.

## Collapsing a cluster to one agent

When a wave's nodes are all `cheap`, tightly scoped, and small enough that one context could hold all
of them without losing precision, `plan` may note in the cluster's shape that `run` can dispatch them
as one agent handling the whole wave sequentially, rather than N concurrent agents — trading real
parallelism for lower overhead when the nodes are too small to be worth splitting. This is judgement
`plan` exercises at authoring time, not something `run` decides on its own; a wave `plan` didn't flag
this way is dispatched as one agent per node, per the default in `skills/run/SKILL.md`.

Never collapse nodes with different `failure_policy` values, or where any node in the cluster is
`strong` — those need to be dispatched (and possibly retried/repaired) independently.
