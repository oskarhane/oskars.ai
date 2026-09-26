# gbuild graph model — normative

This file is normative. Where a skill disagrees with this doc, this doc wins.

One CypherLite store per feature: `.gbuild/<feature>/db/`. `plan` creates and charts it, `run` records
progress in it, and every skill reads it — **all through Cypher**. No skill reads or writes `graph.json`
directly; it is CypherLite's snapshot of the store. How to talk to the store (the single-writer rule,
invocation, quoting, the script catalog) is in `reference/cypher.md`.

`templates/example.cypher` is a complete worked example — a 4-node diamond — written exactly the way
`plan` writes a new feature.

## Store layout

```
.gbuild/<feature>/db/
  graph.json          CypherLite JSON snapshot — committed; always current (every write ends with .checkpoint)
  .gitignore          "*", "!.gitignore", "!graph.json" — committed
  manifest.json       engine files — ignored
  wal/
  .cypherlite.lock
```

The store is created with the JSON codec (`--snapshot-format json`, see `reference/cypher.md`) so
`graph.json` diffs are reviewable in a PR, and a clone holding only `graph.json` is a complete store —
data **and** constraints.

## Nodes

| label        | meaning                                            | count             |
| ------------ | -------------------------------------------------- | ----------------- |
| `Feature`    | the one feature this store is for                  | exactly 1         |
| `Acceptance` | one feature-level acceptance bullet                | one per bullet    |
| `GbuildNode` | one unit of work (always with a PascalCase type label) | one per node  |
| `Field`      | one named input or output of a GbuildNode's contract | one per field   |
| `Review`     | one `gbuild-reviewer` verdict on a GbuildNode      | one per review attempt |

### `Feature`

| property       | type           | meaning                                              |
| -------------- | -------------- | ---------------------------------------------------- |
| `feature`      | string         | the slug — matches the `.gbuild/<feature>/` dir, immutable |
| `destination`  | string         | one line: what is true once this is done             |
| `context`      | string         | why this exists, one or two lines                    |
| `out_of_scope` | list of string | bullets, may be empty                                |

Keep these short — bullets, not paragraphs. Detail lives on the nodes. There is no `acceptance` property:
the feature-level bar is `Acceptance` nodes.

### `Acceptance`

`id` (string, `a-1`, `a-2`, …, unique) and `text` (string, non-blank). Each is linked
`(:Feature)-[:HAS_ACCEPTANCE]->(:Acceptance)` and covered by at least one
`(:GbuildNode)-[:SATISFIES]->(:Acceptance)`.

### `GbuildNode` — a unit of work

Labels: `GbuildNode` plus exactly one type label matching `type` — `(:GbuildNode:Code {...})`. The
universal label is for `MATCH (n:GbuildNode)`; the type label enables `MATCH (n:Code)`.

