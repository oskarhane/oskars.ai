# gbuild — Claude Code + OpenCode plugin

Graph-native task planning and execution: plan a feature as a real dependency graph, then run it with
actual concurrent fan-out, a dedicated review pass on every node, and durable per-node checkpoints.

## The workflow

Plan in conversation first (your agent's normal plan mode), then hand that plan to gbuild:

1. `/gbuild:plan <the plan>` — chart it as a dependency graph
2. `/gbuild:run <slug>` — run it, once; it iterates waves until the graph completes (re-invoke only to resume an interrupted run)
3. `/gbuild:review <slug>` — audit the accumulated branch
4. Issues? `/gbuild:plan <slug> --add "<fix>"`, then `/gbuild:run` again. Clean? `/gbuild:pr <slug>`

The feature branch lives in its own git worktree (created by `plan`) — your checkout never changes
branches, your uncommitted work is never in the way, and several features can be in flight in parallel
without racing each other's `HEAD`.

(OpenCode: `/gbuild-plan`, `/gbuild-run`, … — same loop.)

Inspired by the graph-engineering thread at
[x.com/0xwhrrari/status/2086784668003598356](https://x.com/0xwhrrari/status/2086784668003598356):
sequence isn't dependency, every node needs an explicit contract, edges carry data not just order, and
verification never grades itself.

## Install

gbuild needs the `cypherlite` CLI on PATH — see [Runtime](#runtime).

### Claude Code

From the marketplace:

```bash
claude plugin marketplace add oskarhane/oskars.ai
claude plugin install gbuild@oskars.ai
```

For local development:

```bash
claude --plugin-dir ./plugins/gbuild
```

### OpenCode

The same directory is also an OpenCode (V2) plugin, published to npm as
[`opencode-gbuild`](https://www.npmjs.com/package/opencode-gbuild) — `index.ts` registers the five
skills and five slash commands (`/gbuild-plan`, `/gbuild-run`, `/gbuild-status`, `/gbuild-review`,
`/gbuild-pr`) from the same markdown the Claude plugin uses.

```bash
opencode plugin add opencode-gbuild
```

`opencode plugin update opencode-gbuild` moves to the latest published version. For local
development, point any `opencode.json(c)` at a checkout instead:

```jsonc
{
  "plugins": ["/path/to/oskars.ai/plugins/gbuild"]
}
```

#### Releasing

The npm package is published from this directory:

1. Bump `version` in `package.json` — keep `.claude-plugin/plugin.json`'s version in sync.
2. `npm publish` (2FA on the account; contents are whitelisted via `files` + `.npmignore`).
3. Users pick it up with `opencode plugin update opencode-gbuild`.

One translation note: OpenCode plugins can't register agents, so where the Claude plugin spawns its
bundled `gbuild-reviewer`/`gbuild-auditor` agents, the OpenCode skills dispatch the built-in `general`
subagent with the same `agents/gbuild-*.md` text inlined as its brief. The review is still a fresh,
isolated agent — never the implementer.

## Usage

Claude Code:

```
/gbuild:plan add OAuth login with GitHub
/gbuild:run add-oauth-login-with-github
/gbuild:status add-oauth-login-with-github
/gbuild:review add-oauth-login-with-github
/gbuild:pr add-oauth-login-with-github
```

OpenCode (same order, kebab-case names):

```
/gbuild-plan add OAuth login with GitHub
/gbuild-run add-oauth-login-with-github
/gbuild-status add-oauth-login-with-github
/gbuild-review add-oauth-login-with-github
/gbuild-pr add-oauth-login-with-github
```

- **`plan`** creates the feature branch in its own git worktree and charts the feature into a
  CypherLite graph store there (`.gbuild/<feature>/db/`) — `Feature`,
  `Acceptance`, and `GbuildNode` nodes, each node's contract as `INPUT`/`OUTPUT` `Field` nodes, and
  `FROM` edges carrying data from one node's output to the next node's input. Every dependency edge
  passes the cut test — and because data flow is explicit, the validator checks it; every node has
  mandatory concrete acceptance criteria. Written and validated entirely in Cypher.
- **`run`** dispatches every node in the current ready wave concurrently — not one at a time — with
  each file-touching node working in its own git worktree on its own branch, forked from the feature
  branch. A dedicated `gbuild-reviewer` subagent reviews each node's output against its branch's diff;
  only a passing node's branch is merged back into the feature branch — in the feature's worktree, not
  your checkout — and its worktree is removed.
  Unaccepted work never lands. A review failure applies the node's declared failure policy. Re-invoking
  after an interruption resumes only the remaining frontier, reusing the surviving worktrees.
- **`status`** reports the graph — frontier, blocked, in-flight, completed, each node's review verdict,
  and evidence of what actually ran concurrently vs. serially.
- **`review`** audits the finished branch as a whole in a `gbuild-auditor` subagent, working in the
  feature worktree (the full suite runs there) — abstraction
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

A node's status is its `status` property in the store, next to its outputs and its review history
(`Review` nodes, one per attempt). There are five, and each exists to answer a different question `run`
has to ask on every invocation:

| status        | means                                             | why it exists                                                                                                                                                              |
| ------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pending`     | not started                                       | Every node is charted `pending`. Interrupted work goes back to `pending` when the next run resets it, so nothing is left half-declared.                                     |
| `in_progress` | dispatched, no verdict yet                        | Distinguishes "running right now" from "never started", so a resumed run doesn't double-dispatch a node whose agent was killed mid-flight.                                   |
| `completed`   | reviewed and passed                               | The only status that satisfies a dependent's edge on merit. The write refuses without a passing `Review` and a value for every output — an implementing agent cannot mark its own success. |
| `cancelled`   | deliberately abandoned, dependents may proceed    | The `skip` failure policy's landing spot. Counts as satisfied, so abandoning an optional node doesn't permanently wedge everything downstream.                                |
| `failed`      | escalated, dependents held                        | Records that the node is genuinely stuck and needs a human. Does **not** satisfy dependents — they stay blocked rather than building on a broken foundation.                  |

The distinction that does the most work is `cancelled` vs `failed`. Both mean "this node isn't going to
produce its output," but they answer the dependents' question oppositely: `cancelled` says *proceed
without me*, `failed` says *stop and wait*. Collapsing them into one "didn't work" status would force
`run` to guess which one a given failure meant.

Everything else the tooling reports — `frontier`, `blocked`, `in_flight`, `waves` — is **derived** from
these five by `cypher/status.cypher`, never stored. Nothing can drift out of sync with itself, and the
frontier is a query result rather than a judgement call:

```
frontier  = pending ∧ every dependency completed-or-cancelled
blocked   = pending ∧ some dependency not completed-or-cancelled
in_flight = in_progress
```

## When a node needs you

Subagents are forked, so they cannot talk to you directly — a subagent's final message is a tool result,
not chat output. Anything it finds that needs a human decision therefore travels a specific path:
the subagent reports it, `run` records it, and `run`'s report surfaces it. Nothing gets silently
resolved by the agent that found it, and nothing gets routed around.

Three things can trigger it:

- **A node exhausts its failure policy.** `escalate` sets the node `failed`, stops dispatching
  its dependents (siblings elsewhere in the graph keep going), and surfaces it as needing a decision.
  `repair` escalates the same way once its 2 attempts are spent; `retry` and `fallback` are capped at 2
  attempts too, so no policy can loop unbounded. See `reference/failure-policies.md`.
- **A node's work invalidates an already-completed one.** `gbuild-reviewer` labels this
  `CONTRADICTS <slug>` and stops. It is explicitly *not* the reviewer's job to re-decide an upstream
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

gbuild **requires the [CypherLite](https://github.com/neo4j-labs/cypherlite) CLI**, 0.7.0 or newer:

```bash
curl -sSfL https://neo4j-labs.github.io/cypherlite/install.sh | bash
```

Every skill reads and writes the graph with `cypherlite` and nothing else — there is no Python and no
direct JSON editing. The plugin ships the queries as `.cypher` files; skills pipe them into the store
(`.gbuild/<feature>/db` inside the feature's worktree — examples below run from there):

```bash
cypherlite .gbuild/<feature>/db --mode jsonl < plugins/gbuild/cypher/validate.cypher   # format gate: no output = valid
cypherlite .gbuild/<feature>/db --mode jsonl < plugins/gbuild/cypher/progress.cypher   # one row per wave: counts + open nodes
cypherlite .gbuild/<feature>/db --mode jsonl "MATCH (n:GbuildNode {status: 'failed'}) RETURN n.slug"   # anything else
```

Reads are deliberately narrow so a run doesn't pay for the whole graph on every step: `run` claims a
wave (`dispatch.cypher` returns only that wave's nodes, with their inputs resolved) and records it
(`record.cypher`, one batched call) — two store calls per wave, regardless of graph size. The full
per-node view (`status.cypher`) is only for the human-facing `/gbuild:status`.

Required properties and their types are engine constraints, so an invalid write never lands; the rest of
the contract (enums, edge shapes, coverage, acyclicity, the cut test) is `validate.cypher`. CypherLite
locks a store while a process has it open, so only the main-context skill touches it, one command at a
time — subagents get their inputs in their prompt and report back. `reference/cypher.md` has the full
operating rules.

Tests (repo-root `npm test`) run the Cypher layer against the real binary: `cypher.test.ts` drives the
worked example through a full run, checks every validator rule and write guard, and holds a token budget
— a 40-node run must take two store calls per wave and stay under a fixed number of bytes read.

## Layout

```
plugins/gbuild/
  agents/gbuild-reviewer.md   # fast per-node gate — contract, acceptance, duplication; never self-review
  agents/gbuild-auditor.md    # end-of-branch audit: runs the test suite, then strict maintainability
  reference/                  # graph-format.md (normative model), cypher.md (how to talk to the store), queries.md (ad-hoc recipes); shapes/failure-policies/cost-model/checklist inform plan
  cypher/                     # schema, validate, progress/attention/status/node/feature reads, and run's dispatch/record/set-status
  templates/example.cypher    # a worked 4-node diamond, written the way plan writes a feature
  skills/{plan,run,status,review,pr}/
  index.ts                    # OpenCode plugin entry: registers the skills + /gbuild-* commands, translating paths/names
  package.json                # OpenCode plugin manifest (npm package "opencode-gbuild")
  cypher.test.ts              # node --test contract tests for the Cypher layer (repo-root `npm test`)
  smoke.test.ts               # node --test smoke test for the OpenCode translation
```

State lives outside the plugin, in the project: one CypherLite store per feature at
`.gbuild/<feature>/db/` inside the feature's own git worktree. It holds the plan, every node's status
and output values, and the full review
history. Only `db/graph.json` (CypherLite's JSON snapshot, kept current by every write) and the store's
own `.gitignore` are committed (on the feature branch). All of a feature's worktrees live under
`.git/gbuild/<feature>/` — never in `git status`: `tree/` is the feature worktree itself, created by
`plan` and kept until the feature is done, and during a run each file-touching node gets a `<node>/`
worktree that is removed the moment its node is accepted (merged into the feature branch, in `tree/`)
or terminally failed (discarded).
