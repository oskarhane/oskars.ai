---
name: stellar-review
description: Strict maintainability review — abstraction quality, file size, spaghetti growth. Runs as a deterministic incremental pipeline (facts → ledger scope → briefs → focused passes → scripted verdict) so every blocker and medium surfaces in round 1 and untouched code never re-produces findings. Use for a stellar code quality review, deep quality audit, or harsh maintainability review.
disable-model-invocation: true
---

# Stellar Review

Unusually strict review of implementation quality, maintainability, and abstraction health. Push for **ambitious** restructurings — "code judo" moves that preserve behavior while making the code dramatically simpler, smaller, and more direct. Delete complexity; don't rearrange it.

This review is a **pipeline** (ADR-0271), not a reading. Scripts own everything mechanical — what changed, how big things are, where the branches/casts/fallbacks are, which units look alike, what was already decided. Model tokens buy exactly one thing: per-unit judgment over pre-digested briefs. Do not improvise around the steps, and never review a raw diff — that is the low-recall mode this pipeline replaced.

The tools live beside this file: `tools/facts.py` (git-side extraction), `tools/units.py` (language machinery), `tools/similar.py` (near-duplicates), `tools/ledger.py` (cross-round state), `tools/incremental.py` (stale-ledger-proof anchoring diff, ADR-0292), `tools/briefs.py` (pass briefs), `tools/post.py` (GitHub posting) — pure Python 3 stdlib. Pass mandates live in `passes/`, doctrine in `references/`. Runtime state lives in `.stellar/` (gitignored — when installing into a repo, add `.stellar/` to its .gitignore).

## Step 0 — facts, ledger, scope, briefs (scripts only)

**Local pre-push rounds ALWAYS run the script — never a hand-rolled subset of these steps.** The abbreviated hand-copy (facts → scope → briefs, skipping the ledger fetch and the dependency-dirty expansion) is exactly the divergence that let CI keep finding findings the local round never saw. One command, from the repository root, on the branch to review:

```sh
${CLAUDE_PLUGIN_ROOT}/scripts/stellar-prep.sh local [--quick] [PR_NUMBER]
```

`PR_NUMBER` is optional: given → that PR's ledger is fetched from its summary comment; absent → the PR for the current branch, if one exists; no PR at all → round-1 semantics (no ledger fetch, empty ledger). The script derives the inputs CI's `model` mode reads from its env — base per the SCOPE RULE below, head = HEAD — and runs the identical pipeline body (ledger → facts → docs-only gate → scope → dependency-dirty expansion → incremental diff → briefs), writing `.stellar/facts.json`, `.stellar/scope.json`, `.stellar/briefs/`. CI's `model` mode and the local round are the same code path: `stellar-prep.sh` is the one entry point. Then dispatch the four passes over `.stellar/briefs/` (Step 2). If the repository's default branch is not `main`, export `STELLAR_BASE_REF` (e.g. `origin/master`) first — it overrides the round-1 merge-base ref.

`--quick` is the cheap mid-work sanity check: delta-only scope (the dependency-dirty expansion is skipped) and one brief per pass (no sharding, however big the round). Model tiers are unchanged — the tier guidance and `STELLAR_MODEL_*` overrides below apply as-is; the script never configures models. **Quick is a PRE-FILTER, never a gate — quick catches what the delta touches; the full round (carried ledger + expansion + shards) is still mandatory before every push.**

What each mode catches:

- **Full round (the mandatory pre-push gate)** reviews the delta PLUS the carried ledger's earlier-round units PLUS the dependency-dirty expansion (callers/callees of changed units) — approximately what CI's round will judge. Cost: more units, sharded briefs, all four passes at their configured tiers — the expensive but CI-faithful shape.
- **Quick round (mid-work pre-filter)** reviews ONLY the delta's changed units, one shard per pass — it catches what your own edit touches (structure/branching shape in the code you just wrote) and misses anything CI anchors via earlier rounds or dependency expansion (the observed failure class: findings on pre-existing callers pulled into scope). Cheap, fast, NOT a gate.

