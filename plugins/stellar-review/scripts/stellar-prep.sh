#!/usr/bin/env bash
# stellar-prep.sh — deterministic pipeline inputs for the scripted
# stellar review (ADR-0271). Bundled with the stellar-review plugin;
# the pipeline tools are resolved from this script's own location
# (scripts/../skills/stellar-review/tools), so the script works from
# any install path — Claude Code marketplace checkout, npm package, or
# a local plugin directory — with no repo-side copy of the tools.
#
#   stellar-prep.sh model         — facts → fetch ledger → scope → expand → briefs
#   stellar-prep.sh post          — same minus briefs (the Post step recomputes
#                                   everything itself, so only findings.json is
#                                   model output; .stellar/facts|scope|ledger
#                                   written by the model step are discarded)
#   stellar-prep.sh local [--quick] [PR #] — the pre-push mirror of model
#                                   mode: the same pipeline body with the
#                                   inputs derived from the checkout
#                                   instead of the CI workflow env (the
#                                   scope rule of SKILL.md Step 0). The PR
#                                   number is optional — no argument means
#                                   the PR for the current branch if one
#                                   exists; no PR means round-1 semantics
#                                   (no ledger fetch, empty ledger).
#                                   --quick is the cheap mid-work sanity
#                                   check: delta-only scope (no
#                                   dependency-dirty expansion) and one
#                                   brief per pass (no sharding). Quick is
#                                   a PRE-FILTER, never a gate — quick
#                                   catches what the delta touches; the
#                                   full round (carried ledger + expansion
#                                   + shards) is still mandatory before
#                                   every push.
#
# model/post env: BASE_SHA HEAD_SHA REPO PR_NUMBER GH_TOKEN
# local env: none — the repo's own remote and gh auth serve the fetches.
#            STELLAR_BASE_REF (optional) overrides the default-branch
#            remote ref used for round-1 merge bases (origin/main);
#            set it to e.g. origin/master when the default branch is
#            not main.
set -euo pipefail

# The endpoint fetch and merge-base resolution are shared with the
# per-kind review pre-step (opencode-review-prep.sh) — one spelling.
. "$(dirname "$0")/lib/review-endpoints.sh"

MODE="${1:?usage: stellar-prep.sh model|post|local [--quick] [PR_NUMBER]}"
shift

# --quick is a local-mode flag; the PR number is the only other argument.
QUICK=0
PR_ARG=
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --*)
      echo "stellar-prep.sh: unknown flag: $arg" >&2
      exit 2
      ;;
    *)
      if [ -n "$PR_ARG" ]; then
        echo "stellar-prep.sh: unexpected argument: $arg" >&2
        exit 2
      fi
      PR_ARG="$arg"
      ;;
  esac
done
if [ "$QUICK" -ne 0 ] && [ "$MODE" != "local" ]; then
  echo "stellar-prep.sh: --quick is a local-mode flag" >&2
  exit 2
fi

# The pipeline tools live in the plugin's skill directory, resolved from
# this script's own location — see the header comment.
T="$(cd "$(dirname "$0")/../skills/stellar-review/tools" && pwd)"

fetch_ledger() {
  # the PR's summary comment is the ledger's transport (ADR-0271)
  python3 "$T/post.py" fetch-ledger --repo "$REPO" --pr "$PR_NUMBER" \
    --out .stellar/ledger.json
}

validated_last_head() {
  # the ledger rides the PR summary comment (or a stale local round);
  # never feed an unvalidated value to git
  local last
  last=$(jq -r '.last_head // empty' .stellar/ledger.json)
  if [ -n "$last" ] && ! [[ "$last" =~ ^[0-9a-f]{40}$ ]]; then
    echo "stellar-prep: ignoring malformed ledger last_head: $last" >&2
    last=
  fi
  printf '%s' "$last"
}

