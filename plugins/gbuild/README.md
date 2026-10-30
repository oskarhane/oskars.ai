# gbuild — Claude Code + OpenCode plugin

Graph-native task planning and execution: design a feature with the human, plan it as a real
dependency graph, then run it with actual concurrent fan-out, a dedicated review pass on every node,
and durable per-node checkpoints.

## The workflow

Design the feature first — `/gbuild:design` when the work needs shaping before it can be charted,
conversation (your agent's normal plan mode) when it doesn't — then hand it to gbuild:

1. `/gbuild:design <the feature>` — shape it with the human into committed design artifacts (`docs/design/<slug>/`) on the feature branch in its own worktree; it ends only when you call the design good, and re-invoking with the slug resumes from the commits
2. `/gbuild:plan <the plan>` — chart it as a dependency graph
3. `/gbuild:run <slug>` — run it, once; it starts each node the moment its dependencies complete, until the graph completes (re-invoke only to resume an interrupted run)
4. `/gbuild:review <slug>` — audit the accumulated branch
5. Issues? `/gbuild:plan <slug> --add "<fix>"`, then `/gbuild:run` again. Clean? `/gbuild:pr <slug>`

The feature branch lives in its own git worktree (created by `design` or `plan`) — your checkout never changes
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
[`opencode-gbuild`](https://www.npmjs.com/package/opencode-gbuild) — `index.ts` registers the six
skills and six slash commands (`/gbuild-design`, `/gbuild-plan`, `/gbuild-run`, `/gbuild-status`,
`/gbuild-review`, `/gbuild-pr`) from the same markdown the Claude plugin uses.

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
bundled `gbuild-implementer`/`gbuild-reviewer`/`gbuild-auditor` agents, the OpenCode skills dispatch the
built-in `general` subagent instead. For the implementer and reviewer the prompt is run's dispatch
prompt with its `Agent file: <path>.` field moved to the front as `Read <path> and follow it.`, so the
path appears once; the auditor gets `Read <plugin>/agents/gbuild-auditor.md and follow
it.` followed by exactly what the review skill passes it. The agent's text is never pasted into the
prompt. The review is still a fresh, isolated agent — never the implementer.

## Usage

Claude Code:

```
/gbuild:design add OAuth login with GitHub
/gbuild:plan add OAuth login with GitHub
/gbuild:run add-oauth-login-with-github
/gbuild:status add-oauth-login-with-github
/gbuild:review add-oauth-login-with-github
/gbuild:pr add-oauth-login-with-github
```

OpenCode (same order, kebab-case names):

```
/gbuild-design add OAuth login with GitHub
/gbuild-plan add OAuth login with GitHub
/gbuild-run add-oauth-login-with-github
/gbuild-status add-oauth-login-with-github
/gbuild-review add-oauth-login-with-github
/gbuild-pr add-oauth-login-with-github
```

- **`design`** shapes a feature with the human before `plan` charts it — for when the destination
  still has options, the moving parts aren't named, or the trade-offs are unmade. It analyses the
  codebase, drives the discussion in batched question rounds (the destination first, one line), and
  commits each settled piece to `docs/design/<slug>/` on the feature branch in its own worktree —
  `design.md` carries the destination, scope, decisions with their ruled-out alternatives, and the
  open questions. It ends only when the human calls the design good — never on its own judgement —
  writes no implementation (unknowns that need code become open questions for `plan` to chart as
  `research` nodes), and runs without `cypherlite` or a store; re-invoking with the slug resumes
  from the committed artifacts.
- **`plan`** creates the feature branch in its own worktree (reusing the one `design` left, when
  there is one) and charts the feature into a
  machine-local CypherLite graph store (`<git-common-dir>/gbuild/<feature>/db`) — `Feature`,
  `Acceptance`, and `GbuildNode` nodes, each node's contract as `INPUT`/`OUTPUT` `Field` nodes, and
  `FROM` edges carrying data from one node's output to the next node's input. Every dependency edge
  passes the cut test — and because data flow is explicit, the validator checks it; every node has
  mandatory concrete acceptance criteria, each naming the narrowest check that proves it. Written
  and validated entirely in Cypher.
- **`run`** schedules the graph as dataflow, not waves: a node starts the moment its own dependencies
  complete, while unrelated slower nodes are still running, and each node runs its own pipeline —
  implement, review, land, record — in background subagents, with each file-touching node working in
  its own git worktree on its own branch, forked from the feature branch. A `gbuild-implementer` does
  the work — the most straightforward implementation that meets the node's bar, verified with only
  the checks its criteria name; a dedicated `gbuild-reviewer` reviews it against the branch's diff
  as soon as the implementer replies. Only a passing node's branch is merged back into the feature
  branch — one merge at a time, in the feature's worktree, not your checkout — and its worktree is
  removed.
  Unaccepted work never lands. A review failure applies the node's declared failure policy. Re-invoking
  after an interruption resumes only the remaining frontier, reusing the surviving worktrees.
- **`status`** reports the graph — frontier, blocked, in-flight, completed, each node's review verdict,
  and dataflow evidence: whether each node started soon after its last dependency completed.
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
edges; `run` acts on them — independent nodes run at the same time, a node starts as soon as the
nodes it reads from have landed, a join waits for every incoming edge, and a controlled cycle gets a
hard round cap instead of an open-ended loop.

## How agents get their context

`run` passes references, not content. A dispatch prompt is one line, the same for implementer and
reviewer, and each agent reads the rest itself (the inbox is always the `inbox/` directory beside the
store):

```
gbuild node `<slug>`. Store: <DB>. Worktree: <worktree>. Feature branch: <BRANCH>. Agent file: ${CLAUDE_PLUGIN_ROOT}/agents/gbuild-<implementer|reviewer>.md.
```

- **Briefs from the store, read-only.** `brief.cypher` returns the node's title, acceptance, inputs
  (upstream values resolved through `FROM` edges), outputs, the failed criteria of a previous attempt,
  and notes. Agents run it with `--read-only`, which opens beside `run`'s writes; `run` stays the only
  writer.
- **Results through inbox files.** The implementer writes `<slug>.json` — outputs, its own UTC times,
  notes, symbols — to `<git-common-dir>/gbuild/<feature>/inbox/` and replies `done <slug>`; the reviewer
  writes its checklist to `<slug>.review.json` and replies with just its `VERDICT:` line and `[fail]`
  lines. `record.cypher` reads both files itself, so outputs are never retyped. The verdict only ever
  comes from the reviewer's reply, never from a file the implementer could edit.
- **Shared notes and symbols.** Implementers leave up to 5 notes (`setup`, `testing`, `conventions`,
  `gotcha`) and list up to 10 helpers they added; when a node completes, `record` stores them as `Note`
  and `Symbol` nodes. Later briefs carry upstream nodes' notes plus every setup and testing note —
  implementers provision their worktree from the setup notes in their brief — and implementers and
  reviewers check `symbols.cypher` before writing or flagging a helper. Only merged nodes' symbols
  exist, so nodes running at the same time can't see each other's unmerged work.

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

gbuild **requires the [CypherLite](https://github.com/neo4j-labs/cypherlite) CLI**, 0.12.0 or newer:

```bash
curl -sSfL https://neo4j-labs.github.io/cypherlite/install.sh | bash
```

Every skill reads and writes the graph with `cypherlite` and nothing else — there is no Python and no
direct JSON editing. The plugin ships the queries as `.cypher` files; skills pipe them into the store
(`<git-common-dir>/gbuild/<feature>/db` — machine-local, never committed):

```bash
cypherlite query --read-only --database <git-common-dir>/gbuild/<feature>/db --mode jsonl < plugins/gbuild/cypher/validate.cypher   # format gate: no output = valid
cypherlite query --read-only --database <git-common-dir>/gbuild/<feature>/db --mode jsonl < plugins/gbuild/cypher/progress.cypher   # one row per wave: counts + open nodes
cypherlite query --read-only "MATCH (n:GbuildNode {status: 'failed'}) RETURN n.slug" --database <git-common-dir>/gbuild/<feature>/db --mode jsonl   # anything else
```

Reads are deliberately narrow so a run doesn't pay for the whole graph on every step: `dispatch.cypher`
returns only routing columns (`slug`, `type`, `model_tier`, `failure_policy`) for the nodes it claims,
and `run` records each node with its own `record.cypher` call and claims again after every record —
about two store calls per node, whatever the graph's shape. Node definitions go from the store to the
agents (`brief.cypher`), never through the orchestrator. The full per-node view (`status.cypher`) is
only for the human-facing `/gbuild:status`.

Required properties and their types are engine constraints, so an invalid write never lands; the rest of
the contract (enums, edge shapes, coverage, acyclicity, the cut test, note and symbol ownership) is
`validate.cypher`. Only the main-context skill writes the store, one command at a time — a second
writer gets `storage locked`. Subagents run only read-only queries (`brief`, `symbols`,
`check-result`), which open beside the writer, and report back through the inbox and a one-line reply.
`reference/cypher.md` has the full operating rules.

Tests (repo-root `npm test`) run the Cypher layer against the real binary: `cypher.test.ts` drives the
worked example through a full run, checks every validator rule and write guard, covers the brief,
result-check and symbols scripts, and holds a token budget — a 40-node run that records each node on
its own and re-dispatches after every record must take at most 2 × nodes + 2 store calls, get only
routing columns from every dispatch, and stay under a byte cap per call and for the whole run.

## Layout

```
plugins/gbuild/
  agents/gbuild-implementer.md # per-node implementer — reads its brief read-only, works in its worktree, writes its result to the inbox
  agents/gbuild-reviewer.md   # fast per-node gate — contract, acceptance, duplication, scope; never self-review
  agents/gbuild-auditor.md    # end-of-branch audit: runs the test suite, then strict maintainability
  reference/                  # graph-format.md (normative model), cypher.md (how to talk to the store), queries.md (ad-hoc recipes); shapes/failure-policies/cost-model/checklist inform plan
  cypher/                     # schema, validate, progress/attention/status/node/feature reads, run's dispatch/record/set-status, and brief/check-result/symbols for its agents
  templates/example.cypher    # a worked 4-node diamond, written the way plan writes a feature
  skills/{design,plan,run,status,review,pr}/
  index.ts                    # OpenCode plugin entry: registers the skills + /gbuild-* commands, translating paths/names
  package.json                # OpenCode plugin manifest (npm package "opencode-gbuild")
  cypher.test.ts              # node --test contract tests for the Cypher layer (repo-root `npm test`)
  smoke.test.ts               # node --test smoke test for the OpenCode translation
```

State lives outside the plugin, in the project: one CypherLite store per feature at
`<git-common-dir>/gbuild/<feature>/db` — machine-local, never committed and never carried by a clone.
It holds the plan, every node's status and output values, the full review history (with each
reviewer's checklist), and the notes and symbols agents left; CypherLite checkpoints the store on exit,
so `db/graph.json` is just the engine's local snapshot. All of a feature's worktrees live under
`.git/gbuild/<feature>/` — never in `git status`: `tree/` is the feature worktree itself, created by
`design` or `plan` and kept until the feature is done, and during a run each file-touching node gets a `<node>/`
worktree that is removed the moment its node is accepted (merged into the feature branch, in `tree/`)
or terminally failed (discarded). Beside them, `inbox/` holds the run's hand-off files (`<slug>.json`,
`<slug>.review.json`), emptied when a run starts and cleared for each node once it is recorded.
