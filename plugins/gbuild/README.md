# gbuild — Claude Code Plugin

Graph-native task planning and execution: plan a feature as a real dependency graph, then run it with
actual concurrent fan-out, a dedicated review pass on every node, and durable per-node checkpoints.

Inspired by the graph-engineering thread at
[x.com/0xwhrrari/status/2086784668003598356](https://x.com/0xwhrrari/status/2086784668003598356):
sequence isn't dependency, every node needs an explicit contract, edges carry data not just order, and
verification never grades itself.

## Install

From the marketplace:

```bash
claude plugin marketplace add oskarhane/oskars.ai
claude plugin install gbuild@oskars.ai
```

For local development:

```bash
claude --plugin-dir ./plugins/gbuild
```

## Usage

```
/gbuild:plan add OAuth login with GitHub
/gbuild:run add-oauth-login-with-github
/gbuild:status add-oauth-login-with-github
/gbuild:review add-oauth-login-with-github
/gbuild:pr add-oauth-login-with-github
```

- **`plan`** decomposes a feature into `.gbuild/<feature>/graph.json` — nodes with typed contracts,
  real dependency edges (every edge passes the cut test: does the dependent actually read the
  dependency's output?), and mandatory concrete acceptance criteria per node.
- **`run`** dispatches every node in the current ready wave concurrently — not one at a time — reviews
  each node's output with a dedicated `gbuild-reviewer` subagent before checkpointing it complete, and
  applies the node's declared failure policy on a review failure. Re-invoking after an interruption
  resumes only the remaining frontier.
- **`status`** reports the graph — frontier, blocked, in-flight, completed, each node's review verdict,
  and evidence of what actually ran concurrently vs. serially.
- **`review`** audits the finished branch as a whole in a `gbuild-auditor` subagent — abstraction
  quality, file size, spaghetti growth, and the cross-node duplication that per-node review can't see
  (two nodes, two contexts, same sub-problem solved twice). Blocking findings go back into the graph as
  a `plan --add` requirement. Ported from hone-ai's `review`.
- **`pr`** pushes the feature branch, opens a PR, then watches CI. A red check becomes a new
  requirement on the graph (`plan --add`) and gets run like any other node, rather than patched around
  — looping until the checks are green or the round cap is hit. Ported from hone-ai's `pr`.

## Why a graph instead of a task list

A flat ordered list encodes the order you thought of things in, not what actually depends on what. Two
independent nodes end up serialized for no reason, and nothing catches it. gbuild's `plan` states real
edges; `run` acts on them — independent nodes in the same wave dispatch together, a join waits for every
incoming edge, and a controlled cycle gets a hard round cap instead of an open-ended loop.

## Node statuses

A node's status lives in its own checkpoint file, `.gbuild/<feature>/nodes/<id>.json`. There are five,
and each exists to answer a different question `run` has to ask on every invocation:

| status        | means                                             | why it exists                                                                                                                                                              |
| ------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pending`     | not started                                       | The default — a node with no checkpoint file *is* pending. Nothing has to be written to declare work undone, so an interrupted run leaves no cleanup behind.                 |
| `in_progress` | dispatched, no verdict yet                        | Distinguishes "running right now" from "never started", so a resumed run doesn't double-dispatch a node whose agent was killed mid-flight.                                   |
| `completed`   | reviewed and passed                               | The only status that satisfies a dependent's edge on merit. Written only after `gbuild-reviewer` returns `VERDICT: pass` — an implementing agent cannot mark its own success. |
| `cancelled`   | deliberately abandoned, dependents may proceed    | The `skip` failure policy's landing spot. Counts as satisfied, so abandoning an optional node doesn't permanently wedge everything downstream.                                |
| `failed`      | escalated, dependents held                        | Records that the node is genuinely stuck and needs a human. Does **not** satisfy dependents — they stay blocked rather than building on a broken foundation.                  |

The distinction that does the most work is `cancelled` vs `failed`. Both mean "this node isn't going to
produce its output," but they answer the dependents' question oppositely: `cancelled` says *proceed
without me*, `failed` says *stop and wait*. Collapsing them into one "didn't work" status would force
`run` to guess which one a given failure meant.

Everything else the tooling reports — `frontier`, `blocked`, `in_flight`, `waves` — is **derived** from
these five by `scripts/graph.py`, never stored. Nothing can drift out of sync with itself, and the
frontier is a query result rather than a judgement call:

```
frontier  = pending ∧ every dependency completed-or-cancelled
blocked   = pending ∧ some dependency not completed-or-cancelled
in_flight = in_progress
```

## When a node needs you

Subagents are forked, so they cannot talk to you directly — a subagent's final message is a tool result,
not chat output. Anything it finds that needs a human decision therefore travels a specific path:
the subagent reports it, `run` checkpoints it, and `run`'s report surfaces it. Nothing gets silently
resolved by the agent that found it, and nothing gets routed around.

Three things can trigger it:

- **A node exhausts its failure policy.** `escalate` checkpoints the node `failed`, stops dispatching
  its dependents (siblings elsewhere in the graph keep going), and surfaces it as needing a decision.
  `repair` escalates the same way once its 2 attempts are spent; `retry` and `fallback` are capped at 2
  attempts too, so no policy can loop unbounded. See `reference/failure-policies.md`.
- **A node's work invalidates an already-completed one.** `gbuild-reviewer` labels this
  `CONTRADICTS <node-id>` and stops. It is explicitly *not* the reviewer's job to re-decide an upstream
  node's accepted output, so this always reaches you rather than being reconciled in place. When the
  contradiction undermines the graph's premise rather than one node, the `stop` policy halts the entire
  run instead of just one branch.
- **The end-of-branch audit finds something blocking.** `gbuild-auditor` returns findings to
  `/gbuild:review`, which relays them to chat verbatim — a subagent's audit is worthless if the caller
  paraphrases it. Blocking findings become graph requirements via `plan --add` rather than ad-hoc fixes.

So a run stops early in one of two shapes: an empty frontier with nodes still incomplete (something
escalated — `/gbuild:status` names it), or a hard halt (`stop`). Both report what's blocking and what
decision is wanted; neither guesses.

## Runtime

`scripts/graph.py` is Python 3, stdlib only — no `pip install` required. That's also why the graph file
is `graph.json` rather than YAML: Python's stdlib has no YAML parser, and adding PyYAML would defeat the
zero-extra-dependency goal. The file is written and read by agents, not hand-edited, so losing comments
costs little — `/gbuild:status` is the human-facing view.

```bash
python3 plugins/gbuild/scripts/graph.py .gbuild/<feature>/graph.json --status
python3 -m unittest plugins/gbuild/scripts/test_graph.py
```

## Layout

```
plugins/gbuild/
  agents/gbuild-reviewer.md   # per-node review, ported from hone-ai's reviewer, never self-review
  agents/gbuild-auditor.md    # end-of-branch maintainability audit, ported from hone-ai's auditor
  reference/                  # graph-format.md is normative; shapes/failure-policies/cost-model/checklist inform plan
  scripts/graph.py            # validate, topo-sort into waves, compute frontier/blocked/in-flight
  templates/graph.json        # a worked 4-node diamond example
  skills/{plan,run,status,review,pr}/
```

State lives outside the plugin, in the project: `.gbuild/<feature>/graph.json` (written once by
`plan`) and `.gbuild/<feature>/nodes/<id>.json` (one checkpoint per node, written by `run`).
