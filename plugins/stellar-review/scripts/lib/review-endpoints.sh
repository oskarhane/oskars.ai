# review-endpoints.sh — the one CI endpoint fetch and merge-base
# resolution for the stellar review pre-step, sourced by
# stellar-prep.sh (ADR-0271). Sourced, never
# executed: it defines the helpers every review pre-step needs on the
# actions/checkout depth-1 checkout, where credentials are not
# persisted (persist-credentials: false) so every fetch authenticates
# inline and nothing token-bearing survives into a model step.
#
# Every fetch carries the full per-invocation git pin set (the round-6
# finding, and the same six pins review-restore.sh and the workflow's
# staging git show carry): -c core.fsmonitor= -c core.pager=cat
# -c core.worktree=. -c protocol.ext.allow=never
# -c core.attributesFile= -c core.hooksPath=/dev/null — the post steps
# run these fetches after the model step, on a checkout whose
# .git/config the model shell could have written (the restore
# choreography replaces it, and the pins hold the knobs closed even
# where the replacement has not run): a model-written url.<url>.insteadOf
# can otherwise rewrite the origin URL to an ext:: command, which
# protocol.ext.allow=never refuses, and the hooksPath pin keeps a
# model-crafted .git/hooks script from executing in any git call the
# fetch path runs (the round-9 finding, probed on git 2.43/2.54: an
# undefended reset --hard executes a model-written
# .git/hooks/reference-transaction — the pin redirects every hook
# lookup to /dev/null, where none is found).
#
# The GitHub credential reaches git through its env-numbered
# configuration channel, never the command line (the round-9 Medium
# finding: a surviving model-spawned process can read any process's
# arguments through ps, and the old spelling carried the token as an
# inline http extraheader config argument on the fetch argv).
# git_authed below is the one authenticated git invocation: the count
# and the key are fixed literals of the committed script, and the
# value is the auth argument the caller assembled from its step's
# GH_TOKEN — nothing
# model-writable is consulted. The channel is command-scoped, so the
# GIT_CONFIG_COUNT=0 pin every token-bearing step and
# review-restore.sh carry keeps holding for every other git call: a
# model-published GIT_CONFIG_KEY_n pair stays inert, and this one
# assignment raises the count to exactly 1 — the single fixed
# extraheader entry — for the fetch command alone.
#
# Requires git and coreutils base64 on PATH; no repository state beyond
# the object store is touched.

# review_auth TOKEN → the Authorization header value for GitHub's git
# http transport (the x-access-token user carries the workflow's token).
review_auth() {
	printf 'AUTHORIZATION: basic %s' "$(printf 'x-access-token:%s' "$1" | base64 -w0)"
}

# git_authed AUTH GIT-ARGS... → the one authenticated git invocation:
# the credential rides git's env-numbered configuration channel
# (GIT_CONFIG_COUNT/KEY_0/VALUE_0 — one fixed entry,
# http.<url>.extraheader), never the command line, and the invocation
# carries the full per-invocation pin set like every restore-path and
# fetch git call. Every authenticated fetch in the token-bearing review
# steps routes through it — fetch_review_base below and
# stellar-prep.sh's CI-arm LAST fetch.
git_authed() { # $1 = AUTH header value, rest = git arguments
	local auth=$1
	shift
	GIT_CONFIG_COUNT=1 \
	GIT_CONFIG_KEY_0='http.https://github.com/.extraheader' \
	GIT_CONFIG_VALUE_0="$auth" \
		git -c core.fsmonitor= -c core.pager=cat -c core.worktree=. -c protocol.ext.allow=never -c core.attributesFile= -c core.hooksPath=/dev/null "$@"
}

# fetch_review_base AUTH BASE_SHA HEAD_SHA → the merge-base SHA, or empty
# when none resolves even at depth 256. Fetches both endpoints at
# --depth=1 first (the checkout holds only the merge ref), then deepens
# in powers of two until the merge-base exists: the PR's real diff is
# merge-base...head, and resolving it needs just enough history to
# connect the endpoints — never the whole base branch. Both fetches
# authenticate through git_authed — the env-numbered channel, never a
# token on the command line.
fetch_review_base() { # $1 = AUTH header value, $2 = base SHA, $3 = head SHA
	local auth=$1 base=$2 head=$3 mb depth
	git_authed "$auth" fetch --depth=1 origin "$base" "$head"
	mb=$(git merge-base "$base" "$head" 2>/dev/null || true)
	depth=2
	while [ -z "$mb" ] && [ "$depth" -le 256 ]; do
		git_authed "$auth" fetch --deepen="$depth" origin "$base" "$head"
		mb=$(git merge-base "$base" "$head" 2>/dev/null || true)
		depth=$((depth * 2))
	done
	printf '%s' "$mb"
}
