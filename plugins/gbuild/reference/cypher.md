# Talking to the gbuild store

Every gbuild skill reads and writes the feature store (`.gbuild/<feature>/db/`, modelled in
`reference/graph-format.md`) with the `cypherlite` CLI and nothing else. This file is the operating
manual; follow it exactly.

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

Always pass `-json` when you need the result. `DB` below is `.gbuild/<feature>/db`.

```
# a plugin script
cypherlite DB -json < ${CLAUDE_PLUGIN_ROOT}/cypher/status.cypher

# a plugin script with parameters
cypherlite DB -json --param 'slug="b-consume-doubled"' < ${CLAUDE_PLUGIN_ROOT}/cypher/node.cypher

# an ad-hoc read
cypherlite DB -json "MATCH (n:GbuildNode) RETURN n.slug, n.status ORDER BY n.slug LIMIT 100"

# a write you author (plan, reopen, fixes) — quoted heredoc delimiter, so the shell expands nothing
cypherlite DB <<'CYPHER'
.begin
MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.title = 'Consume the value, double it';
.commit
.checkpoint
CYPHER
```

## Rules

- **Parameters are JSON.** Every `--param` value is JSON, single-quoted for the shell: strings in double
  quotes (`--param 'slug="01-scan-runners"'`), lists and objects as JSON (`--param 'slugs=["a","b"]'`,
  `--param 'outputs={"value": 7}'`). Bare values that start with a digit — timestamps, `01-…` slugs —
  are rejected, so always quote.
- **String literals** in Cypher you author: single quotes by default; double quotes when the text
  contains an apostrophe (`"gbuild's"`); backslash-escape (`\'`, `\"`) when it contains both.
- **Authored writes are atomic and checkpointed.** Wrap them in `.begin` / `.commit` — if any statement
  fails, the whole transaction is discarded — and end with `.checkpoint` so `graph.json` on disk (what
  git commits) is always current. The plugin write scripts already do both.
- **Values are scalars or lists of scalars.** CypherLite cannot store a map as a property value;
  JSON-encode anything nested into a string.
- **Read the result.** The plugin write scripts are guarded: a write that did nothing returns `[]` (or
  `completed: false` with the reason). Never assume a write landed.
- **Exit code 1 is a failure** — lock, constraint violation (`ConstraintValidationFailed`), syntax. Read
  stderr, fix, retry the whole transaction.
- A one-shot write without `.checkpoint` still lands (reads replay the WAL), but `graph.json` stays stale
  until the next checkpoint — so always end writes with it.

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

All in `${CLAUDE_PLUGIN_ROOT}/cypher/`. Reads print one JSON array; writes end with `.checkpoint`.

| script               | params                                   | returns                                                        | used by |
| -------------------- | ---------------------------------------- | -------------------------------------------------------------- | ------- |
| `schema.cypher`      | —                                        | nothing (installs constraints)                                  | plan    |
| `validate.cypher`    | —                                        | one row per violation (`check`, `detail`); `[]` = valid         | every skill |
| `status.cypher`      | —                                        | one row per node: `slug`, `title`, `type`, `status`, `state` (`frontier`/`blocked`/stored status), `wave`, `waiting_on`, `review_attempts`, `last_verdict`, `last_failed_criteria`, `started_at`, `completed_at` | every skill |
| `node.cypher`        | `slug`                                   | one node: properties, `inputs` (resolved through `FROM`: `name`, `shape`, `from`, `value`), `outputs`, `depends_on`, `satisfies`, `reviews` | run     |
| `feature.cypher`     | —                                        | `destination`, `context`, `out_of_scope`, `acceptance` (with `covered_by`), every node's `outputs` | review, pr |
| `dispatch.cypher`    | `slugs` (list)                           | `dispatched` — only pending nodes whose dependencies are satisfied | run     |
| `record-review.cypher` | `slug`, `verdict` (`pass`/`fail`), `failed_criteria` (list) | `attempt`, `verdict`                                     | run     |
| `complete.cypher`    | `slug`, `outputs` (object), `started_at`, `completed_at` | `completed` (bool), `status`, `has_passing_review`, `missing_outputs` | run |
| `set-status.cypher`  | `slug`, `status` (`pending`/`in_progress`/`failed`/`cancelled`) | `slug`, `status`                                    | run     |
