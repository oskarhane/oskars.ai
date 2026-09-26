// Record a whole wave's review verdicts in one atomic call. Each result adds a
// Review (attempt = previous reviews + 1). A pass with a value for every
// OUTPUT field also completes the node: output values stored on its fields,
// the implementing agent's own times on the node. A pass missing outputs is
// recorded as a fail listing them, so the review history stays truthful.
// Only in_progress nodes are recorded: compare the returned slugs with what
// you sent. Output values must be scalars or lists of scalars — one nested
// value rejects the whole batch (InvalidPropertyType); JSON-encode it and
// resend.
//   cypherlite .gbuild/<slug>/db --mode jsonl --param 'results=[
//     {"slug": "a", "verdict": "pass", "failed_criteria": [], "outputs": {"value": 7},
//      "started_at": "<iso>", "completed_at": "<iso>"},
//     {"slug": "b", "verdict": "fail", "failed_criteria": ["<criterion>"]}
//   ]' < cypher/record.cypher
UNWIND $results AS r
MATCH (n:GbuildNode {slug: r.slug})
WHERE n.status = 'in_progress' AND r.verdict IN ['pass', 'fail']
WITH n, r,
     COUNT { (n)-[:REVIEWED]->(:Review) } + 1 AS attempt,
     CASE WHEN r.verdict = 'pass'
          THEN [k IN COLLECT { MATCH (n)-[:OUTPUT]->(f:Field) RETURN f.name } WHERE r.outputs[k] IS NULL]
          ELSE [] END AS missing
WITH n, r, attempt, missing, (r.verdict = 'pass' AND size(missing) = 0) AS ok
CREATE (n)-[:REVIEWED]->(review:Review {
  attempt: attempt,
  verdict: CASE WHEN ok THEN 'pass' ELSE 'fail' END,
  failed_criteria: coalesce(r.failed_criteria, []) + [k IN missing | 'missing output value: ' + k],
  at: toString(datetime())
})
WITH n, r, attempt, missing, ok, review
OPTIONAL MATCH (n)-[:OUTPUT]->(f:Field) WHERE ok
SET f.value = r.outputs[f.name]
WITH DISTINCT n, r, attempt, missing, ok, review
FOREACH (_ IN CASE WHEN ok THEN [1] ELSE [] END |
  SET n.status = 'completed', n.started_at = r.started_at, n.completed_at = r.completed_at)
RETURN n.slug AS slug, attempt, review.verdict AS verdict, ok AS completed, missing AS missing_outputs
ORDER BY slug;
.checkpoint
