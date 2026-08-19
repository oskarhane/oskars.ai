# `graph.json` — normative format

This file is normative. Where a skill disagrees with this doc, this doc wins.

One file per feature: `.gbuild/<feature>/graph.json`, written once by `plan`, read-only during `run`.
JSON, not YAML — `scripts/graph.py` is stdlib-only and Python's stdlib has no YAML parser. Comments are
lost; that's fine, the file is agent-authored, not hand-typed. `/gbuild:status` is the human-facing view.

## Top level

```jsonc
{
  "feature": "gbuild-mvp",                 // slug, matches the .gbuild/<feature>/ dir
  "destination": "<one line — what \"done\" looks like>",
  "context": "<why this exists, one or two lines>",
  "out_of_scope": ["<bullet>"],
  "acceptance": [{ "id": "a-1", "text": "<bullet>" }],  // global, feature-level bar
  "nodes": [ /* see below */ ]
}
```

Keep `destination`/`context`/`out_of_scope`/`acceptance` short — bullets, not paragraphs. Detail lives
on the node, not here. Same discipline as hone's 150-line `spec.md` budget, for the same reason: this
block gets re-read every invocation.

## Node

```jsonc
{
  "id": "01-scan-existing-runners",          // filename-safe, immutable once created
  "title": "<string>",
  "type": "research | decision | code | test | verify | chore",
  "dependencies": ["<node id>"],              // real data/order dependency ONLY — see cut test below
  "contract": {
    "input": {},                              // what this node reads, structured not prose
    "output": {}                              // what this node produces, structured not prose
  },
  "satisfies": ["a-1"],                       // which global acceptance ids this node serves
  "acceptance": [
    "<concrete, checkable-by-a-fresh-context criterion>"
  ],
  "verify": null,                             // id of an *additional* verify-type node, or null
  "failure_policy": "retry | fallback | skip | repair | escalate | stop",
  "model_tier": "cheap | strong"
}
```

### The cut test

Before adding an edge `B -> depends on -> A`, ask: does B actually read something A produced? If B
would run exactly the same way with A deleted, it's not a dependency — it's just the order you thought
of them in. Sequence ≠ dependency. Nodes with no real edge between them belong in the same wave, not a
chain.

### `acceptance` is mandatory and must be concrete

`graph.py` rejects the file if any node has an empty or all-blank `acceptance` list (same rule as
hone's invariant: every build task has ≥1 acceptance criterion). Concrete means checkable by a fresh
context with no other information — not `"looks correct"` or `"works well"`. Prefer criteria that name
a file, a command's exit code, a specific behavior, or a literal output shape.

### `verify` is not the review

Every node — regardless of `type` — goes through `gbuild-reviewer` before it's checkpointed complete
(see `agents/gbuild-reviewer.md`). `verify` is for something *beyond* that default: a dedicated
fact-checker, an adversarial multi-vote, a human-approval gate. Most nodes have `verify: null` and are
still reviewed.

### `type`

| type       | produces                                                              |
| ---------- | ---------------------------------------------------------------------- |
| `research` | findings — an answer to a question, cited                             |
| `decision` | a choice made and recorded, with the alternatives it ruled out         |
| `code`     | a coherent, reviewable change, committed                               |
| `test`     | coverage for behavior a `code` node landed, when genuinely separable  |
| `verify`   | a check on another node's output — never the same agent, never self  |
| `chore`    | mechanical work with no behavior change                                |

### `failure_policy`

See `reference/failure-policies.md` for how `run` applies each value.

### `model_tier`

See `reference/cost-model.md` for the cheap/strong split and when a cluster should collapse to one agent.

## State (not part of `graph.json`)

`.gbuild/<feature>/nodes/<id>.json`, one file per node, written by `run`:

```jsonc
{
  "status": "pending | in_progress | completed | failed | cancelled",
  "output": {},              // matches the node's contract.output shape
  "review": {
    "verdict": "pass | fail",
    "acceptance_results": [{ "criterion": "<text>", "passed": true }]
  },
  "started_at": "<ISO8601>",
  "completed_at": "<ISO8601>"
}
```

A missing checkpoint file means `pending`. Each node owns its own file, so parallel writers never
collide.

## Derived queries

Nothing here is stored twice — `scripts/graph.py` computes all of it:

```
frontier  = status pending ∧ every dependency completed-or-cancelled
blocked   = status pending ∧ some dependency not completed-or-cancelled
in_flight = status in_progress
waves     = topological layering — wave N holds every node whose deps all resolved in wave < N
```

A `cancelled` dependency counts as satisfied — cancelling a node must not permanently block its
dependents.