fetch_last_head() {
  # Best effort, and only when the commit is actually missing: a
  # --depth=1 fetch of an already-present LAST rewrites the shallow
  # boundary and can sever the commit from parents the repo already
  # has (observed dogfooding local mode AND live in CI: the
  # merge-base resolved during input derivation, then incremental.py
  # got no-common-ancestor and the anchoring patch degraded to
  # empty). incremental.py handles an unreachable last_head either
  # way (empty anchoring patch). Local fetches ride the repo's own
  # credentials; the CI modes authenticate inline.
  if git cat-file -e "$LAST^{commit}" 2>/dev/null; then
    return 0
  fi
  if [ "$MODE" = "local" ]; then
    # the stderr asymmetry is intended: a missing LAST after a
    # rebase/force-push is routine local noise, while the CI arm keeps
    # fetch errors visible in the pipeline log
    git fetch --depth=1 origin "$LAST" 2>/dev/null || true
  else
    # the CI arm fetches through the endpoint library's git_authed —
    # the one authenticated fetch spelling (the round-6 pin set and
    # the round-9 credential channel): the token rides git's
    # env-numbered configuration channel, never the command line a
    # surviving model-spawned process could read through ps, and the
    # invocation carries the full per-invocation pin set (an insteadOf
    # rewrite to an ext:: URL is refused, and a model-crafted
    # .git/hooks script never executes)
    git_authed "$AUTH" fetch --depth=1 origin "$LAST" || true
  fi
}

# ---------------------------------------------------------------------------
# Inputs. model/post read the CI workflow's env; local derives everything
# from the checkout and ensures .stellar/ledger.json up front (the body
# below reads it before its own ledger fetch point).
# ---------------------------------------------------------------------------

if [ "$MODE" = "local" ]; then
  mkdir -p .stellar
  PR_NUMBER="$PR_ARG"
  if [ -z "$PR_NUMBER" ]; then
    # no argument: the PR for the current branch, if one exists
    PR_NUMBER=$(gh pr view --json number --jq .number 2>/dev/null || true)
  fi
  HEAD_SHA=$(git rev-parse HEAD)
  if [ -n "$PR_NUMBER" ]; then
    REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
    fetch_ledger
  elif [ ! -f .stellar/ledger.json ]; then
    # round 1: no PR and no previous local round — boot from the empty
    # ledger (one canonical spelling: ledger.empty_ledger())
    PYTHONPATH="$T" python3 -c 'import json, ledger
with open(".stellar/ledger.json", "w") as fh:
    json.dump(ledger.empty_ledger(), fh, indent=1, sort_keys=True)
    fh.write("\n")'
  fi
  # BASE selection is the SCOPE RULE — the one spelling of it lives in
  # SKILL.md Step 0; this is the implementation, not a second statement.
  LAST=$(validated_last_head)
  if [ -n "$LAST" ] && git merge-base --is-ancestor "$LAST" "$HEAD_SHA" 2>/dev/null; then
    BASE_SHA="$LAST"
  fi
  # diverged or missing LAST (rebase onto advanced main): the default
  # branch's merge-base, as CI's pull_request.base.sha — never
  # merge-base(LAST, HEAD), which re-includes main's whole advance
  # (LABS-955). STELLAR_BASE_REF (header comment) overrides origin/main
  # for repos whose default branch is not main.
  BASE_REF="${STELLAR_BASE_REF:-origin/main}"
  if [ -z "${BASE_SHA:-}" ]; then
    BASE_SHA=$(git merge-base HEAD "$BASE_REF")
  fi
  echo "local round inputs: quick=$QUICK PR=${PR_NUMBER:-none} base=$BASE_SHA head=$HEAD_SHA"
else
  : "${BASE_SHA:?stellar-prep.sh $MODE: BASE_SHA required}"
  : "${HEAD_SHA:?stellar-prep.sh $MODE: HEAD_SHA required}"
  : "${REPO:?stellar-prep.sh $MODE: REPO required}"
  : "${PR_NUMBER:?stellar-prep.sh $MODE: PR_NUMBER required}"
  : "${GH_TOKEN:?stellar-prep.sh $MODE: GH_TOKEN required}"
fi

# ---------------------------------------------------------------------------
# The one pipeline body — model, post, and local all run exactly this.
# ---------------------------------------------------------------------------

