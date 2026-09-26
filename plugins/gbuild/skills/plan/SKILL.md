---
description: Decomposes a feature into a real dependency graph in the gbuild CypherLite store (.gbuild/<feature>/db) — nodes with typed field contracts, mandatory concrete acceptance criteria, and edges that pass the cut test. Use when starting new gbuild work, before /gbuild:run.
---

Plan the work described in `$ARGUMENTS` as a graph.

## The loop

The intended workflow: plan in ordinary conversation first, then chart that plan here. After this
skill: `/gbuild:run <slug>` once — it iterates waves until the graph completes. Then
`/gbuild:review <slug>`; if it finds issues, reopen with `/gbuild:plan <slug> --add "<fix>"` and
`/gbuild:run` again; if clean, `/gbuild:pr <slug>`.

Read `${CLAUDE_PLUGIN_ROOT}/reference/graph-format.md` (the normative graph model) and
`${CLAUDE_PLUGIN_ROOT}/reference/cypher.md` (how to talk to the store) before doing anything, and run
its version check. `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md`,
`${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`, and `${CLAUDE_PLUGIN_ROOT}/reference/cost-model.md`
inform the choices below. `${CLAUDE_PLUGIN_ROOT}/reference/checklist.md` is the self-check at the end.

## Mode

| arguments                                    | mode                    |
| --------------------------------------------- | ----------------------- |
| a description, link, or file path             | **Chart** — new feature |
| an existing feature slug with `--add "<req>"` | **Reopen**              |

A bare slug with no `.gbuild/<slug>/db/` is a description, not a slug — chart it.

## Chart

### 1. Slug and branch

Derive the feature slug from `$ARGUMENTS`: kebab-case, ≤4 words, names the outcome not the mechanism
(`oauth-device-flow`, not `add-some-auth-stuff`). It's the `.gbuild/<slug>/` directory name and the
`Feature` node's `feature` property — immutable once charted.

Then get onto a branch for it, so `run`'s commits land somewhere isolated:

- Working tree dirty → stop and ask. Don't stash or sweep someone else's changes into your branch.
- Already on a branch ending in `<slug>` → stay there, say so.
- Otherwise `git checkout -b <prefix>/<slug>` from current HEAD. Take `<prefix>` from the repo's
  convention — project or user instructions first, else the dominant pattern in `git branch --list`
  — and fall back to `gbuild` when there is none.

Report the branch. Everything below happens on it.

### 2. Analyse the codebase

Read the project manifest(s), directory structure, `README.md`, and — for related in-flight work — the
`Feature` of every existing store (`feature.cypher` against each `.gbuild/*/db`, one at a time). Resolve
file paths or URLs in `$ARGUMENTS`; if a reference fails to load, say so and ask.

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
note the result. A prototype worth charting names the specific question it answers in its `OUTPUT`
field, and its `acceptance` is the answer to that question.

### 4. Name the destination

Ask, one question at a time, until `destination` fits in one line — the thing that's true once this is
done. Do not proceed until it's that sharp; everything past it goes in `out_of_scope`.

### 5. Decompose into nodes, not steps

List the real pieces of work. For each pair, apply the **cut test** (`graph-format.md`): does one
actually read the other's output? If no, they're independent — same wave, not a chain. This is the step
hone-ai v1 skipped, and the whole reason gbuild exists: state the true dependency structure, don't
default to the order you thought of things in.

Classify each cluster's shape per `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md` (chain / diamond / router /
controlled cycle). A controlled cycle needs its round cap and dedup rule decided now, not left to `run`
to invent.

For each GbuildNode decide (full model in `graph-format.md`):

- `slug` — kebab-case, immutable; what skills and the store key on. `title` — what the user reads.
- `type` — `research | decision | code | test | verify | chore`, plus the matching PascalCase label.
- **`OUTPUT` fields** — every node declares at least one, each with a precise `shape`
  (`<integer>`, `<list of changed file paths>`, `<commit sha>`). Values will be scalars or lists of
  scalars; for anything nested, the shape says it is a JSON-encoded string.
- **`INPUT` fields** — one per value the node reads. If it comes from another node, wire it
  `FROM` that node's `OUTPUT` field and add the `DEPENDS_ON`. If it comes from the codebase or the
  environment, leave it without `FROM` and say where in its `shape`. The cut test is now concrete:
  a `DEPENDS_ON` exists exactly when the node reads one of the other's outputs.
- `acceptance` — **mandatory, non-empty, concrete.** No vague adjectives. A criterion a fresh context
  with no other information couldn't check is not concrete enough — rewrite it until it names a file, a
  shape, a value, or a command's result.
- `verify` — only when the node needs something *beyond* the standard `gbuild-reviewer` pass. Usually
  omitted.
- `failure_policy` — per `${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`, don't default everything
  to `retry`. `model_tier` — `strong` only where judgement, not throughput, is the bottleneck.
- `status: 'pending'` — every new node starts pending.

### 6. Write the global acceptance bar

The feature-level bar is one `Acceptance` node per bullet (`id` `a-1`, `a-2`, …), each linked
`(:Feature)-[:HAS_ACCEPTANCE]->(:Acceptance)`. Every bullet must end up covered by at least one node's
`SATISFIES` edge — the validator enforces it.

