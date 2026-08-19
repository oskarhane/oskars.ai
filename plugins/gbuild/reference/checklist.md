# Ship checklist

`plan` runs this checklist against the graph it just wrote, before committing `graph.json`. Any item
that fails means revise the graph, not add a caveat in prose.

1. **Every edge passes the cut test.** For each `dependencies` entry, the dependent node actually reads
   something the dependency produced. No edge exists just because one node was thought of after another.
2. **Independent nodes are actually in the same wave.** Run `python3 scripts/graph.py <path> --waves`
   and confirm nodes with no real edge between them land together, not in a chain.
3. **Every node has non-empty, concrete acceptance criteria.** `graph.py` enforces non-empty; `plan`
   itself is responsible for concrete — no `"looks correct"`, no criterion a fresh context couldn't
   check unaided.
4. **Every node's `contract.output` is structured, not free text.** A downstream node's `contract.input`
   should be able to reference it directly.
5. **Every global `acceptance` bullet is `satisfies`-covered** by at least one node. An uncovered
   feature-level acceptance bullet means a node is missing.
6. **No node restates a global acceptance bullet verbatim as its own criterion.** Node-level acceptance
   is the local, observable slice; the global block keeps the whole-feature bar.
7. **Every controlled cycle has a hard round cap and a dedup rule**, stated in the node(s) that form the
   cycle — not left implicit.
8. **`dependencies` is acyclic.** `graph.py --waves` raises `GraphError` on a cycle; confirm it doesn't.
9. **Every `chore` node is depended on by at least one other node.** A chore nobody depends on isn't in
   scope — it's either wired wrong or shouldn't exist.
10. **`failure_policy` fits the node type**, per `reference/failure-policies.md` — not defaulted to
    `retry` everywhere without thinking about it.
11. **`model_tier` is `strong` only where judgement, not throughput, is the bottleneck** — see
    `reference/cost-model.md`.
12. **The graph, run end to end with every node passing review, actually reaches `destination`.** Read
    the top-level `destination` line back against the node set: if every node completed, is the feature
    actually done? A graph that's internally consistent but doesn't add up to the destination is still
    wrong.
