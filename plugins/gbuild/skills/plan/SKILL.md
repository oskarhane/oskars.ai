---
description: Decomposes a feature into a real dependency graph in .gbuild/<feature>/graph.json — nodes with typed contracts, mandatory concrete acceptance criteria, and edges that pass the cut test. Use when starting new gbuild work, before /gbuild:run.
---

Plan the work described in `$ARGUMENTS` as a graph.

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

### 3. Name the destination

Ask, one question at a time, until `destination` fits in one line — the thing that's true once this is
done. Do not proceed until it's that sharp; everything past it goes in `out_of_scope`.

### 4. Decompose into nodes, not steps

List the real pieces of work. For each pair, apply the **cut test** (`${CLAUDE_PLUGIN_ROOT}/reference/graph-format.md`):
does one actually read the other's output? If no, they're independent — same wave, not a chain. This is
the step hone-ai v1 skipped, and the whole reason gbuild exists: state the true dependency structure,
don't default to the order you thought of things in.

Classify each cluster's shape per `${CLAUDE_PLUGIN_ROOT}/reference/shapes.md` (chain / diamond / router / controlled cycle).
A controlled cycle needs its round cap and dedup rule decided now, not left to `run` to invent.

For each node, write:

- `id` — filename-safe, kebab-case, immutable once created.
- `type` — `research | decision | code | test | verify | chore`.
- `dependencies` — only edges that passed the cut test.
- `contract.input` / `contract.output` — structured shapes, not prose. A downstream node's `input`
  should be able to reference an upstream node's `output` field directly.
- `satisfies` — which global `acceptance` ids this node serves.
- `acceptance` — **mandatory, non-empty, concrete.** No vague adjectives ("looks correct", "works
  well"). A criterion a fresh context with no other information couldn't check is not concrete enough.
  Rewrite it until it names a file, a shape, a value, or a command's result.
- `verify` — only set when this node needs something *beyond* the standard `gbuild-reviewer` pass
  (adversarial check, fact-check, human approval). Usually `null`.
- `failure_policy` — pick per `${CLAUDE_PLUGIN_ROOT}/reference/failure-policies.md`, don't default everything to `retry`.
- `model_tier` — `strong` only where judgement, not throughput, is the bottleneck
  (`${CLAUDE_PLUGIN_ROOT}/reference/cost-model.md`).

### 5. Write the global acceptance bar

`acceptance` at the top level is the whole-feature bar, gisted as short bullets with ids (`a-1`, `a-2`,
…). Every bullet must end up covered by at least one node's `satisfies` — that's checked in step 6.

### 6. Self-check against the checklist

Walk every item in `${CLAUDE_PLUGIN_ROOT}/reference/checklist.md` against the graph you just wrote. Fix the graph, don't
annotate around a failing item.

### 7. Write and validate

Write `.gbuild/<slug>/graph.json`. Run:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph.py .gbuild/<slug>/graph.json --status
```

If it prints `invalid graph: ...`, fix the file and re-run — don't hand off an invalid graph.

### 8. Fire research nodes

For each `research`-typed node in the initial wave, dispatch a subagent **in parallel** (one message,
multiple `Agent` calls). Give each the node's `contract.input`, `acceptance`, and enough context to
work independently. Each writes its `output` to `.gbuild/<slug>/nodes/<id>.json` directly (`status:
completed`) — these still get a `gbuild-reviewer` pass before `run` will treat them as satisfying
anyone's dependency, same as every other node type.

### 9. Commit and stop

Commit `.gbuild/<slug>/` unless the repo ignores it (`git check-ignore -q .gbuild/`; if true, don't
stage anything under it). Message: `<slug>: chart graph`.

Report the branch, the wave decomposition, and the frontier. Close with `next: /gbuild:run <slug>`.

## Reopen

`--add "<requirement>"`:

0. Check out the feature's existing branch if you're not on it. Never chart a reopen onto a different
   branch than the one the graph was charted on.
1. Add the requirement to the top-level `acceptance` list with the next `a-` id.
2. Decompose whatever new nodes it needs, wire `dependencies` against the *existing* graph (a new node
   may depend on an already-completed one — that's fine, its dependency is satisfied), re-run the
   checklist against the delta.
3. Validate with `graph.py --status`, commit (`<slug>: reopen graph — <what was added>`), report the
   new frontier.

If the requirement needs no new nodes (an existing node's contract already covers it), say so and stop
— don't manufacture graph churn.

## Rules

- **Plan, don't do.** Nodes here get *defined*, not executed — even `research` nodes just write
  findings to their own checkpoint, they don't touch anything `run` is responsible for.
- **Acceptance criteria are the bar, not a formality.** A node with vague acceptance is a node
  `gbuild-reviewer` can't actually check — that's a planning failure, not something to fix later.
- **Refer to nodes by title in anything the user reads.** IDs are for the graph, not the conversation.
