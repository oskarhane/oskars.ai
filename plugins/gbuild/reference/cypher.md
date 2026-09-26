# Talking to the gbuild store

Every gbuild skill reads and writes the feature store (`.gbuild/<feature>/db/`, modelled in
`reference/graph-format.md`) with the `cypherlite` CLI and nothing else. This file is the full operating
manual; the skills that only run plugin scripts carry the short version of these rules inline.

## Requirement

`cypherlite` 0.7.0 or newer must be on PATH. Check first, in every skill:

```
cypherlite --version
```

If the command is missing, stop and tell the user gbuild needs it:
`curl -sSfL https://neo4j-labs.github.io/cypherlite/install.sh | bash`. Never fall back to reading or
editing `graph.json` by hand.

## One writer, one command at a time

CypherLite takes an exclusive lock on the store while a process has it open. A second process — reader
or writer — fails with `storage locked` (exit 1). So:

- **Only the skill running in the main context runs `cypherlite` against the store.** Subagents never
  do: give them what they need in their prompt, have them report results in their final message, and
  record those results yourself.
- **Never run two `cypherlite` commands against the same store at once** — no parallel tool calls on it.
  Fan-out is for agents, not for store access.
- On `storage locked`, another process holds the store (another gbuild command, a REPL left open). Wait a
  few seconds and retry, up to 3 times; then stop and report. Never delete `.cypherlite.lock`.

## Invocation

Always pass `--mode jsonl`: one compact JSON object per row, one row per line, and no output at all when
there are no rows. `DB` below is `.gbuild/<feature>/db`.

```
# a plugin script
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher

# a plugin script with parameters
cypherlite DB --mode jsonl --param 'slug="b-consume-doubled"' < ${CLAUDE_PLUGIN_ROOT}/cypher/node.cypher

# an ad-hoc read — return only the columns you need, and keep a LIMIT on anything that can grow
cypherlite DB --mode jsonl "MATCH (n:GbuildNode {status: 'failed'}) RETURN n.slug LIMIT 20"

# a write you author (plan, reopen, fixes) — quoted heredoc delimiter, so the shell expands nothing
cypherlite DB <<'CYPHER'
.begin
MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.title = 'Consume the value, double it';
.commit
.checkpoint
CYPHER
```

## Rules

- **Read narrowly.** Prefer the smallest script that answers the question — `progress` for "how far
  along / is it done", `attention` for "what needs a decision", `dispatch` for "what runs next". The full
  per-node `status` is for the human-facing `/gbuild:status` report, not for loops.
- **Parameters are JSON.** Every `--param` value is JSON, single-quoted for the shell: strings in double
  quotes (`--param 'slug="01-scan-runners"'`), lists and objects as JSON (`--param 'slugs=["a","b"]'`).
  Bare values that start with a digit — timestamps, `01-…` slugs — are rejected, so always quote.
- **String literals** in Cypher you author: single quotes by default; double quotes when the text
  contains an apostrophe (`"gbuild's"`); backslash-escape (`\'`, `\"`) when it contains both.
- **Authored writes are atomic and checkpointed.** Wrap them in `.begin` / `.commit` — if any statement
  fails, the whole transaction is discarded — and end with `.checkpoint` so `graph.json` on disk (what
  git commits) is always current. The plugin write scripts already do both.
- **Values are scalars or lists of scalars.** CypherLite cannot store a map as a property value;
  JSON-encode anything nested into a string.
- **Read the result.** The plugin write scripts are guarded and return what they actually changed.
  Compare it with what you asked for; never assume a write landed.
- **Exit code 1 is a failure** — lock, constraint violation (`ConstraintValidationFailed`), syntax. Read
  stderr, fix, retry the whole transaction.

## Creating a store

Only `plan` does this, once per feature:

```
mkdir -p .gbuild/<feature>/db
cypherlite .gbuild/<feature>/db --snapshot-format json < ${CLAUDE_PLUGIN_ROOT}/cypher/schema.cypher
printf '*\n!.gitignore\n!graph.json\n' > .gbuild/<feature>/db/.gitignore
```

`--snapshot-format json` belongs on this first call only (it applies to an empty directory). It installs
the schema constraints and pins the JSON codec, so `graph.json` exists from the start.

## Script catalog

All in `${CLAUDE_PLUGIN_ROOT}/cypher/`. Writes end with `.checkpoint`.

| script               | params                    | returns                                                        | used by |
| -------------------- | ------------------------- | -------------------------------------------------------------- | ------- |
| `schema.cypher`      | —                         | nothing (installs constraints)                                  | plan    |
| `validate.cypher`    | —                         | one row per violation (`check`, `detail`); no rows = valid      | every skill |
| `progress.cypher`    | —                         | one row per wave: `total`, counts per state, `open` (slugs not yet completed or cancelled) | every skill |
| `attention.cypher`   | —                         | only nodes needing a decision: `slug`, `reason` (`failed` / `in_progress` / `blocked-by-failed`), `detail` | run, status |
| `dispatch.cypher`    | —                         | claims the whole frontier (→ `in_progress`); per claimed node: `slug`, `title`, `type`, `acceptance`, `failure_policy`, `model_tier`, `verify`, `inputs` (`name`, `shape`, `value`), `outputs` (`name`, `shape`) | run |
| `record.cypher`      | `results` — list of `{slug, verdict, failed_criteria, outputs, started_at, completed_at}` | per recorded node: `attempt`, `verdict`, `completed`, `missing_outputs` | run |
| `set-status.cypher`  | `slugs` (list), `status` (`pending` / `in_progress` / `failed` / `cancelled`) | `slug`, `status` per changed node | run |
| `status.cypher`      | —                         | one row per node: `state`, `wave`, `waiting_on`, review summary, timestamps | status (human report) |
| `node.cypher`        | `slug`                    | one node in full: properties, `inputs` (with `from`), `outputs`, `depends_on`, `satisfies`, `reviews` | plan (reopen), ad hoc |
| `feature.cypher`     | —                         | `destination`, `context`, `out_of_scope`, `acceptance` (with `covered_by`) | review, pr |

Ready-made ad-hoc queries (lineage, critical path, repair history, …) are in
`${CLAUDE_PLUGIN_ROOT}/reference/queries.md`.
