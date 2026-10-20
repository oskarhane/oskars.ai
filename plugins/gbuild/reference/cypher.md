# Talking to the gbuild store

Every gbuild skill reads and writes the feature store (modelled in `reference/graph-format.md`) with the
`cypherlite` CLI and nothing else. `DB` throughout is the store path:
`<git-common-dir>/gbuild/<feature>/db` — beside the feature worktree, machine-local, never committed.
`INBOX` is `<git-common-dir>/gbuild/<feature>/inbox`, beside it: where `run`'s agents leave their result
files for `record.cypher` to read. This file is the full operating manual; the skills that only run
plugin scripts carry the short version of these rules inline.

## Requirement

`cypherlite` 0.12.0 or newer must be on PATH. Check first, in every skill:

```
cypherlite --version
```

If the command is missing, stop and tell the user gbuild needs it:
`curl -sSfL https://neo4j-labs.github.io/cypherlite/install.sh | bash`. Never fall back to reading or
editing `graph.json` by hand.

The floor is the ADR-0200 CLI cutover: the store path is a flag (`-d` / `--database PATH`), the first
positional is the Cypher statement (never the database), and piped scripts and the interactive shell
require the explicit `query` verb. The old path-first form — database as the first argument — hard-fails.

## One writer, one command at a time

The store is a directory store. A writable open takes its exclusive write lock; a `--read-only` open
does not, so read-only queries open the store beside a writer. Only a second writer fails, with
`storage locked` (exit 5). So:

- **Only the skill running in the main context writes to the store.** It is the only writer: schema,
  dispatch, record, set-status and authored writes run there and nowhere else.
- **Subagents may run read-only queries, never writes.** `run`'s implementers and reviewers read their
  own brief (`brief.cypher`), the helper registry (`symbols.cypher`) and their result check
  (`check-result.cypher`), always with `--read-only` — their agent files list exactly what they run.
  They report through files in `INBOX` plus a one-line reply; the orchestrator records them.
- **One `cypherlite` command at a time from the main context** — no parallel tool calls on the store.
  Fan-out is for agents, not for store writes.
- On `storage locked` (exit 5), another writer holds the store (another gbuild command, a REPL left
  open). Wait a few seconds and retry, up to 3 times; then stop and report. Never delete
  `.cypherlite.lock`.

## Invocation

Always pass `--mode jsonl`: one compact JSON object per row, one row per line, and no output at all when
there are no rows. Every call is `cypherlite query [STATEMENT] --database DB …`; with no STATEMENT the
piped stdin is the script list. Pure reads add `--read-only`: no exit flush, a shared lock, and a
fail-fast on a wrong path — a read-only call never creates a missing store. Writes (schema creation,
dispatch, record, set-status, authored heredocs) go without.

```
# a plugin read script
cypherlite query --read-only --database DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher

# a plugin read script with parameters
cypherlite query --read-only --database DB --mode jsonl --param 'slug="b-consume-doubled"' < ${CLAUDE_PLUGIN_ROOT}/cypher/node.cypher

# an ad-hoc read — return only the columns you need, and keep a LIMIT on anything that can grow
cypherlite query "MATCH (n:GbuildNode {status: 'failed'}) RETURN n.slug LIMIT 20" --read-only --database DB --mode jsonl

# a write you author (plan, reopen, fixes) — quoted heredoc delimiter, so the shell expands nothing
cypherlite query --database DB <<'CYPHER'
.begin
MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.title = 'Consume the value, double it';
.commit
CYPHER
```

## Rules

- **Read narrowly.** Prefer the smallest script that answers the question — `progress` for "how far
  along / is it done", `attention` for "what needs a decision", `dispatch` for "what runs next". The full
  per-node `status` is for the human-facing `/gbuild:status` report, not for loops.
- **Parameters are JSON.** Every `--param` value is JSON, single-quoted for the shell: strings in double
  quotes (`--param 'slug="01-scan-runners"'`), lists and objects as JSON (`--param 'slugs=["a","b"]'`).
  Bare values that start with a digit — timestamps, `01-…` slugs — are rejected, so always quote.
  `--fetch-params NAME=<file>` binds a JSON file as `$NAME` instead — how `record` and `check-result`
  read inbox files without anyone retyping them.
- **String literals** in Cypher you author: single quotes by default; double quotes when the text
  contains an apostrophe (`"gbuild's"`); backslash-escape (`\'`, `\"`) when it contains both.
- **Authored writes are atomic.** Wrap them in `.begin` / `.commit` — if any statement fails, the whole
  transaction is discarded. The plugin write scripts already do. Never write `.checkpoint`: a writable
  session checkpoints on exit by itself.
- **Values are scalars or lists of scalars.** CypherLite cannot store a map as a property value;
  JSON-encode anything nested into a string.
- **Read the result.** The plugin write scripts are guarded and return what they actually changed.
  Compare it with what you asked for; never assume a write landed.
