// Move nodes to a non-completed status in one call: `cancelled` (skip policy,
// or a router's unselected branches), `failed` (escalate, an exhausted
// retry/repair, stop), or `pending` (reset nodes an interrupted run left
// in_progress). `completed` is rejected — only record.cypher may set it, so it
// can require a passing review and every output value.
//   cypherlite .gbuild/<slug>/db --mode jsonl --param 'slugs=["a","b"]' --param 'status="cancelled"' \
//     < cypher/set-status.cypher
UNWIND $slugs AS s
MATCH (n:GbuildNode {slug: s})
WHERE $status IN ['pending', 'in_progress', 'failed', 'cancelled']
SET n.status = $status
RETURN n.slug AS slug, n.status AS status
ORDER BY slug;
.checkpoint
