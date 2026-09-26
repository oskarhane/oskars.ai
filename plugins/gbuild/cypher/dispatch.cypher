// Claim the next wave: move every frontier node (pending, every DEPENDS_ON
// target completed or cancelled) to in_progress, and return exactly what its
// implementing agent needs — nothing about the rest of the graph. An input
// with a `value` was read from an upstream node; one with a null value is
// external, and its `shape` says where to find it. No rows = nothing is
// ready (the graph is done or stuck — ask progress.cypher / attention.cypher).
// For a router, cancel the unselected branches with set-status.cypher first.
//   cypherlite .gbuild/<slug>/db --mode jsonl < cypher/dispatch.cypher
MATCH (n:GbuildNode {status: 'pending'})
WHERE NOT EXISTS { MATCH (n)-[:DEPENDS_ON]->(d:GbuildNode) WHERE NOT d.status IN ['completed', 'cancelled'] }
SET n.status = 'in_progress'
RETURN n.slug AS slug,
       n.title AS title,
       n.type AS type,
       n.acceptance AS acceptance,
       n.failure_policy AS failure_policy,
       n.model_tier AS model_tier,
       n.verify AS verify,
       COLLECT {
         MATCH (n)-[:INPUT]->(i:Field)
         OPTIONAL MATCH (i)-[:FROM]->(o:Field)
         WITH i, o ORDER BY i.name
         RETURN {name: i.name, shape: i.shape, value: o.value}
       } AS inputs,
       COLLECT {
         MATCH (n)-[:OUTPUT]->(f:Field)
         WITH f ORDER BY f.name
         RETURN {name: f.name, shape: f.shape}
       } AS outputs
ORDER BY slug;
.checkpoint
