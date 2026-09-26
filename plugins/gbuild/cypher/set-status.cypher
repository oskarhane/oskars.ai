// Move a node to a non-completed status: `cancelled` (skip policy), `failed`
// (escalate, or an exhausted retry/repair), or `pending` (reset a node an
// interrupted run left in_progress). `completed` is rejected here — only
// complete.cypher may set it, so it can enforce the review and outputs.
//   cypherlite .gbuild/<slug>/db -json --param slug=<node-slug> --param status=cancelled \
//     < cypher/set-status.cypher
MATCH (n:GbuildNode {slug: $slug})
WHERE $status IN ['pending', 'in_progress', 'failed', 'cancelled']
SET n.status = $status
RETURN n.slug AS slug, n.status AS status;
.checkpoint
