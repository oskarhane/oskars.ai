// Mark frontier nodes in_progress just before run fans them out. Only nodes
// that are pending AND whose every DEPENDS_ON target is completed or cancelled
// are moved; anything else is silently skipped, so compare `dispatched`
// against what you asked for.
//   cypherlite .gbuild/<slug>/db -json --param 'slugs=["a","b"]' < cypher/dispatch.cypher
UNWIND $slugs AS s
MATCH (n:GbuildNode {slug: s})
WHERE n.status = 'pending'
  AND NOT EXISTS { MATCH (n)-[:DEPENDS_ON]->(d:GbuildNode) WHERE NOT d.status IN ['completed', 'cancelled'] }
SET n.status = 'in_progress'
RETURN n.slug AS dispatched
ORDER BY dispatched;
.checkpoint
