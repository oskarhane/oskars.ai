// Claim every frontier node (pending, every DEPENDS_ON target completed or
// cancelled): move it to in_progress and return only what the orchestrator
// routes on. Each agent reads its own definition with brief.cypher, so no
// title, acceptance, inputs or outputs pass through the orchestrator. Run it
// at the start of a run and again after every record.cypher / set-status.cypher
// call. No rows = nothing newly ready (ask progress.cypher / attention.cypher
// whether the graph is done or stuck).
//   cypherlite query --database <git-common-dir>/gbuild/<slug>/db --mode jsonl < cypher/dispatch.cypher
MATCH (n:GbuildNode {status: 'pending'})
WHERE NOT EXISTS { MATCH (n)-[:DEPENDS_ON]->(d:GbuildNode) WHERE NOT d.status IN ['completed', 'cancelled'] }
SET n.status = 'in_progress'
RETURN n.slug AS slug, n.type AS type, n.model_tier AS model_tier, n.failure_policy AS failure_policy
ORDER BY slug;