- **Check the exit code.** `0` is success (an empty result included). `5` is `storage locked` or a
  write conflict — wait and retry as above. `6` is a rejected statement — syntax, semantic, or type
  error, including `ConstraintValidationFailed` and writes on a `--read-only` store — read stderr, fix,
  retry the whole transaction. `2` is a usage error — fix the invocation, not the data. `1` is any other
  runtime failure. With `--mode jsonl` a failure also prints one JSON error envelope on stdout, after
  any rows already written: `{"error":{"code","exit_code","kind","message","retryable"}}`.
- **Agent output is capped at 100 rows.** Under a detected agent harness with non-terminal stdout —
  gbuild skills always are — a statement prints at most 100 rows, warns on stderr, and still exits `0`.
  Keep a `LIMIT` on anything that can grow; when you genuinely need every row, pass `--max-rows 0` (or
  set `CYPHERLITE_MAX_ROWS=0`).

## Creating a store

Only `plan` does this, once per feature:

```
mkdir -p DB
cypherlite query --database DB --snapshot-format json < ${CLAUDE_PLUGIN_ROOT}/cypher/schema.cypher
```

`--snapshot-format json` belongs on this first call only (it applies to an empty directory). It installs
the schema constraints and pins the JSON codec for cross-build compatibility: a parquet-enabled
CypherLite build defaults a new store to Parquet, and a JSON-pinned store opens in every build.

## Migrating an old store

Stores charted by gbuild ≤ 0.7.1 live at `<tree>/.gbuild/<slug>/db` and are git-tracked. Migrate with
`git rm -r --cached .gbuild` (commit the removal) and
`mv <tree>/.gbuild/<slug>/db <git-common-dir>/gbuild/<slug>/db`.

## Script catalog

All in `${CLAUDE_PLUGIN_ROOT}/cypher/`.

| script               | params                    | returns                                                        | used by |
| -------------------- | ------------------------- | -------------------------------------------------------------- | ------- |
| `schema.cypher`      | —                         | nothing (installs constraints)                                  | plan    |
| `validate.cypher`    | —                         | one row per violation (`check`, `detail`); no rows = valid      | every skill |
| `progress.cypher`    | —                         | one row per wave: `total`, counts per state, `open` (slugs not yet completed or cancelled) | every skill |
| `attention.cypher`   | —                         | only nodes needing a decision: `slug`, `reason` (`failed` / `in_progress` / `blocked-by-failed`), `detail` | run, status |
| `dispatch.cypher`    | —                         | claims every frontier node (→ `in_progress`); per claimed node only the routing columns `slug`, `type`, `model_tier`, `failure_policy` — agents read the rest with `brief` | run (at start, and after every record / set-status) |
| `brief.cypher`       | `slug`                    | one node's brief: `slug`, `title`, `type`, `acceptance`, `verify`, `inputs` (`name`, `shape`, `from`, `value`), `outputs` (`name`, `shape`), `failed_criteria` (the latest review's when it failed, else `[]`), `notes` (`topic`, `text`, `by` — every transitive upstream node's notes plus setup and testing notes from any node, upstream first, then newest, at most 20) | run's implementer and reviewer (read-only) |
| `check-result.cypher` | `slug`; `result` (`--fetch-params result=INBOX/<slug>.json`) | `slug`, `missing_outputs`, `invalid_outputs`, `unknown_outputs`, `has_times` — clean when the three lists are `[]` and `has_times` is `true` | run's implementer and reviewer (read-only) |
| `record.cypher`      | `verdict` — `{slug, verdict, failed_criteria}`; `result` — `--fetch-params result=INBOX/<slug>.json` on a pass whose file exists, else `{}`; `review` — `--fetch-params review=INBOX/<slug>.review.json` when it exists, else `{}` (all three always bound) | one call per node: `slug`, `attempt`, `verdict`, `completed`, `missing_outputs`, `notes_added`, `symbols_added`, `unselected`; the `Review` keeps the review file's `checklist`, and a completing pass stores the result file's outputs, times, `notes` (as `Note`) and `symbols` (as `Symbol`) | run |
| `notes.cypher`       | `topics` (list)           | `topic`, `text`, `by` — stored notes of those topics, newest first, at most 20 | run (setup notes before creating worktrees), ad hoc |
| `symbols.cypher`     | —                         | `name`, `file`, `purpose`, `by` — every completed node's registered helpers, by file and name, at most 100 | run's implementer and reviewer (read-only) |
| `set-status.cypher`  | `slugs` (list), `status` (`pending` / `in_progress` / `failed` / `cancelled`) | `slug`, `status` per changed node | run |
| `status.cypher`      | —                         | one row per node: `state`, `wave`, `waiting_on`, review summary, timestamps | status (human report) |
| `node.cypher`        | `slug`                    | one node in full: properties, `inputs` (with `from`), `outputs`, `depends_on`, `satisfies`, `reviews` (`attempt`, `verdict`, `failed_criteria`, `checklist`, `at`) | plan (reopen), ad hoc |
| `feature.cypher`     | —                         | `destination`, `context`, `out_of_scope`, `acceptance` (with `covered_by`) | review, pr |

Ready-made ad-hoc queries (lineage, critical path, repair history, …) are in
`${CLAUDE_PLUGIN_ROOT}/reference/queries.md`.
