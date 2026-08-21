---
description: Pushes the current gbuild feature branch to the appropriate remote, opens a pull request with a concise description that classifies the change (new feature, fix, optimization, etc.) and notes any user-facing impact, then monitors CI checks in the background and auto-triggers a graph reopen + run if any fail. Use after /gbuild:review reports nothing blocking, to publish the finished feature branch.
---

Publish a finished feature branch: push it to the right remote, open a well-formed pull request, then watch the PR's CI checks and drive a graph reopen automatically when a check goes red — looping until the checks are green or a round cap is hit.

## CRITICAL: main-context requirement

This skill MUST run in the **main conversation context**. It MUST NOT be invoked as a forked subagent (e.g. via the Agent/Task tool). The auto-fix step runs `/gbuild:run`, which dispatches one Agent per node — and forked agents cannot nest, so a nested fork will fail. If you are already running inside a forked agent, stop immediately and report that `/gbuild:pr` must be run from the top-level conversation.

## Step 0: Parse arguments

`$ARGUMENTS` is free-form text: an optional feature slug and an optional `--max-rounds N` flag.

- **slug**: the first token that isn't a flag. If absent, infer it — the current branch commonly ends in the slug (`plan` checks out `<prefix>/<slug>`), otherwise fall back to the most recently modified `.gbuild/*/graph.json`. If neither resolves, leave `<slug>` unresolved (the auto-fix step degrades gracefully — see Step 4).
- **max_rounds**: the value of `--max-rounds N` (also accept `--max-rounds=N`). Default `3` when absent.

## Step 1: Preconditions

Verify the environment before touching the remote. Stop with a clear, actionable message if any check fails:

1. **Git repo.** This skill is git + GitHub specific. If the repo is not git, stop and explain that `/gbuild:pr` only supports git + GitHub (`gh`).
2. **GitHub CLI.** Confirm `gh` is installed and authenticated (`gh auth status`). If not, stop and tell the user to install/authenticate `gh`.
3. **Base branch.** Determine the upstream default branch: `gh repo view --json defaultBranchRef -q .defaultBranchRef.name`. Call it `<base>`.
4. **Not on base.** Get the current branch (`git branch --show-current`). If it equals `<base>`, stop — there is nothing to open a PR for.
5. **Clean tree.** Check for uncommitted changes (`git status --porcelain`). `/gbuild:run` commits each node's work as it goes, so the tree should be clean. If there are uncommitted changes, warn the user and ask whether to proceed (they may want to commit first).
6. **Commits ahead of base.** Confirm the branch has commits the base lacks (`git log <base>..HEAD --oneline`). If empty, stop — nothing to push.
7. **Graph finished.** When `<slug>` resolved, run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/graph.py .gbuild/<slug>/graph.json --status`. If the frontier is non-empty or nodes are still `in_progress`, warn that the graph isn't finished and ask whether to open the PR anyway. If any node is `failed`, name it — a PR built on an escalated node is usually premature.

## Step 2: Determine the remote & push

Choose the push remote from the project's actual remotes:

1. List remotes (`git remote -v`).
2. **Exactly one remote** → use it.
3. **Multiple remotes** → look for a push-target hint in `AGENTS.md` or `CLAUDE.md` (e.g. an explicit statement that the project pushes to a fork). If a clear hint exists, use it. Otherwise, use `AskUserQuestion` to let the user pick which remote to push to (e.g. `origin` vs a fork remote).

Push the current branch and set upstream: `git push -u <remote> <branch>`.

## Step 3: Open the pull request

Build a **short, well-formed** description, then open the PR.

Gather context from:

- Commit subjects: `git log <base>..HEAD --oneline`.
- File overview: `git diff <base>...HEAD --stat`.
- When present: the graph's `destination` and top-level `acceptance` from `.gbuild/<slug>/graph.json`, and the per-node `output` values in `.gbuild/<slug>/nodes/*.json`.

Derive a concise, conventional-commit-style title from the feature/branch and the changes (e.g. `feat(auth): add OAuth login`).

Write the body to this template. Keep it tight — bullets, not essays. Classify what kind of change this is (new feature, fix, optimization, replacement, refactor, or other) and lead with that. Most changes are not user-facing — only include the **User-facing impact** section when something a user actually interacts with (API, CLI, config, UI, output) changed; omit it entirely otherwise. Omit any section that has nothing:

```
## Summary
<1–2 sentences: what changed & why, and the kind of change — new feature / fix / optimization / replacement / refactor / other>

## Changes
- <bullet per notable change — what it does, not a play-by-play>

## User-facing impact
<Only when the change is user-facing: what users will now see or do differently (inputs and/or outputs). Drop this whole section for internal-only changes.>

---
This description was auto generated
```

The trailing `This description was auto generated` line is **mandatory** — it always ends the body, after every other section, and is never dropped or reworded.

Create the PR: `gh pr create --base <base> --title "<title>" --body "<body>"`. Let `gh` resolve the head branch (it handles fork `owner:branch` head refs automatically). Capture the PR URL and number (`<pr>`).

## Step 4: Monitor checks in the background → auto-fix loop

Watch the PR's CI checks and react when they fail. Run for at most `max_rounds` rounds:

1. **Launch the watch in the background.** Run `gh pr checks <pr> --watch --fail-fast` via the Bash tool with `run_in_background: true`. It exits `0` when all checks pass and non-zero when a check fails; the harness re-invokes this skill when the command exits, so continue from the result.
2. **Checks green (exit 0):** report success and go to Step 5.
3. **Checks red (non-zero exit):**
   - Collect the failure detail: `gh pr checks <pr>` for the failed-check list, and `gh run view <run-id> --log-failed` for the failing logs.
   - **If `<slug>` is unresolved** (the branch wasn't produced by gbuild, so there's no graph to reopen): do not auto-fix. Print which checks failed with their logs and suggest the user fix manually, then go to Step 5 with an `unresolved` status.
   - **Otherwise, fix automatically** — via the graph, not by patching around it. gbuild has no separate fix skill; a red check is a new requirement:
     1. Read `${CLAUDE_PLUGIN_ROOT}/skills/plan/SKILL.md` and execute its **Reopen** path inline: `--add "<requirement>"` where the requirement is the failing check stated as a concrete outcome (e.g. `CI check "lint" passes — <the actual error>`). Re-read that file and follow it verbatim rather than paraphrasing it here, so this phase auto-syncs when `plan` changes. One requirement per distinct failing check.
     2. Run it unattended. `plan`'s Reopen asks nothing, but if executing it would prompt the user (an ambiguous decomposition), resolve it yourself from the failing logs and note the choice in the final report — `/gbuild:pr` runs without a human present.
     3. If Reopen concludes the requirement needs no new nodes, stop the loop and go to Step 5 with an `unresolved` status — the failure isn't something the graph can act on, so surface the logs to the user.
     4. Read `${CLAUDE_PLUGIN_ROOT}/skills/run/SKILL.md` and execute it inline against `<slug>` to run the newly-unblocked frontier. Suppress its trailing `next: /gbuild:status…` line — this skill owns the transition.
   - After the run completes, push the new commits (`git push`) and **re-launch the watch** (next round).

4. **Round cap reached while still red:** stop, print the still-failing checks and their logs, and tell the user to inspect manually. Go to Step 5 with an `unresolved` status.

## Step 5: Final output

Report the outcome:

```
PR: <url>  (checks: green | fixed after <rounds> round(s) | unresolved after <max_rounds> round(s))
next: /gbuild:status <slug>
```
