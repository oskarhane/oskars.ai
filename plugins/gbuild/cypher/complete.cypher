// Record a node as completed: store its output values on its OUTPUT fields
// and the implementing agent's own start/finish times. Guarded — it writes
// nothing unless the node is in_progress, has a passing Review, and $outputs
// has a value for every declared output. Check `completed` in the result;
// `missing_outputs` / `has_passing_review` say why when it is false.
// Output values must be scalars or lists of scalars; JSON-encode anything
// nested into a string.
//   cypherlite .gbuild/<slug>/db -json --param slug=<node-slug> \
//     --param 'outputs={"value": 7}' --param started_at=<iso> --param completed_at=<iso> \
//     < cypher/complete.cypher
MATCH (n:GbuildNode {slug: $slug})
WITH n,
     [k IN COLLECT { MATCH (n)-[:OUTPUT]->(f:Field) RETURN f.name } WHERE $outputs[k] IS NULL] AS missing,
     EXISTS { (n)-[:REVIEWED]->(:Review {verdict: 'pass'}) } AS passed
WITH n, missing, passed, (n.status = 'in_progress' AND passed AND size(missing) = 0) AS ok
OPTIONAL MATCH (n)-[:OUTPUT]->(f:Field) WHERE ok
SET f.value = $outputs[f.name]
WITH DISTINCT n, missing, passed, ok
FOREACH (_ IN CASE WHEN ok THEN [1] ELSE [] END |
  SET n.status = 'completed', n.started_at = $started_at, n.completed_at = $completed_at)
RETURN n.slug AS slug, ok AS completed, n.status AS status,
       passed AS has_passing_review, missing AS missing_outputs;
.checkpoint
