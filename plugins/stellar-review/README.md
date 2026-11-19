# stellar-review — Claude Code + OpenCode plugin

Strict maintainability review as a **deterministic pipeline** (ADR-0271 lineage, extracted
from the [relate](https://github.com/relatedb/relate) repository): scripted facts, a
cross-round ledger that seals untouched code, pre-digested pass briefs, four focused review
passes dispatched in parallel, and scripted posting + verdict. Every blocker and medium
surfaces in round 1; untouched code never re-produces findings; the model judges briefs and
never reads a raw diff.

## The pipeline

```
stellar-prep.sh local [--quick] [PR]     # one command: facts → ledger → scope → briefs
        │
        ├── structure pass    (size, decomposition, layer placement)      ┐
        ├── branching pass    (spaghetti growth, conditionals, code judo) ├ parallel sub-agents,
        ├── boundaries pass   (abstractions, type contracts, sequencing)  │ one per brief file,
        └── comparison pass   (duplication, consistency, resolutions)     ┘ cheap model tiers
        │
ledger.py update → findings grouped by severity, approval-bar verdict
```

- **Full round** (the mandatory pre-push gate): the delta plus the carried ledger's
  earlier-round units plus the dependency-dirty expansion — approximately what CI will judge.
- **Quick round** (`--quick`, mid-work pre-filter): the delta's changed units only, one brief
  per pass. A pre-filter, never a gate — a clean quick round does not predict a clean CI round.
- **CI round**: the same pipeline driven by the workflow template — the model step judges the
  briefs, `post.py` rolls the ledger, posts inline comments, and derives the verdict.

The four passes are bundled as agents (`agents/stellar-*.md`); doctrine lives in
`skills/stellar-review/references/`, pass mandates in `skills/stellar-review/passes/`, the
tooling (pure Python 3 stdlib) in `skills/stellar-review/tools/`.

## Install

### Claude Code

From the marketplace:

```bash
claude plugin marketplace add oskarhane/oskars.ai
claude plugin install stellar-review@oskars.ai
```

For local development:

```bash
claude --plugin-dir ./plugins/stellar-review
```

The four pass agents register as plugin agents; invoke the skill with
`/stellar-review` (or ask for a stellar review).

### OpenCode

The same directory is also an OpenCode (V2) plugin, published to npm as
[`opencode-stellar-review`](https://www.npmjs.com/package/opencode-stellar-review) —
`index.ts` registers the `stellar-review` skill and the `/stellar-review` slash command from
the same markdown the Claude plugin uses.

```bash
opencode plugin add opencode-stellar-review
```

`opencode plugin update opencode-stellar-review` moves to the latest published version. For
local development, point any `opencode.json(c)` at a checkout instead:

```jsonc
{
  "plugins": ["/path/to/oskars.ai/plugins/stellar-review"]
}
```

OpenCode plugins cannot register agents, so the skill's OpenCode runtime notes dispatch the
built-in `general` subagent per brief file, pointed at the plugin's agent markdown, with the
per-pass model from the tier guidance or the `STELLAR_MODEL_<PASS>` environment overrides
(`STELLAR_MODEL_STRUCTURE`, `STELLAR_MODEL_BRANCHING`, `STELLAR_MODEL_BOUNDARIES`,
`STELLAR_MODEL_COMPARISON`).

## Setting up a new repository

Two lines in the repo, then optionally CI:

1. Add the runtime state directory to `.gitignore`:

   ```gitignore
   .stellar/
   ```

2. If the default branch is not `main`, export `STELLAR_BASE_REF` (e.g. `origin/master`)
   wherever the skill runs (shell profile, CI env), so round-1 merge bases resolve against
   the real default branch.

3. *(optional, recommended)* CI: copy `templates/ci/stellar-review.yml` to
   `.github/workflows/stellar-review.yml`, set the `FIREWORKS_API_KEY` secret, and optionally
   the `OPENCODE_REVIEW_MODEL` / `STELLAR_MODEL_<PASS>` overrides. The template pins the
   plugin version (`STELLAR_REVIEW_VERSION` env) and the OpenCode CLI (version + sha256) —
   bump both with releases. Its header comments document the security posture and what was
   consciously simplified from the origin repo's CI (the full restore-and-harden
   choreography between the model and post steps).

### Runtime dependencies

`python3` (stdlib only), `git`, `gh` (authenticated, for ledger fetch/post), and `jq` — on
PATH wherever the skill or CI runs.

## What it reviews

Per-unit judgment over pre-digested briefs, against the doctrine in
`skills/stellar-review/references/full-checklist.md`:

| Pass | Reports |
| --- | --- |
| `stellar-structure` | file size / decomposition / layer placement |
| `stellar-branching` | spaghetti growth, special-case conditionals, missed code-judo |
| `stellar-boundaries` | thin abstractions, casts/optionality, duplication of canonical helpers, sequencing/atomicity |
| `stellar-comparison` | cross-unit duplication, same-situation divergent handling, resolution checks |

If the reviewed repository's AGENTS.md defines its own code-shape rules, those take
precedence over the default recurring-pattern catalog.

## Provenance

Extracted from the relate repository's `.agents/skills/stellar-review/` (ADR-0271 pipeline,
ADR-0275 incremental anchoring, ADR-0292 stale-ledger-proof diffs, ADR-0302 per-pass model
tiers; LABS references in comments are that repo's finding/provenance labels). relate will
migrate to consuming this plugin; until then the two copies must not drift — treat this
directory as canonical.

## Releasing

Releases are dispatched from the GitHub Actions tab, never published by hand: pick the
**stellar-review release** workflow → **Run workflow** → choose a level. The workflow bumps
`version` in `package.json` and `.claude-plugin/plugin.json` in lockstep
(`scripts/bump-versions.mjs`), runs the test suites (`node --import tsx --test` plus the
Python `unittest` suite in `skills/stellar-review/tools/tests`), publishes
`opencode-stellar-review` to npm with provenance (trusted publishing — see the one-time setup
notes in `.github/workflows/stellar-review-release.yml`), then pushes the release commit and
tag.
