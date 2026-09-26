---
description: Performs a strict end-of-feature maintainability audit of the current gbuild branch — abstraction quality, file size, spaghetti growth, cross-node duplication, missed code-judo simplifications. Runs the audit in the gbuild-auditor sub-agent and relays its result to chat. Use after /gbuild:run finishes a graph, before /gbuild:pr.
---

Run the strict end-of-feature maintainability audit in a dedicated sub-agent, then relay its result.

This is not a second pass at what `gbuild-reviewer` already did. That agent grades one node against one
contract; this one grades what the whole accumulated diff did to the codebase — the duplication and
missed abstractions that only exist *between* nodes, which no per-node review can see.

## Arguments

`$ARGUMENTS` is optional. If present, treat it as the feature slug. If absent, infer it — the current
branch commonly ends in the slug (`plan` checks out `<prefix>/<slug>`), otherwise fall back to the store
whose `.gbuild/*/db/graph.json` was most recently modified. Do NOT write any file — this skill outputs to
chat exclusively.

Store rules: run `cypherlite --version` first (missing → stop; gbuild needs it). One `cypherlite`
command at a time, always `--mode jsonl` (no output = no rows); on `storage locked` wait and retry up to
3 times. Anything else: `${CLAUDE_PLUGIN_ROOT}/reference/cypher.md`.

Check the graph is finished — one row per wave, cheap:

```
cypherlite .gbuild/<slug>/db --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/progress.cypher
```

If any row's `open` is non-empty, say the graph isn't finished (name the open nodes) and ask whether to
audit anyway — auditing a half-built branch produces findings that the remaining nodes were going to
address.

## Run the audit

Fetch the feature context:

```
cypherlite .gbuild/<slug>/db --mode jsonl < ${CLAUDE_PLUGIN_ROOT}/cypher/feature.cypher
```

Launch the `gbuild-auditor` subagent (agents/gbuild-auditor.md — this plugin's own copy, gbuild does not
depend on hone-ai being installed). Pass it:

- The resolved slug and the `feature.cypher` result verbatim (destination and the acceptance bar with
  the nodes covering each criterion) — the auditor never opens the store itself, and reads the code from
  the branch diff.
- Tell it to audit the current branch.

The sub-agent runs the full audit in its own fresh context and returns the audit as its final message.
That message is a tool result — it is NOT shown to the user. So once it returns:

**Relay the sub-agent's entire output to chat verbatim, preserving its closing line exactly.** Do not
summarize, reorder, or rewrite it. The closing line is a contract:

- `Run /gbuild:plan <slug> --add "the above blocking issues"` — `plan`'s Reopen path resolves
  `the above blocking issues` as a back-reference to the relayed audit.
- `Nothing blocking.` followed by `next: /gbuild:pr <slug>` — that exact `Nothing blocking.` text is
  what any caller looping review→fix parses to end the loop.

Both must appear verbatim in the chat output for the rest of the chain to work.
