# Pass: structure — size, decomposition, layer placement

You are the **structure** pass of a stellar review. Your input is one
brief file (`brief-structure[-N].md`) plus the doctrine
(`references/full-checklist.md`) and output rules
(`references/finding-schema.md`, `references/severity-rubric.md`). Read
them first.

## Your mandate — report ONLY these

From the Standards:

- **std-1** — files crossing or approaching 1000 lines because of this
  branch (the brief's File facts mark crossings mechanically; your job is
  to judge whether the growth is organized or accreted, and whether a
  decomposition is obvious)
- **std-6 (layer half)** — logic in the wrong file/layer/package; feature
  logic leaking into general-purpose modules; implementation details
  leaking through APIs. The brief's dependency edges make layering
  visible: an edge that skips or inverts a layer is a finding candidate.

From the Review Questions:

- Is this logic in the right file/layer? Past a healthy size boundary?
- Did a cohesive module become more coupled, stateful, or harder to scan?

From Flag Aggressively:

- files crossing 1000 lines because of this PR
- feature-specific logic leaking into general-purpose modules
- edge-case handling shoved into an already busy function
- logic in the wrong layer/package
- missed obvious decomposition that would materially improve
  maintainability

## NOT yours (never report)

- Conditionals, special-case branching, state-model reframes, code-judo →
  **branching** pass
- Thin wrappers, casts/optionality, duplicated/copy-pasted helpers,
  sequencing/atomicity → **boundaries** pass
- Cross-unit duplication candidates and site inconsistency →
  **comparison** pass

Genuine overlaps (a helper that is both misplaced AND duplicated): report
it if the *primary* defect is placement; otherwise leave it to comparison.

## Mechanics

1. Read your assigned brief file. Its "Units in scope" list is your
   assignment — judge every one of them. Sealed units and unlisted files
   are decided; never report them.
2. The brief includes unit bodies; you may open the real files for
   surrounding context (callers, module layout) when placement or cohesion
   is in question — but findings anchor to in-scope units.
3. Emit findings in the finding-schema JSON shape as your final message:
   a `{"findings": [...], "coverage": ["<brief file>"]}` document. No
   prose around it.
