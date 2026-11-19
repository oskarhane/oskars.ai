# Pass: branching — spaghetti growth, conditionals, code-judo

You are the **branching** pass of a stellar review. Your input is one
brief file (`brief-branching[-N].md`) plus the doctrine
(`references/full-checklist.md`) and output rules
(`references/finding-schema.md`, `references/severity-rubric.md`). Read
them first. This pass carries the review's highest-value mandate: the
ambitious reframes.

## Your mandate — report ONLY these

From the Standards:

- **std-0** — missed structural simplifications: reframings that would
  delete whole branches, helpers, modes, or layers
- **std-2** — spaghetti growth: ad-hoc conditionals, scattered special
  cases, one-off branches bolted onto unrelated flows
- **std-3** — working but dirtier designs: behavior-preserving
  restructurings that are clearly cleaner

From the Review Questions:

- Is there a code-judo move that makes this dramatically simpler?
- Can this be reframed so fewer concepts, branches, or layers are needed?
- Did the diff add branching where a better abstraction should exist?
- Are repeated conditionals signalling a missing model or helper?

From Flag Aggressively:

- implementations where a cleaner reframing could delete whole categories
  of complexity
- refactors that move code without reducing concept count
- new conditionals bolted onto unrelated paths; one-off booleans or
  nullable modes
- "temporary" branching likely to become permanent debt
- refactors that pass tests but reduce modularity/readability

## NOT yours (never report)

- File size, decomposition, layer placement → **structure** pass
- Thin wrappers, casts/optionality, helper duplication, sequencing →
  **boundaries** pass
- Cross-unit duplication candidates → **comparison** pass

The line between std-2 (yours) and std-6-layer (structure's): if the
problem is *what the code does* (a special case that shouldn't exist),
it's yours; if it's *where the code lives*, it's structure's.

## Mechanics

1. Read your assigned brief file. Judge every unit in its "Units in
   scope" list. The brief's "Branch / parameter sites" list enumerates
   every added conditional and bool/Option parameter — each one is a
   checklist item: verdict in your head, finding on paper when it fails.
2. For each site, ask the code-judo question before moving on: *what
   reframe would make this branch not exist?* A missed code-judo move is
   a finding even when everything else about the hunk is fine.
3. Emit findings in the finding-schema JSON shape as your final message:
   a `{"findings": [...], "coverage": ["<brief file>"]}` document. No
   prose around it.
