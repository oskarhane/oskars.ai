---
description: Designs a feature with the human — the design step before /gbuild:plan charts it: analyses the codebase, drives the discussion in batched question rounds, and commits the design artifacts (docs/design/<slug>/, entry doc design.md) to the feature branch in its own git worktree, never touching the main checkout. Ends only when the human calls the design good; re-invoking with the slug resumes from the committed artifacts. Runs without cypherlite and without a store — use when the work needs shaping before it can be charted.
---

Design the feature described by `$ARGUMENTS` — with the human, before `/gbuild:plan` charts it.

`plan` decomposes a feature that already makes sense: a one-line destination, a scope with edges,
constraints it can verify against. When the work isn't there yet — the destination still has
options, the moving parts aren't named, the trade-offs are unmade — this skill shapes it into
committed artifacts first. It writes the design onto the feature branch and stops: no graph, no
store, no implementation. The committed artifacts are the design's whole state, so re-invoking
`/gbuild:design <slug>` resumes exactly where the commits left off. After it, `/gbuild:plan <slug>`
has a design to decompose instead of a guess.

## Mode

| arguments                                                 | mode                                                |
| --------------------------------------------------------- | --------------------------------------------------- |
| a description, link, or file path                         | **Design** — new feature                            |
| a slug with a feature worktree or branch, and no store    | **Resume** — continue the committed artifacts      |
| a slug whose store already exists                         | **Redirect** — `/gbuild:plan <slug> --add "<req>"`  |