run_pipeline() {
  # actions/checkout on pull_request lands the merge ref at depth 1;
  # facts.py reads trees by SHA, so fetch both endpoints explicitly.
  # Credentials are not persisted, so each fetch authenticates inline and
  # nothing token-bearing survives into the model step. Local mode needs
  # no fetch: every SHA it resolves (HEAD, the merge base, an ancestor
  # last_head) is already in the checkout. The fetch, the deepen loop
  # and the merge-base resolution are lib/review-endpoints.sh's — the
  # one spelling, shared with the per-kind lanes' pre-step.
  if [ "$MODE" != "local" ]; then
    AUTH=$(review_auth "$GH_TOKEN")
    MB=$(fetch_review_base "$AUTH" "$BASE_SHA" "$HEAD_SHA")
  else
    MB=$(git merge-base "$BASE_SHA" "$HEAD_SHA" 2>/dev/null || true)
  fi
  # The PR's real diff is merge-base...head, not base-tip..head: when the
  # branch is behind main, a two-dot diff includes main's newer commits
  # REVERSED, and the review would flag code the PR never touched.
  BASE="${MB:-$BASE_SHA}"
  echo "review base: $BASE (merge-base of $BASE_SHA and $HEAD_SHA)"
  NCOMMITS=$(git rev-list --count "$BASE..$HEAD_SHA" 2>/dev/null || echo 0)
  if [ "$NCOMMITS" -gt 1 ]; then
    echo "::warning::stellar: PR has $NCOMMITS commits; squash into one before review so rebases resolve once (LABS-311)"
  fi

  python3 "$T/facts.py" --base "$BASE" --head "$HEAD_SHA" --out .stellar/facts.json

  if [ "$(jq -r .has_code_changes .stellar/facts.json)" = "false" ]; then
    echo 'SCRIPTED_NOOP=true' >> "${GITHUB_ENV:-/dev/null}"
    exit 0
  fi

  # local mode ensured the ledger while deriving its inputs; model/post
  # fetch it here, after the docs-only gate, exactly as before
  if [ "$MODE" != "local" ]; then
    fetch_ledger
  fi
  python3 "$T/ledger.py" scope --facts .stellar/facts.json --ledger .stellar/ledger.json --out .stellar/scope.json

  jq -r '.dependency_dirty_files[]' .stellar/scope.json > .stellar/expand.txt
  # quick is delta-only: the dependency-dirty expansion — the main
  # scope/time ballooner — runs in the full round only
  if [ "$QUICK" -ne 1 ] && [ -s .stellar/expand.txt ]; then
    python3 "$T/facts.py" --base "$BASE" --head "$HEAD_SHA" --out .stellar/facts.json --include-units-file .stellar/expand.txt
    python3 "$T/ledger.py" scope --facts .stellar/facts.json --ledger .stellar/ledger.json --out .stellar/scope.json
  fi

  # The incremental diff (last round's head → this head) is computed in
  # every mode: the model/local steps embed it in briefs, and the post
  # step passes it to the poster, which drops findings that do not
  # intersect its hunks in incremental rounds (ADR-0275).
  LAST="${LAST:-$(validated_last_head)}"
  rm -f .stellar/diff-incremental.patch
  if [ -n "$LAST" ] && [ "$LAST" != "$HEAD_SHA" ]; then
    # A force-push/rebase leaves LAST unreachable or diverged; incremental.py
    # picks the smallest covering base (LAST, else merge-base(LAST, head),
    # never the main merge-base) and restricts the patch to PR-changed files
    # (LABS-311, ADR-0292).
    fetch_last_head
    python3 "$T/incremental.py" --facts .stellar/facts.json --ledger .stellar/ledger.json --out .stellar/diff-incremental.patch
  fi

  # post recomputes the briefs itself; model (CI) and local run them here.
  # --quick means one brief per pass (ledger.py brief --no-shard); model
  # tiers are the caller's (the skill's tier guidance / STELLAR_MODEL_*),
  # never this script's.
  if [ "$MODE" != "post" ]; then
    NO_SHARD=
    if [ "$QUICK" -eq 1 ]; then
      NO_SHARD="--no-shard"
    fi
    if [ -s .stellar/diff-incremental.patch ]; then
      python3 "$T/ledger.py" brief --facts .stellar/facts.json --scope .stellar/scope.json --diff .stellar/diff-incremental.patch ${NO_SHARD:+$NO_SHARD} --out .stellar/briefs
    else
      python3 "$T/ledger.py" brief --facts .stellar/facts.json --scope .stellar/scope.json ${NO_SHARD:+$NO_SHARD} --out .stellar/briefs
    fi
  fi

  echo '--- scope:'
  jq '.stats, .resolve_checks' .stellar/scope.json
}

run_pipeline
