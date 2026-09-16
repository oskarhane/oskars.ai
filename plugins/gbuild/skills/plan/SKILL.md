---
description: Decomposes a feature into a real dependency graph in .gbuild/<feature>/graph.json — nodes with typed contracts, mandatory concrete acceptance criteria, and edges that pass the cut test. Use when starting new gbuild work, before /gbuild:run.
---

Plan the work described in `$ARGUMENTS` as a graph.

## The loop

The intended workflow: plan in ordinary conversation first, then chart that plan here. After this
skill: `/gbuild:run <slug>` once — it iterates waves until the graph completes. Then
`/gbuild:review <slug>`; if it finds issues, reopen with `/gbuild:plan <slug> --add "<fix>"` and
`/gbuild:run` again; if clean, `/gbuild:pr <slug>`.

Read `${CLAUDE_PLUGIN_ROOT}/reference/graph-format.md` before doing anything — it's the normative schema. `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md`,
`${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`, and `${CLAUDE_PLUGIN_ROOT}/reference/cost-model.md` inform the choices below.
`${CLAUDE_PLUGIN_ROOT}/reference/checklist.md` is the self-check at the end.

## Mode

| arguments                                    | mode                    |
| --------------------------------------------- | ----------------------- |
| a description, link, or file path             | **Chart** — new feature |
| an existing feature slug with `--add "<req>"` | **Reopen**              |

A bare slug with no `.gbuild/<slug>/` is a description, not a slug — chart it.

## Chart

### 1. Slug and branch

Derive the feature slug from `$ARGUMENTS`: kebab-case, ≤4 words, names the outcome not the mechanism
(`oauth-device-flow`, not `add-some-auth-stuff`). It's the `.gbuild/<slug>/` directory name and the
`feature` field in `graph.json` — immutable once charted.

Then get onto a branch for it, so `run`'s commits land somewhere isolated:

- Working tree dirty → stop and ask. Don't stash or sweep someone else's changes into your branch.
- Already on a branch ending in `<slug>` → stay there, say so.
- Otherwise `git checkout -b <prefix>/<slug>` from current HEAD. Take `<prefix>` from the repo's
  convention — project or user instructions first, else the dominant pattern in `git branch --list`
  — and fall back to `gbuild` when there is none.

Report the branch. Everything below happens on it.

### 2. Analyse the codebase

Read the project manifest(s), directory structure, `README.md`, and any existing `.gbuild/*/graph.json`
for related in-flight work. Resolve file paths or URLs in `$ARGUMENTS`; if a reference fails to load,
say so and ask.

### 3. Validate and explore

Triage `$ARGUMENTS` against what step 2 found. The point is to catch plans that are wrong *before*
they're charted — not to interrogate every input. If the description is sharp and the scope is
unambiguous, this step is a quick confirmation and you move on.

**Classify the input into one of:**

- **Clear** — names a concrete outcome, scope is unambiguous, no assumption risky enough to
  invalidate the graph if wrong. This is the default when a competent spec lands. Skip to step 4.
  Don't manufacture questions for a plan that already makes sense.
- **Gappy** — missing constraints, ambiguous terms, or a destination that could mean two different
  things. Ask. Batch **all** clarifying questions in one message; cap at ~5. If you need more, the
  input is underspecified — say so and ask the user to rewrite it rather than play 20 questions.
  Fold the answers in, then proceed.
- **Risky** — the plan rests on an assumption that, if wrong, invalidates nodes or edges (a library
  can do X, a data source exists at a given shape, a perf budget holds). Don't just ask about it —
  **resolve** it. Find evidence in the codebase or docs, or chart a prototype (below). State the
  assumption, what's at risk, and how you resolved it. A resolved assumption is a fact the graph
  rests on; an unresolved one is a hole.

**Explore alternatives when the destination doesn't dictate the mechanism.** If two plausible
approaches reach the outcome, name each in one sentence, pick one, say why in one sentence. Skip
the survey when there's only one real way — don't perform thoroughness for its own sake.

