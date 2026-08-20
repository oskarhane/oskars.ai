---
description: Performs a strict end-of-feature maintainability audit of the current gbuild branch — abstraction quality, file size, spaghetti growth, cross-node duplication, missed code-judo simplifications. Runs the audit in the gbuild-auditor sub-agent and relays its result to chat. Use after /gbuild:run finishes a graph, before /gbuild:pr.
---

Run the strict end-of-feature maintainability audit in a dedicated sub-agent, then relay its result.

This is not a second pass at what `gbuild-reviewer` already did. That agent grades one node against one
contract; this one grades what the whole accumulated diff did to the codebase — the duplication and
missed abstractions that only exist *between* nodes, which no per-node review can see.

## Arguments

`$ARGUMENTS` is optional. If present, treat it as the feature slug. If absent, infer it — the current
branch commonly ends in the slug (`plan` checks out `<prefix>/<slug>`), otherwise fall back to the most
recently modified `.gbuild/*/graph.json`. Do NOT write any file — this skill outputs to chat exclusively.

Run `python3 <plugin>/scripts/graph.py .gbuild/<slug>/graph.json --status` first. If the frontier is
non-empty or nodes are still `in_progress`, say the graph isn't finished and ask whether to audit anyway
— auditing a half-built branch produces findings that the remaining nodes were going to address.

## Run the audit

Launch the `gbuild-auditor` subagent (agents/gbuild-auditor.md — this plugin's own copy, gbuild does not
depend on hone-ai being installed). Pass it:

- The resolved slug and its `.gbuild/<slug>/graph.json` path.
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
