# Ship checklist

`plan` runs this checklist against the graph it just wrote, before committing the store. Any item that
fails means revise the graph (with Cypher), not add a caveat in prose.

1. **Risky assumptions are resolved, not deferred.** Every assumption that would invalidate nodes or
   edges if wrong has either been confirmed against the codebase/docs, or is charted as a `research`
   node that answers it. An assumption left as "probably fine" is a hole.
2. **Every edge passes the cut test.** For each `DEPENDS_ON`, the dependent reads one of the
   dependency's `OUTPUT` fields through a `FROM` edge. `validate.cypher` rejects an edge with no data
   behind it and data with no edge behind it — but an agent can still invent a field just to satisfy it,
   so ask honestly whether the dependent *needs* that value.
3. **Independent nodes are actually in the same wave.** Read `wave` from `status.cypher` and confirm
   nodes with no real edge between them land together, not in a chain.
4. **Every node has non-empty, concrete acceptance criteria.** The schema requires a list and
   `validate.cypher` rejects blanks; `plan` itself is responsible for concrete — no `"looks correct"`, no
   criterion a fresh context couldn't check unaided.
5. **Every `OUTPUT` field has a precise `shape`**, not free text. Downstream `INPUT` fields read it
   through `FROM` rather than re-describing it.
6. **Every `Acceptance` node is `SATISFIES`-covered** by at least one GbuildNode. An uncovered
   feature-level acceptance bullet means a node is missing. (`validate.cypher` enforces this.)
7. **No node restates a global acceptance bullet verbatim as its own criterion.** Node-level acceptance
   is the local, observable slice; the `Acceptance` nodes keep the whole-feature bar.
8. **Every controlled cycle has a hard round cap and a dedup rule**, stated in the node(s) that form the
   cycle — not left implicit.
9. **`DEPENDS_ON` is acyclic.** `validate.cypher` rejects a cycle; confirm it doesn't.
10. **Every `chore` node is depended on by at least one other node.** A chore nobody depends on isn't in
    scope — it's either wired wrong or shouldn't exist. (`validate.cypher` enforces this.)
11. **`failure_policy` fits the node type**, per `reference/failure-policies.md` — not defaulted to
    `retry` everywhere without thinking about it.
12. **`model_tier` is `strong` only where judgement, not throughput, is the bottleneck** — see
    `reference/cost-model.md`.
13. **The graph, run end to end with every node passing review, actually reaches `destination`.** Read
    the `Feature` node's `destination` property back against the node set: if every node completed, is
    the feature actually done? A graph that's internally consistent but doesn't add up to the
    destination is still wrong.
