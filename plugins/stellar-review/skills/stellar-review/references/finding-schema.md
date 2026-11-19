# Finding schema (findings.json)

The pipeline's only model-written artifact is `.stellar/findings.json` —
a single JSON document. Everything else (facts, scope, briefs, ledger,
posting, verdict) is produced by scripts.

## Shape

```json
{
  "version": 1,
  "findings": [
    {
      "area": "structure | branching | boundaries | comparison",
      "severity": "blocker | medium | nit",
      "path": "src/namespace.rs",
      "start_line": 51,
      "end_line": 61,
      "unit": "src/namespace.rs::Namespace::parse",
      "checklist_id": "std-3",
      "quote": "match s { \"system\" => ... }",
      "why": "one or two sentences — what this does to the codebase",
      "remedy": "the structural fix, not a band-aid",
      "confidence": "high | medium"
    }
  ],
  "resolutions": [
    { "finding_id": "F-1-3", "addressed": true, "note": "optional" }
  ],
  "coverage": ["list", "of", "brief", "files", "read"],
  "notes": "optional free text for the summary"
}
```

## Rules

1. **Exhaustive at detection.** Report every finding inside your mandate.
   Never withhold one because you already have several, because it seems
   minor, or because you assume another pass has it. Severity grading and
   nit-capping happen in the poster — never in your head.
2. **No quote, no finding.** `quote` is 1–6 lines of the actual code,
   copied verbatim from the brief. `start_line`/`end_line` refer to the
   NEW file's line numbers (the brief's unit headers give them).
3. **One issue per finding.** Two problems in one hunk are two findings.
   The same problem in two places is two findings (the poster dedupes true
   duplicates only).
4. **`unit`** is the unit ID from the brief (`path::name`). It keys the
   ledger's resolution tracking — always set it when the finding lives
   inside a listed unit. Omit only for genuinely file-level issues.
5. **`checklist_id`**: `std-<n>` for Standards, `q-<slug>` for Review
   Questions, `flag-<slug>` for Flag Aggressively items (e.g.
   `flag-1k-crossing`, `flag-temp-branch`, `flag-canonical-dup`). Use the
   closest existing id; invent one in the same style only when nothing
   fits.
6. **Sealed means sealed.** Units the brief marks sealed or omits from
   your assignment must not appear in your findings. Already-posted open
   findings and waived findings (listed in the brief header) must not be
   re-reported. The poster enforces this: out-of-scope findings are
   dropped before they reach the ledger.
7. **Incremental rounds anchor to the incremental diff.** In round ≥ 2 a
   finding's `start_line`–`end_line` must intersect the `last_head…head`
   diff hunks embedded in your brief. Unchanged lines of a re-scoped unit
   were already judged in an earlier round; if a changed hunk makes them
   wrong, quote the *changed* lines and explain the causal link in `why`.
   The poster drops non-intersecting findings. Findings resolved in
   earlier rounds (listed in the brief header) are decided: do not
   re-report them, and do not file the inverse of an accepted remedy.
8. **`resolutions`** answers the brief's Resolution checks — one entry per
   check, `addressed: true|false`. This is closed-form: compare the
   finding's quoted code with the current unit body.
9. **`confidence`** matters only for nits: the poster drops non-`high`
   nits and caps the rest.
10. **`coverage`** lists the brief files you actually read (e.g.
   `brief-structure-2.md`). The orchestrator merges these into the final
   document.