### 7. Self-check against the checklist

Walk every item in `${CLAUDE_PLUGIN_ROOT}/reference/checklist.md` against the graph you designed. Fix the
design, don't annotate around a failing item.

### 8. Create the store and write the graph

Create the store exactly as `reference/cypher.md` § Creating a store shows (`mkdir`, `schema.cypher` with
`--snapshot-format json`, the `db/.gitignore`).

Then write the whole graph as **one** Cypher script, piped through a quoted heredoc.
`${CLAUDE_PLUGIN_ROOT}/templates/example.cypher` is a complete worked example — follow its structure:
`.begin`, a single statement of `CREATE` clauses (so variables like `a1` or `a_value` stay in scope for
the edges), `.commit`, `.checkpoint`.

```
cypherlite .gbuild/<slug>/db <<'CYPHER'
.begin
CREATE (f:Feature {feature: '<slug>', destination: '...', context: '...', out_of_scope: ['...']})
CREATE (a1:Acceptance {id: 'a-1', text: '...'})
CREATE (f)-[:HAS_ACCEPTANCE]->(a1)
CREATE (n:GbuildNode:Code {slug: '...', title: '...', type: 'code', acceptance: ['...'],
                           failure_policy: 'repair', model_tier: 'cheap', status: 'pending'})
CREATE (n)-[:OUTPUT]->(n_out:Field {name: '...', shape: '<...>'})
...
CREATE (m)-[:DEPENDS_ON]->(n)
CREATE (m)-[:INPUT]->(:Field {name: '...', shape: '<...>'})-[:FROM]->(n_out)
CREATE (m)-[:SATISFIES]->(a1);
.commit
.checkpoint
CYPHER
```

A constraint violation (`ConstraintValidationFailed`: a missing property, a wrong type, a duplicate
slug) fails the transaction and writes nothing — fix the script and run it again.

### 9. Validate

```
cypherlite .gbuild/<slug>/db --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/validate.cypher
```

No output means valid. Every row is a violation (`check`, `detail`): fix it with Cypher — a `.begin` …
`.commit` … `.checkpoint` script of `MATCH … SET/CREATE/DELETE` — and re-run until it prints nothing. Never
hand off or commit a graph that fails validation, and never edit `graph.json` directly.

Then confirm run-readiness:

```
cypherlite .gbuild/<slug>/db --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher
```

One row per wave: each row's `open` slugs are the decomposition, and the `frontier` counts are what
`run` claims first. Nodes you expected to run together should share a wave.

### 10. Commit and stop

Commit `.gbuild/<slug>/` unless the repo ignores it (`git check-ignore -q .gbuild/`; if true, don't stage
anything under it). The store's own `.gitignore` limits that to `db/graph.json` and `db/.gitignore`.
Message: `<slug>: chart graph`.

Report the branch, the waves, and the frontier. Close with `next: /gbuild:run <slug>`.

## Reopen

`--add "<requirement>"`:

0. Check out the feature's existing branch if you're not on it. Never chart a reopen onto a different
   branch than the one the graph was charted on.
1. Read the current graph narrowly: `progress.cypher` for its shape and what's done, and `node.cypher`
   only for the nodes the requirement touches.
2. Design the delta: a new `Acceptance` node (next `a-` id) linked from the `Feature`, and whatever new
   GbuildNodes it needs, with their `Field`s. A new node may depend on an already-completed one — wire
   its `INPUT` `FROM` that node's `OUTPUT` like any other; its value is already recorded. Re-run the
   checklist against the delta.
3. Write it as one script that `MATCH`es what it connects to and `CREATE`s the rest:

   ```
   cypherlite .gbuild/<slug>/db <<'CYPHER'
   .begin
   MATCH (f:Feature), (up:GbuildNode {slug: '<existing-slug>'})-[:OUTPUT]->(up_out:Field {name: '<field>'})
   CREATE (f)-[:HAS_ACCEPTANCE]->(a:Acceptance {id: 'a-3', text: '...'})
   CREATE (n:GbuildNode:Code {slug: '...', ..., status: 'pending'})
   CREATE (n)-[:DEPENDS_ON]->(up)
   CREATE (n)-[:INPUT]->(:Field {name: '...', shape: '<...>'})-[:FROM]->(up_out)
   CREATE (n)-[:OUTPUT]->(:Field {name: '...', shape: '<...>'})
   CREATE (n)-[:SATISFIES]->(a);
   .commit
   .checkpoint
   CYPHER
   ```

4. **Re-run `validate.cypher`** until it prints nothing, then `progress.cypher`. Commit
   (`<slug>: reopen graph — <what was added>`), report the new frontier.

If the requirement needs no new nodes (an existing node's contract already covers it), say so and stop
— don't manufacture graph churn.

## Rules

- **Plan, don't do.** Nodes here get *defined*, not executed — even `research` nodes. They land in the
  first wave and `run` dispatches them.
- **The store is only touched through `cypherlite`**, from this skill, one command at a time
  (`reference/cypher.md`).
- **Acceptance criteria are the bar, not a formality.** A node with vague acceptance is a node
  `gbuild-reviewer` can't actually check — that's a planning failure, not something to fix later.
- **Refer to nodes by title in anything the user reads.** Slugs are for the graph, not the conversation.
