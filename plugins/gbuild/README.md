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
