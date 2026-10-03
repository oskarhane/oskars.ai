---
description: Performs a strict end-of-feature maintainability audit of a gbuild feature branch — abstraction quality, file size, spaghetti growth, cross-node duplication, missed code-judo simplifications. Runs the audit in the gbuild-auditor sub-agent, in the feature's worktree, and relays its result to chat. Use after /gbuild:run finishes a graph, before /gbuild:pr.
---

Run the strict end-of-feature maintainability audit in a dedicated sub-agent, then relay its result.

This is not a second pass at what `gbuild-reviewer` already did. That agent grades one node against one
contract; this one grades what the whole accumulated diff did to the codebase — the duplication and
missed abstractions that only exist *between* nodes, which no per-node review can see.

## Arguments

`$ARGUMENTS` is optional. If present, treat it as the feature slug. If absent, infer it — if exactly one
feature worktree exists (`<git-common-dir>/gbuild/*/tree`), that's the slug; otherwise fall back to the
most recently modified `graph.json` under `<git-common-dir>/gbuild/*/tree/.gbuild/*/db` (or, for
features charted before the worktree layout, `.gbuild/*/db/graph.json` in the main tree). Do NOT write
any file — this skill outputs to chat exclusively.

Resolve `FT`, the feature worktree, exactly as `/gbuild:run`'s step 0 describes (reuse the registered
worktree, attach if the feature branch is checked out nowhere). `DB` below is `FT/.gbuild/<slug>/db`.

Store rules: run `cypherlite --version` first (missing → stop; gbuild needs it). One `cypherlite`
command at a time, always `--mode jsonl` (no output = no rows); on `storage locked` wait and retry up to
3 times. Anything else: `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`.

Check the graph is finished — one row per wave, cheap:

```
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher
```

If any row's `open` is non-empty, say the graph isn't finished (name the open nodes) and ask whether to
audit anyway — auditing a half-built branch produces findings that the remaining nodes were going to
address.

## Run the audit

Fetch the feature context:

```
cypherlite DB --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/feature.cypher
```

Launch the `gbuild-auditor` subagent (agents/gbuild-auditor.md — this plugin's own copy, gbuild does not
depend on hone-ai being installed). Pass it:

- The resolved slug and the `feature.cypher` result verbatim (destination and the acceptance bar with
  the nodes covering each criterion) — the auditor never opens the store itself, and reads the code from
  the branch diff.
- The feature worktree path `FT` and the feature branch name — it audits the branch's code from `FT`:
  every read, every check, and every git command runs there, never in the main tree.

The sub-agent runs the full audit in its own fresh context and returns the audit as its final message.
That message is a tool result — it is NOT shown to the user. So once it returns:

**Relay the sub-agent's entire output to chat verbatim, preserving its closing line exactly.** Do not
summarize, reorder, or rewrite it. The closing line is a contract:

- `Run /gbuild:plan <slug> --add "the above blocking issues"` — `plan`'s Reopen path resolves
  `the above blocking issues` as a back-reference to the relayed audit.
- `Nothing blocking.` followed by `next: /gbuild:pr <slug>` — that exact `Nothing blocking.` text is
  what any caller looping review→fix parses to end the loop.

Both must appear verbatim in the chat output for the rest of the chain to work.