`$ARGUMENTS` is slug-shaped only if it is one kebab-case token. Then, in order: a store at
`<git-common-dir>/gbuild/<slug>/db` (its `graph.json` present) means `plan` already charted the
feature — don't design a charted feature; say so and point at `/gbuild:plan <slug> --add
"<requirement>"`, which is how a charted feature takes new work. A feature worktree or a branch
named `<slug>` or ending `/<slug>`, with no store, means a design started here and wasn't charted —
resume it. Anything else is a description — design it.

## Design

### 1. Slug, branch, and feature worktree

Derive the feature slug from `$ARGUMENTS`: kebab-case, ≤4 words, names the outcome not the mechanism
(`oauth-device-flow`, not `add-some-auth-stuff`). It names the artifact home below and the
`gbuild/<slug>/` directory `plan` later creates — immutable once the design is committed.

gbuild never changes the branch of the user's checkout: the feature branch lives in its own **feature
worktree**, so several features can be designed, charted, and run in parallel without racing each
other's `HEAD`, and uncommitted work in the main tree is irrelevant — there is no dirty-tree check.
Resolve these paths, all absolute: `GC` = `git rev-parse --git-common-dir` (resolve it to an absolute
path), `WT` = `GC/gbuild/<slug>` — the feature's worktree root, inside `.git/` so nothing under it is
ever committed — and `FT` = `WT/tree`, the feature worktree, the one place the feature branch is
checked out. Then:

- `FT` is already a registered worktree (`git worktree list --porcelain`) → reuse it, say so.
- A branch named `<slug>` or ending `/<slug>` already exists → if it's checked out somewhere (a feature
  charted before the worktree layout usually has it in the main tree), that location is `FT`; otherwise
  attach it: `git worktree add FT <branch>`.
- Otherwise create branch and worktree in one step, forked from the current HEAD:

  ```
  git worktree add FT -b <prefix>/<slug> HEAD
  ```

  Take `<prefix>` from the repo's convention — project or user instructions first, else the dominant
  pattern in `git branch --list` — and fall back to `gbuild` when there is none.

That is `plan`'s step 1 verbatim in substance (`${CLAUDE_PLUGIN_ROOT}/skills/plan/SKILL.md`) — keep
the two in sync. If the derived slug's store already exists (`GC/gbuild/<slug>/db`), stop: the feature
is charted, and new work goes to `/gbuild:plan <slug> --add`. Report the branch and `FT`; everything
below happens in `FT`. If `docs/design/<slug>/` on that branch already has committed artifacts, this
is a resume that arrived as a description — read them (Resume below) instead of writing over them.

### 2. Analyse the codebase

Read the project manifest(s), directory structure, `README.md`, and the code the feature touches.
Resolve file paths or URLs in `$ARGUMENTS`; if a reference fails to load, say so and ask. For
related in-flight work — best-effort, never required: when `cypherlite` is on PATH, read the
`Feature` of every existing store (`feature.cypher` with `--read-only` against each `GC/gbuild/*/db`,
one at a time); when it isn't, skip — this skill needs neither `cypherlite` nor a store, and never
installs or creates either.

### 3. Fix the artifact home

The design artifacts live at `docs/design/<slug>/` on the feature branch; the entry doc is
`design.md`, and everything else hangs off it. Before writing anything, look at how the repo already
documents work — `docs/` layout, ADR or decision-record folders, README patterns — and follow an
existing convention when one is present: supporting docs take the repo's naming and format; only
the home and the entry doc are fixed here.

### 4. The design loop

The design is written by discussing it, one settled piece at a time. The loop runs until the human
calls the design good — never less, and never on your own judgement of when it's good enough.

1. **Open with what the analysis found.** A few lines: the pieces that exist, the gap, the
   constraints — grounding, not a report. End with the first batch of questions.
2. **Ask in batches.** Put the round's open questions to the human in one message — cap at ~5. The
   destination comes first, and it must end up one line, the thing that is true once this is done;
   everything past it is scope to defend or cut. Then what the destination needs decided: scope
   edges, naming, the trade-offs with real alternatives, the risks worth stating. Never one question
   at a time, and never 20 questions — a round with more than ~5 open questions hasn't converged:
   settle what the last answers gave you, and batch the rest into the next round.
3. **Settle as they solidify.** Fold each round's answers into the artifacts the moment they're
   agreed, and commit — message `docs(design/<slug>): <what settled>` — so an interruption costs
   nothing that had settled. `design.md` carries the state: the destination (one line), the scope
   and out-of-scope, what the analysis found, each decision with its rationale and the alternatives
   it ruled out, and the open questions still in play. Supporting docs — whatever this design
   needs: diagrams, data shapes, interface sketches — follow the repo's convention (step 3).
4. **An unknown that needs code is an open question, not a prototype.** Design writes no
   implementation — no scaffolding, no probes, no spike branches. A question the analysis can't
   answer by reading goes into `design.md`'s open questions for `/gbuild:plan` to chart as a
   `research` node.

### 5. Report and hand over

Only after the human has called the design good: ask nothing more, write and commit the last of it,
then report the artifacts (every file under `docs/design/<slug>/`), the branch, and `FT`. The feature
worktree stays — `plan` reuses it. Then both exits, the human's to pick:

- **Continue into gbuild** — `next: /gbuild:plan <slug>`.
- **A design review on a PR** — ask the agent to open it directly with `gh` from `FT` (push the
  branch, `gh pr create`): `/gbuild:pr` can't, it needs a graph store, and a design isn't charted.

## Resume

Re-invoking `/gbuild:design <slug>` continues a design the feature worktree or branch already holds —
the mode table routed you here:

0. Resolve `FT` exactly as step 1 describes — reuse the registered worktree, attach the branch if
   it's checked out nowhere. Never into the user's main checkout unless that's where the feature
   branch already lives (a legacy feature).
1. Read the committed artifacts at `docs/design/<slug>/` in `FT`. `design.md` says what's decided
   and what's open; the commit log says what settled when. Anything the loop left uncommitted never
   settled — start that piece over.
2. Continue the loop (step 4) from the open questions. A settled decision reopens only on new
   information, said out loud — not on a fresh context's second thoughts.

## Rules

- **Design, don't build.** Nothing lands on the branch but the artifacts under
  `docs/design/<slug>/` — no implementation, no scaffolding, no probes. Unknowns that need code
  become open questions for `plan` to chart as `research` nodes.
- **The human closes the design.** The loop ends on the human calling it good, never on your own
  judgement; the closing report follows that word and nothing before it.
- **Commit as work solidifies.** Everything agreed is written and committed in the round it was
  agreed in — the branch is the state, there is no store, and an interrupted design must resume
  having lost nothing that had settled.
- **No cypherlite, no store.** This skill runs without either and never installs or creates
  either: a store's existence only routes the mode, and sibling stores are read best-effort
  (step 2), only when `cypherlite` is already on PATH.
- **The user's checkout never changes branch.** Every edit, commit, and check happens in `FT`; the
  main tree is never touched.
