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

## Collapsing a cluster to one agent

When a wave's nodes are all `cheap`, tightly scoped, and small enough that one context could hold all
of them without losing precision, `plan` may note in the cluster's shape that `run` can dispatch them
as one agent handling the whole wave sequentially, rather than N concurrent agents — trading real
parallelism for lower overhead when the nodes are too small to be worth splitting. This is judgement
`plan` exercises at authoring time, not something `run` decides on its own; a wave `plan` didn't flag
this way is dispatched as one agent per node, per the default in `skills/run/SKILL.md`.

Never collapse nodes with different `failure_policy` values, or where any node in the cluster is
`strong` — those need to be dispatched (and possibly retried/repaired) independently.