A clean quick round does NOT predict a clean CI round; a clean full round is the best local predictor of CI's verdict — and even the full round differs from CI by model pinning (CI's `STELLAR_MODEL_*` secrets), so a local green is strong, not identical.

The rest of this section is the manual reference — the expansion of exactly what the script runs (and what CI's env-driven `model`/`post` modes do with workflow-provided inputs), kept for reading, not for hand-copying:

```sh
TOOLS=${CLAUDE_PLUGIN_ROOT}/skills/stellar-review/tools
mkdir -p .stellar

# facts (CI passes --base/--head from the PR payload; locally they default
# to merge-base HEAD origin/main → HEAD)
#
# SCOPE RULE (anti-balloon): when .stellar/ledger.json exists and its
# last_head is an ancestor of HEAD, ALWAYS pass --base <last_head> --head
# HEAD. The main merge-base default is for round 1 (no ledger) only — using
# it on an existing PR re-judges the entire PR diff and balloons the scope
# (891+ units, hours of pass time). After a force-push/rebase (last_head
# not an ancestor of HEAD), pass --base <merge-base HEAD origin/main> — never
# the merge-base of the old and new heads, which re-includes main's advance.
python3 $TOOLS/facts.py --out .stellar/facts.json

# ledger: CI fetches it from the PR summary comment; locally it is a file
# CI:   python3 $TOOLS/post.py fetch-ledger --repo $REPO --pr $PR --out .stellar/ledger.json
# local: .stellar/ledger.json already exists from the last round, or not (round 1)

python3 $TOOLS/ledger.py scope --facts .stellar/facts.json --ledger .stellar/ledger.json --out .stellar/scope.json

# dependency expansion: if scope.json lists dependency_dirty_files, rerun
# facts with them included, then rerun scope:
jq -r '.dependency_dirty_files[]' .stellar/scope.json > .stellar/expand.txt
# (if non-empty) python3 $TOOLS/facts.py --out .stellar/facts.json --include-units-file .stellar/expand.txt
# (and rerun the scope command above)

# briefs: incremental rounds embed the since-last-round diff; round 1 omits it
LAST=$(jq -r '.last_head // empty' .stellar/ledger.json)
HEAD=$(jq -r '.head' .stellar/facts.json)
if [ -n "$LAST" ] && [ "$LAST" != "$HEAD" ]; then
  # never raw `git diff $LAST $HEAD`: after a force-push/rebase LAST is stale
  python3 $TOOLS/incremental.py --facts .stellar/facts.json --ledger .stellar/ledger.json --out .stellar/diff-incremental.patch
  python3 $TOOLS/ledger.py brief --facts .stellar/facts.json --scope .stellar/scope.json --diff .stellar/diff-incremental.patch --out .stellar/briefs
else
  python3 $TOOLS/ledger.py brief --facts .stellar/facts.json --scope .stellar/scope.json --out .stellar/briefs
fi
```

## Step 1 — gates (no model tokens)

- `facts.has_code_changes` is `false` → docs/CI-only diff. Stop. (CI: the workflow already ran `post.py noop`.)
- `scope.stats.units_in_scope` is `0` **and** `scope.resolve_checks` is empty → nothing new to judge. Write `{"version": 1, "findings": [], "resolutions": [], "coverage": [], "notes": "nothing changed since last round"}` to `.stellar/findings.json` and go to Step 4. Open findings from earlier rounds are carried by the ledger — the poster re-states them; you do not.

## Step 2 — dispatch the passes (parallel sub-agents)

For **each** file in `.stellar/briefs/` (`brief-structure[-N].md`, `brief-branching[-N].md`, `brief-boundaries[-N].md`, `brief-comparison.md`), dispatch one sub-agent — the `stellar-structure`, `stellar-branching`, `stellar-boundaries`, `stellar-comparison` agents are bundled with this plugin at `${CLAUDE_PLUGIN_ROOT}/agents/`. Claude Code registers them as plugin agents; under OpenCode (see the runtime notes appended to this skill) dispatch the built-in `general` subagent with that agent file to read. Dispatch all of them in parallel. Prompt per agent:

> Stellar review round <N>. Your brief is `.stellar/briefs/<file>` — read it fully, then follow your standing instructions (mandate + doctrine + JSON output). Return only your JSON document.

Never merge two briefs into one dispatch, and never dispatch a pass without its brief — the isolated contexts and pre-digested inputs are what make the passes exhaustive and fast.

If a pass agent fails to dispatch or errors, stop and report the failure — never assemble or post a partial review; a missing pass is not an empty pass.

MODEL TIERS (cost/speed): the passes are mechanical checklist reads against pre-digested briefs.

Per-pass model overrides (ADR-0302): `STELLAR_MODEL_<PASS>` (`STELLAR_MODEL_STRUCTURE`, `STELLAR_MODEL_BRANCHING`, `STELLAR_MODEL_BOUNDARIES`, `STELLAR_MODEL_COMPARISON`) overrides that pass's sub-agent model; unset or empty = no override — the tier guidance below applies.
- **CI**: the workflow exports each non-empty `STELLAR_MODEL_<PASS>` into the review run's environment; the dispatcher applies them exactly as the local arm does.
- **Local**: a dispatcher that can set a per-dispatch model runs `printenv STELLAR_MODEL_<PASS>` before dispatch and passes a non-empty value as that pass's model, in the dispatcher's own model syntax (OpenCode `provider/model`, a Claude Code alias such as `haiku`).

Tier guidance: dispatch `stellar-boundaries` and `stellar-comparison` on the cheapest fast model your dispatcher supports (e.g. `model: haiku`); `stellar-branching` on the mid model (e.g. `model: sonnet`); keep `stellar-structure` on the default/strong model — decomposition and 1k-line judgment is the one pass that genuinely needs it. A finding dropped by a cheap pass is usually caught by its siblings or by CI's full-strength round; the cost asymmetry favors cheap local passes.

## Step 3 — assemble findings.json

Collect each agent's JSON document. Concatenate `findings`, `resolutions`, and `coverage` arrays. Write exactly one file, `.stellar/findings.json`:

```json
{"version": 1, "findings": [...], "resolutions": [...], "coverage": [...], "notes": ""}
```

Sanity-check before writing: every finding has `area`, `severity` (`blocker|medium|nit`), `path`, `start_line`, `quote`, `why`, `remedy`; every finding's `unit` (when present) is a unit the scope actually assigned; no finding quotes code from a sealed unit; in incremental rounds, every finding's lines intersect the incremental diff hunks. Drop violations — they are process errors, not findings (the poster drops them anyway: scope membership and incremental anchoring are script-enforced, ADR-0275). This file is the **only** file you may write.

## Step 4 — hand off

- **CI**: stop here. The workflow runs `post.py`, which rolls the ledger, posts one review with all inline comments, derives the verdict, and updates the summary comment.
- **Local**: roll the ledger and print the report yourself:
  ```sh
  python3 ${CLAUDE_PLUGIN_ROOT}/skills/stellar-review/tools/ledger.py update --facts .stellar/facts.json --ledger .stellar/ledger.json \
      --findings .stellar/findings.json --scope .stellar/scope.json
  ```
  Then print: round number, scope stats, findings grouped by severity (blocker → medium → nit, with `path:lines`, why, remedy), resolution outcomes, and the approval-bar verdict (`references/full-checklist.md`). Direct, serious, demanding tone; a small set of well-evidenced findings beats a wall of nits — but nothing medium or higher is ever held back.

## What changed from the old skill (for anyone surprised)

- No `git diff` reading, ever. Facts and briefs are pre-digested and identical every round for the same code.
- The verify pass is gone; the **comparison** pass catches the same defect class (inconsistency between similar sites) from similarity groups instead of a fifth full read.
- Round 2+ reviews only what changed since round 1 (plus signature-affected dependents and resolution checks). Everything else is sealed — new findings on untouched code are a process violation.
- Posting and verdict are scripts. The model writes `.stellar/findings.json` and nothing else.