**Prototypes are nodes, not side quests.** An unknown that needs code or a probe to resolve becomes
a `research`-typed GbuildNode in the first wave — `plan` charts it, `run` executes it. `plan` does
not run prototypes inline (the "Plan, don't do" rule below). The one exception: a check so cheap it
finishes in a single tool call (grep, read a file, check an installed version) — do that inline and
note the result. A prototype worth charting names the specific question it answers in its
`contract.output`, and its `acceptance` is the answer to that question.

### 4. Name the destination

Ask, one question at a time, until `destination` fits in one line — the thing that's true once this is
done. Do not proceed until it's that sharp; everything past it goes in `out_of_scope`.

### 5. Decompose into nodes, not steps

List the real pieces of work. For each pair, apply the **cut test** (`${CLAUDE_PLUGIN_ROOT}/reference/graph-format.md`):
does one actually read the other's output? If no, they're independent — same wave, not a chain. This is
the step hone-ai v1 skipped, and the whole reason gbuild exists: state the true dependency structure,
don't default to the order you thought of things in.

Classify each cluster's shape per `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md` (chain / diamond / router / controlled cycle).
A controlled cycle needs its round cap and dedup rule decided now, not left to `run` to invent.

The graph is a **CypherLite GraphData file** (see `${CLAUDE_PLUGIN_ROOT}/reference/graph-format.md` — normative). You
write three kinds of nodes and three kinds of relationships:

- **`Feature` node** (id 1) — one per graph, properties `feature` (the slug), `destination`, `context`,
  `out_of_scope` (array). No `acceptance` property here.
- **`Acceptance` nodes** — one per feature-level bullet, properties `id` (`a-1`, `a-2`, …) and `text`.
  Each linked `Feature -[:HAS_ACCEPTANCE]-> Acceptance`.
- **`GbuildNode`s** — one per unit of work. Integer `id` (sequential after the Feature and Acceptance
  nodes), `labels` `["GbuildNode", <PascalCase type>]`, properties `slug` / `title` / `type` (lowercase
  enum) / `contract` (`{input,output}`) / `acceptance` (node-level local criteria) / `verify` / `failure_policy`
  / `model_tier`. No `satisfies` property — use a `SATISFIES` edge instead.
- **`DEPENDS_ON` relationships** — one per dependency that passed the cut test. Direction
  dependent→dependency (`start_node` depends on `end_node`). Both endpoints are GbuildNodes.
- **`SATISFIES` relationships** — `GbuildNode -[:SATISFIES]-> Acceptance` for each global criterion a
  node covers.
- **`HAS_ACCEPTANCE` relationships** — `Feature -[:HAS_ACCEPTANCE]-> Acceptance`, one per bullet.

For each GbuildNode, write:

- `id` — integer, sequential, unique, never reused. Authoring convenience; `slug` is the stable identity.
- `slug` — filename-safe, kebab-case, immutable once created. This is what skills and checkpoint files
  key on; it's how nodes are referred to in anything the user reads.
- `type` — `research | decision | code | test | verify | chore`. Set both the lowercase `type` property
  and the matching PascalCase label (`Code`, `Research`, …).
- `contract.input` / `contract.output` — structured shapes, not prose. A downstream node's `input`
  should be able to reference an upstream node's `output` field directly.
