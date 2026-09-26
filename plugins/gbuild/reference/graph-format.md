# `graph.json` — normative format

This file is normative. Where a skill disagrees with this doc, this doc wins.

One file per feature: `.gbuild/<feature>/db/graph.json`, written once by `plan`, read-only during `run`.

**`graph.json` is a CypherLite GraphData file.** It lives alone in its own `db/` folder so CypherLite can open that folder as a database and query it with Cypher — CypherLite opens a *directory* holding `graph.json`, not a bare `.json` file:

```
cypherlite .gbuild/<feature>/db "MATCH (n:GbuildNode) RETURN n.slug, n.type"
```

The `db/` folder contains `graph.json` and nothing else that CypherLite cares about. Checkpoints live in the sibling `.gbuild/<feature>/nodes/` directory (see [State](#state-not-part-of-graphjson)) — deliberately *outside* `db/`, because CypherLite reads a directory named `nodes` as Parquet shards and would reject the store as "mixed snapshot codecs". Opening `db/` also makes CypherLite create a `db/wal/` directory; that is expected. **Only run read-only `MATCH … RETURN` Cypher against the plan** — a writing query could checkpoint and rewrite the write-once `graph.json`.

### Interoperability with CypherLite

`graph.json` is the *same* JSON snapshot CypherLite reads and writes — there is one store file, not a gbuild copy and a CypherLite copy. Two consequences:

- **The store must be the JSON codec.** gbuild always writes `graph.json`, so the store is JSON by construction. A Parquet store directory is not readable by gbuild's stdlib parsers.
- **A CypherLite checkpoint normalizes the file.** If a writing Cypher command is followed by `.checkpoint` (or the WAL rotates), CypherLite rewrites `graph.json` in full — adding `value_encoding` — and leaves `manifest.json` and `wal/` beside it. gbuild's parsers read only `nodes` / `relationships` / `next_node_id` / `next_rel_id` and ignore the rest, so the checkpointed snapshot remains valid and queryable by `graph.py` / `validate_format.py` unchanged.

CypherLite can *read* every property gbuild writes, including the `contract` map. It cannot **write** map property values via Cypher (`InvalidPropertyType`), so a node authored purely through Cypher cannot carry `contract` today — direct JSON authoring remains the way `plan` writes it.

JSON, not YAML — `scripts/graph.py` and `scripts/validate_format.py` are stdlib-only and Python's stdlib has no YAML parser. Comments are lost; that's fine, the file is agent-authored, not hand-typed. `/gbuild:status` is the human-facing view.

**Validate after every change.** `scripts/validate_format.py <path>` is the format gate — run it after the initial write, after any reopen edit, after any hand-edit, before doing anything else with the file (including committing). It exits 0 + `valid: <feature>` on success, 1 + every error joined on failure. Fix the file and re-run until it passes; never hand off or run an invalid graph.

The validator does its stdlib JSON checks always. If the `cypherlite` binary is on PATH, it *also* opens the file with CypherLite and runs a trivial `MATCH` — confirming CypherLite itself loads it, not just that the stdlib walk approves the shape. CypherLite is an optional consumer, not a dependency: if the binary is absent the cross-check is skipped silently (`--no-cypherlite` forces the skip too).

## Top level — the GraphData envelope

```jsonc
{
  "nodes": [ /* Feature, Acceptance, GbuildNode — see below */ ],
  "relationships": [ /* DEPENDS_ON, HAS_ACCEPTANCE, SATISFIES */ ],
  "indexes": [],
  "constraints": [],
  "next_node_id": 8,   // max(node.id) + 1 (1 if empty) — CypherLite trusts this
  "next_rel_id": 10    // max(rel.id) + 1 (1 if empty)
}
```

`indexes` and `constraints` are empty for gbuild graphs — kept only because CypherLite's loader expects them. `next_node_id`/`next_rel_id` are the id allocator counters; they must equal `max(id)+1` for each kind, and the validator enforces this.

## Node labels

Three node kinds, distinguished by label:

| label        | meaning                                  | count per graph |
| ------------ | ---------------------------------------- | --------------- |
| `Feature`    | the one feature this graph is for         | exactly 1       |
| `Acceptance` | one feature-level acceptance bullet        | one per bullet  |
| `GbuildNode` | one unit of work in the dependency graph   | one per node    |

### `Feature` node (id 1)

```jsonc
{
  "id": 1,
  "labels": ["Feature"],
  "properties": {
    "feature": "gbuild-mvp",                 // slug, matches the .gbuild/<feature>/ dir
    "destination": "<one line — what \"done\" looks like>",
    "context": "<why this exists, one or two lines>",
    "out_of_scope": ["<bullet>"]
  }
}
```

Keep `destination`/`context`/`out_of_scope` short — bullets, not paragraphs. Detail lives on the nodes, not here. Same discipline as hone's 150-line `spec.md` budget, for the same reason: this block gets re-read every invocation. **Do not put an `acceptance` property here** — feature-level acceptance lives in `Acceptance` nodes.

### `Acceptance` nodes

One per feature-level acceptance bullet:

```jsonc
{
  "id": 2,
  "labels": ["Acceptance"],
  "properties": { "id": "a-1", "text": "<bullet>" }
}
```

Each is linked `Feature -[:HAS_ACCEPTANCE]-> Acceptance`. A node that serves a criterion gets `GbuildNode -[:SATISFIES]-> Acceptance` (see below). Normalizing the bar into nodes makes it queryable on its own and joinable to the nodes that cover it.

### `GbuildNode` — a unit of work

```jsonc
{
  "id": 4,
  "labels": ["GbuildNode", "Code"],        // PascalCase type label, always alongside GbuildNode
  "properties": {
    "slug": "01-scan-existing-runners",      // filename-safe kebab-case, immutable, the stable identity
    "title": "<string>",
    "type": "code",                          // lowercase enum — kept as a property too (matches the label)
    "contract": { "input": {}, "output": {} },  // structured shapes, not prose
    "acceptance": [                          // node-level local criteria (mandatory, concrete)
      "<concrete, checkable-by-a-fresh-context criterion>"
    ],
    "verify": null,                          // slug of an *additional* verify-type node, or null
    "failure_policy": "retry | fallback | skip | repair | escalate | stop",
    "model_tier": "cheap | strong"
  }
}
```

- `id` — integer, sequential, unique, never reused even if a node is removed. Authoring convenience, not semantic identity — `slug` is the stable identity skills and checkpoints key on.
- `labels` — `["GbuildNode", <PascalCase type>]`. The universal `GbuildNode` label is for `MATCH (n:GbuildNode)`; the type label (`Research`, `Decision`, `Code`, `Test`, `Verify`, `Chore`) enables `MATCH (n:Code)`.
- `slug` — the human/inter-skill identifier. Checkpoint files are named `<slug>.json`; skills refer to nodes by slug in anything the user reads. Immutable once created.
- `type` — lowercase enum, duplicated as a property alongside the PascalCase label so `n.type` works for sort/filter and survives any label-casing edge. The validator checks the label matches the type.
- `contract.input` / `contract.output` — structured shapes, not prose. A downstream node's `input` should reference an upstream node's `output` field directly (by slug path in the doc string, e.g. `"<integer, from a-produce-shared-value.output.value>"`).
- `acceptance` — **mandatory, non-empty, concrete.** The validator rejects empty or all-blank lists. Concrete means checkable by a fresh context with no other information — not `"looks correct"` or `"works well"`.
- `verify` — only set when this node needs something *beyond* the standard `gbuild-reviewer` pass. Usually `null`.
- **no `satisfies` property** — which global acceptance ids this node serves is expressed as `SATISFIES` edges, not an array. The validator rejects a stray `satisfies` property.

### The cut test

Before adding an edge `B -[:DEPENDS_ON]-> A`, ask: does B actually read something A produced? If B would run exactly the same way with A deleted, it's not a dependency — it's just the order you thought of them in. Sequence ≠ dependency. Nodes with no real edge between them belong in the same wave, not a chain.

### `acceptance` is mandatory and must be concrete

`validate_format.py` rejects the file if any GbuildNode has an empty or all-blank `acceptance` list (same rule as hone's invariant: every build task has ≥1 acceptance criterion). Concrete means checkable by a fresh context with no other information — not `"looks correct"` or `"works well"`. Prefer criteria that name a file, a command's exit code, a specific behavior, or a literal output shape.

### `verify` is not the review

Every node — regardless of `type` — goes through `gbuild-reviewer` before it's checkpointed complete (see `agents/gbuild-reviewer.md`). `verify` is for something *beyond* that default: a dedicated fact-checker, an adversarial multi-vote, a human-approval gate. Most nodes have `verify: null` and are still reviewed.

### `type`

| type       | label      | produces                                                              |
| ---------- | ---------- | -------------------------------------------------------------------- |
| `research` | `Research` | findings — an answer to a question, cited                             |
| `decision` | `Decision` | a choice made and recorded, with the alternatives it ruled out         |
| `code`     | `Code`     | a coherent, reviewable change, committed                               |
| `test`     | `Test`     | coverage for behavior a `code` node landed, when genuinely separable  |
| `verify`   | `Verify`   | a check on another node's output — never the same agent, never self  |
| `chore`    | `Chore`    | mechanical work with no behavior change                                |

### `failure_policy`

See `reference/failure-policies.md` for how `run` applies each value.

### `model_tier`

See `reference/cost-model.md` for the cheap/strong split and when a cluster should collapse to one agent.

## Relationships

Three types. Each gets a sequential integer `id` (never reused), `start_node`/`end_node` reference node ids, `properties` is an object (empty for all gbuild edges today).

### `DEPENDS_ON` — the dependency edge

```jsonc
{ "id": 6, "type": "DEPENDS_ON", "start_node": 5, "end_node": 4, "properties": {} }
```

Direction: **dependent → dependency** (`start_node` depends on `end_node`). So `MATCH (n)-[:DEPENDS_ON]->(d)` is "what does n need", and `MATCH (n)<-[:DEPENDS_ON]-(d)` is "what waits on n". Both endpoints must be `GbuildNode`s — you can't depend on the Feature or an Acceptance. The `DEPENDS_ON` graph must be acyclic (validator enforces).

### `HAS_ACCEPTANCE` — feature → acceptance

```jsonc
{ "id": 1, "type": "HAS_ACCEPTANCE", "start_node": 1, "end_node": 2, "properties": {} }
```

Ties each `Acceptance` node to its `Feature`. `start_node` must be the Feature node, `end_node` an Acceptance node. One per acceptance bullet.

### `SATISFIES` — node → acceptance

```jsonc
{ "id": 3, "type": "SATISFIES", "start_node": 5, "end_node": 2, "properties": {} }
```

Ties a `GbuildNode` to a feature-level criterion it covers (replaces the old `satisfies` array property). `start_node` a GbuildNode, `end_node` an Acceptance. Every `Acceptance` must be the target of at least one `SATISFIES` — an uncovered criterion means a node is missing (validator enforces).

## ID authoring rules

- The skill authors integer ids directly in the file, sequential: `Feature` = 1, then `Acceptance` nodes, then `GbuildNode`s in any stable order. Relationship ids are sequential across all three types.
- `next_node_id` / `next_rel_id` must equal `max(id)+1` for each kind (or 1 if empty). The validator enforces this because CypherLite trusts these counters on load — a stale counter can collide with a live id.
- Never reuse an id, even if a node is removed. Slugs are the stable identity; ids are authoring convenience.
- On reopen: append new `Acceptance`/`GbuildNode` nodes with the next available ids, add their edges, bump the counters, then re-run `validate_format.py`.

## State (not part of `graph.json`)

`.gbuild/<feature>/nodes/<slug>.json`, one file per GbuildNode, written by `run`:

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

A missing checkpoint file means `pending`. Each node owns its own file, so parallel writers never collide. Checkpoints stay as sidecar files by design: `graph.json` is write-once (plan), checkpoints are write-many (run), and only the plan needs to be CypherLite-queryable. Runtime status is joined in by `graph.py --status`, not stored in the graph.

## Derived queries

`scripts/graph.py` computes all of this (joining the GraphData plan with the sidecar checkpoints):

```
frontier  = status pending ∧ every DEPENDS_ON target completed-or-cancelled
blocked   = status pending ∧ some DEPENDS_ON target not completed-or-cancelled
in_flight = status in_progress
waves     = topological layering — wave N holds every node whose deps all resolved in wave < N
```

A `cancelled` dependency counts as satisfied — cancelling a node must not permanently block its dependents.

## Querying with Cypher

Because `graph.json` is a CypherLite GraphData file, the *plan structure* is queryable directly with Cypher (no conversion). Runtime status is not — it lives in sidecar checkpoint files, so `frontier`/`blocked`/`completed` come from `graph.py --status`, not pure Cypher. Dependency-derived questions are pure Cypher:

```cypher
-- the whole plan
MATCH (n:GbuildNode) RETURN n.slug, n.type, n.title

-- nodes by type
MATCH (n:Code) RETURN n.slug, n.title

-- what does node d depend on (direct)
MATCH (n {slug:'d-join-and-sum'})-[:DEPENDS_ON]->(d) RETURN d.slug

-- full transitive dependency chain
MATCH (n {slug:'d-join-and-sum'})-[:DEPENDS_ON*]->(d) RETURN DISTINCT d.slug

-- what waits on a given node
MATCH (n)<-[:DEPENDS_ON]-(dependent) WHERE n.slug='a-produce-shared-value' RETURN dependent.slug

-- nodes with no dependencies (first wave / roots)
MATCH (n:GbuildNode) WHERE NOT (n)-[:DEPENDS_ON]->() RETURN n.slug

-- nodes nobody depends on (final joins / leaves)
MATCH (n:GbuildNode) WHERE NOT ()-[:DEPENDS_ON]->(n) RETURN n.slug

-- critical path (longest dependency chain)
MATCH p=(n:GbuildNode)-[:DEPENDS_ON*]->(m:GbuildNode) RETURN length(p) AS d, p ORDER BY d DESC LIMIT 1

-- feature-level bar
MATCH (f:Feature)-[:HAS_ACCEPTANCE]->(a:Acceptance) RETURN a.id, a.text

-- which nodes cover each criterion
MATCH (a:Acceptance)<-[:SATISFIES]-(n:GbuildNode) RETURN a.id, n.slug

-- uncovered criteria (a node is missing)
MATCH (a:Acceptance) WHERE NOT ()-[:SATISFIES]->(a) RETURN a.id, a.text
```
