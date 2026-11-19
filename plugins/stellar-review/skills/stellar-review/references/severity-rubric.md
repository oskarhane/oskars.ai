# Severity Rubric

Assign exactly one severity per finding. When torn, use the calibration question at the bottom.

## blocker

Anything under the Approval Bar's presumptive blockers, or a structural regression:

- preserves incidental complexity when a visible code-judo move would delete it
- pushes a file from <1000 to >1000 lines (this one is mechanical — the Step-0 facts decide it, not taste)
- adds ad-hoc branching that tangles an existing flow
- scatters feature checks across shared code
- adds an unnecessary abstraction / wrapper / cast-heavy contract
- duplicates a canonical helper or puts logic in the wrong layer
- any structural regression: the branch leaves a module materially harder to reason about than it found it

## medium

A real violation of a standard or doctrine flag with a concrete remedy, that materially affects maintainability but is **contained**: it doesn't tangle an existing flow, scatter checks across shared code, or regress a module's overall structure. Examples:

- a helper duplicated in one place where extraction is obvious
- a file growing toward (but not past) the 1k line boundary and losing cohesion
- unnecessary optionality or a cast at one boundary, with an explicit typed alternative
- a one-off conditional that is isolated today but will invite copies
- a missed extraction that would materially improve one busy function

## nit

Cosmetic: naming, local legibility, taste-level disagreements, ordering, comment style. Report only high-conviction nits; the merge caps them.

## Calibration

Torn between blocker and medium? Ask: *"If the next change to this code lands as-is, does this finding make that change materially riskier, or does it make the surrounding flow harder to reason about globally?"* Yes → **blocker**. It's a contained local cleanup → **medium**.

Torn between medium and nit? Ask: *"Is there a concrete structural remedy, or is this preference?"* Structural remedy → **medium**. Preference → **nit**.