- `acceptance` — **mandatory, non-empty, concrete.** No vague adjectives ("looks correct", "works
  well"). A criterion a fresh context with no other information couldn't check is not concrete enough.
  Rewrite it until it names a file, a shape, a value, or a command's result.
- `verify` — only set when this node needs something *beyond* the standard `gbuild-reviewer` pass
  (adversarial check, fact-check, human approval). Usually `null`.
- `failure_policy` — pick per `${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`, don't default everything to `retry`.
- `model_tier` — `strong` only where judgement, not throughput, is the bottleneck
  (`${CLAUDE_PLUGIN_ROOT}/reference/cost-model.md`).

Wire each dependency as a `DEPENDS_ON` relationship (not a `dependencies` array on the node), and each
criterion a node covers as a `SATISFIES` relationship (not a `satisfies` array). Set `next_node_id` and
`next_rel_id` to `max(id)+1` for each kind. `${CLAUDE_PLUGIN_ROOT}/templates/graph.json` is a complete worked example.

### 6. Write the global acceptance bar

The feature-level bar is one `Acceptance` node per bullet, each linked `Feature -[:HAS_ACCEPTANCE]-> Acceptance`,
with ids `a-1`, `a-2`, …. Every bullet must end up covered by at least one node's `SATISFIES` edge —
that's checked in step 7 and enforced by the validator.

### 7. Self-check against the checklist

Walk every item in `${CLAUDE_PLUGIN_ROOT}/reference/checklist.md` against the graph you just wrote. Fix the graph, don't
annotate around a failing item.

### 8. Write and validate

Write `.gbuild/<slug>/graph.json` (a CypherLite GraphData file). **Run the format validator first:**

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate_format.py .gbuild/<slug>/graph.json
```

If it prints `invalid: ...`, fix the file and re-run — never hand off or commit a file that fails
validation. The validator is the format gate; it checks the GraphData envelope, node shapes, the three
relationship types, id/counter invariants, acyclicity, and coverage. **Run it after every change** —
initial write, reopen, any hand-edit, any fix-up — before doing anything else with the file.

Then confirm run-readiness:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph.py .gbuild/<slug>/graph.json --status
```

The graph is now queryable with Cypher **if the `cypherlite` binary is on PATH** (`command -v
cypherlite`) — in that case you can mention it to the user:

```
cypherlite .gbuild/<slug>/graph.json "MATCH (n:GbuildNode) RETURN n.slug, n.type"
```

If the binary is absent, skip this without comment. CypherLite is an optional consumer, never a
requirement — `validate_format.py` already cross-checks with it when present and passes without it,
and the user should never be asked to install it.

### 9. Fire research nodes

For each `research`-typed node in the initial wave, dispatch a subagent **in parallel** (one message,
multiple `Agent` calls). Give each the node's `contract.input`, `acceptance`, and enough context to
work independently. Each writes its `output` to `.gbuild/<slug>/nodes/<id>.json` directly (`status:
completed`) — these still get a `gbuild-reviewer` pass before `run` will treat them as satisfying
anyone's dependency, same as every other node type.

### 10. Commit and stop

Commit `.gbuild/<slug>/` unless the repo ignores it (`git check-ignore -q .gbuild/`; if true, don't
stage anything under it). Message: `<slug>: chart graph`.

Report the branch, the wave decomposition, and the frontier. Close with `next: /gbuild:run <slug>`.

## Reopen

`--add "<requirement>"`:

0. Check out the feature's existing branch if you're not on it. Never chart a reopen onto a different
   branch than the one the graph was charted on.
1. Add a new `Acceptance` node (next `a-` id) + a `Feature -[:HAS_ACCEPTANCE]-> Acceptance` edge for the
   requirement.
2. Decompose whatever new GbuildNodes it needs, wire `DEPENDS_ON` edges against the *existing* graph (a
   new node may depend on an already-completed one — that's fine, its dependency is satisfied) and
   `SATISFIES` edges to the new (or existing) `Acceptance` nodes it covers. Assign the next available
   integer ids, bump `next_node_id`/`next_rel_id`. Re-run the checklist against the delta.
3. **Re-run `validate_format.py`** (counters, coverage, acyclicity all re-checked on the mutated graph),
   then `graph.py --status`. Commit (`<slug>: reopen graph — <what was added>`), report the new frontier.

If the requirement needs no new nodes (an existing node's contract already covers it), say so and stop
— don't manufacture graph churn.

## Rules

- **Plan, don't do.** Nodes here get *defined*, not executed — even `research` nodes just write
  findings to their own checkpoint, they don't touch anything `run` is responsible for.
- **Acceptance criteria are the bar, not a formality.** A node with vague acceptance is a node
  `gbuild-reviewer` can't actually check — that's a planning failure, not something to fix later.
- **Refer to nodes by title in anything the user reads.** IDs are for the graph, not the conversation.