| property         | type           | meaning                                                        |
| ---------------- | -------------- | -------------------------------------------------------------- |
| `slug`           | string         | kebab-case, unique, immutable — the identity every skill keys on |
| `title`          | string         | what the user reads; refer to nodes by title in conversation    |
| `type`           | string         | `research \| decision \| code \| test \| verify \| chore`       |
| `acceptance`     | list of string | node-level criteria — mandatory, non-empty, concrete            |
| `verify`         | string, optional | slug of an *additional* verify-type node; usually absent      |
| `failure_policy` | string         | `retry \| fallback \| skip \| repair \| escalate \| stop` — `reference/failure-policies.md` |
| `model_tier`     | string         | `cheap \| strong` — `reference/cost-model.md`                   |
| `status`         | string         | `pending` at creation — see [Status lifecycle](#status-lifecycle) |
| `started_at`     | string, optional | implementing agent's own UTC start time, set on completion    |
| `completed_at`   | string, optional | implementing agent's own UTC finish time, set on completion   |

The contract is not a property — it is the node's `Field`s (below). Which feature criteria the node
serves is `SATISFIES` edges, not a property.

| type       | label      | produces                                                              |
| ---------- | ---------- | -------------------------------------------------------------------- |
| `research` | `Research` | findings — an answer to a question, cited                             |
| `decision` | `Decision` | a choice made and recorded, with the alternatives it ruled out         |
| `code`     | `Code`     | a coherent, reviewable change, committed                               |
| `test`     | `Test`     | coverage for behavior a `code` node landed, when genuinely separable  |
| `verify`   | `Verify`   | a check on another node's output — never the same agent, never self  |
| `chore`    | `Chore`    | mechanical work with no behavior change                                |

**`acceptance` must be concrete** — checkable by a fresh context with no other information. Not
"looks correct" or "works well": name a file, a command's exit code, a specific behavior, or a literal
output value.

**`verify` is not the review.** Every node goes through `gbuild-reviewer` before it can be completed
(`agents/gbuild-reviewer.md`). `verify` is for something *beyond* that: a fact-checker, an adversarial
multi-vote, a human-approval gate.

### `Field` — one contract field

| property | type   | meaning                                                                 |
| -------- | ------ | ----------------------------------------------------------------------- |
| `name`   | string | unique per node and direction                                            |
| `shape`  | string | what the value is — `<integer>`, `<list of changed file paths>`, `<commit sha>` |
| `value`  | scalar or list of scalars, optional | outputs only — recorded when the node completes |

Output values must be scalars (string, number, boolean) or lists of scalars; CypherLite cannot store a
map as a property value. JSON-encode anything nested into a string and say so in `shape`.

### `Review` — one reviewer verdict

`attempt` (integer, 1-based, assigned by `record.cypher`), `verdict` (`pass | fail`),
`failed_criteria` (list of the acceptance criteria the reviewer failed; empty on a pass), `at` (string).
Reviews are never updated or deleted — the repair history stays visible to `status`.

## Relationships

| type             | from → to                  | meaning                                           |
| ---------------- | -------------------------- | ------------------------------------------------- |
| `HAS_ACCEPTANCE` | `Feature` → `Acceptance`   | the criterion belongs to the feature              |
| `SATISFIES`      | `GbuildNode` → `Acceptance`| the node covers the criterion                     |
| `DEPENDS_ON`     | `GbuildNode` → `GbuildNode`| dependent → dependency; must be acyclic           |
| `INPUT`          | `GbuildNode` → `Field`     | the node reads this field                         |
| `OUTPUT`         | `GbuildNode` → `Field`     | the node produces this field                      |
| `FROM`           | `Field` → `Field`          | an input field reads an upstream node's output field |
| `REVIEWED`       | `GbuildNode` → `Review`    | a verdict on the node                             |

No other edge shapes are valid. `MATCH (n)-[:DEPENDS_ON]->(d)` is "what does n need";
`MATCH (n)<-[:DEPENDS_ON]-(d)` is "what waits on n".

### The contract: `INPUT`, `OUTPUT`, `FROM`

A node's contract is its fields. Every node declares at least one `OUTPUT` — a node that produces
nothing structured gives `gbuild-reviewer` nothing to check. An `INPUT` field with a `FROM` edge reads
that upstream output: when the upstream completes, the value flows to the consumer through the edge
(`node.cypher` resolves it). An `INPUT` without `FROM` is external — the codebase, the environment, the
user — and its `shape` says where it comes from.

```cypher
(b:GbuildNode)-[:DEPENDS_ON]->(a:GbuildNode)
(a)-[:OUTPUT]->(v:Field {name: 'value', shape: '<integer>'})
(b)-[:INPUT]->(:Field {name: 'value', shape: '<integer>'})-[:FROM]->(v)
```

### The cut test, machine-checked

Before adding `B -[:DEPENDS_ON]-> A`, ask: does B actually read something A produced? If B would run
exactly the same way with A deleted, it is not a dependency — it is the order you thought of them in.
Sequence ≠ dependency; nodes with no real edge between them belong in the same wave, not a chain.

In this model the question has a checkable answer, and `validate.cypher` enforces both directions:

- every `DEPENDS_ON` carries at least one `FROM` from B's inputs to A's outputs — no edge without data
  (`dependency-without-from`);
- every `FROM` points at an output of a node B `DEPENDS_ON` — no data without an edge
  (`from-without-dependency`).

## Status lifecycle

`status` is stored on the node; `frontier` and `blocked` are derived by `status.cypher`, never stored.

```
pending ──dispatch──▶ in_progress ──record (pass)──▶ completed
                          │
                          ├──set-status──▶ failed      (escalate, exhausted retry/repair, stop)
                          └──set-status──▶ cancelled   (skip)

frontier = pending ∧ every DEPENDS_ON target completed-or-cancelled
blocked  = pending ∧ some DEPENDS_ON target not completed-or-cancelled
```

A `cancelled` dependency counts as satisfied — abandoning an optional node must not wedge its
dependents. A `failed` one does not — dependents stay blocked rather than build on a broken foundation.
`completed` can only be set by `record.cypher`, and only for an `in_progress` node whose review passed
with a value for every `OUTPUT` — a pass missing outputs is recorded as a failed review naming them.

## Who enforces what

| layer                     | enforces                                                                 |
| ------------------------- | ------------------------------------------------------------------------ |
| engine constraints (`cypher/schema.cypher`) | required properties and their types; unique `slug` and `Acceptance.id` — a violating write never lands |
| `cypher/validate.cypher`  | exactly one `Feature`; enums; type label matches `type`; non-blank acceptance; `verify` target exists; acceptance linked and covered; allowed edge shapes only; acyclic `DEPENDS_ON`; every chore depended on; every node has an output; field ownership and uniqueness; the `FROM` cut test; completed nodes have a passing review and all output values |
| write scripts (`cypher/*.cypher`) | `dispatch` claims only frontier nodes; `record` completes a node only on a pass with every output; `set-status` never sets `completed` |

## Querying

The plan and its progress are one graph, so any question is a Cypher query. The plugin scripts cover
what the skills need (`reference/cypher.md` § Script catalog); ready-made ad-hoc queries are in
`reference/queries.md`.
