// Record one node attempt per call. Every call adds a Review (attempt =
// previous reviews + 1) holding the verdict, its failed criteria and the
// reviewer's checklist. A pass with a value for every OUTPUT field also
// completes the node: output values stored on its fields, the implementing
// agent's own times on the node. A pass missing outputs is recorded as a fail
// listing them, so the review history stays truthful. A fail stores the Review
// only.
// Three params, always all bound (the script can't tell --param from
// --fetch-params):
//   verdict  {"slug", "verdict": "pass"|"fail", "failed_criteria": [...]} — the
//            only source of slug, verdict and failed criteria
//   result   <inbox>/<node-slug>.json (outputs, started_at, completed_at) on a
//            pass whose file exists, else {}; any slug/verdict key in it is ignored
//   review   <inbox>/<node-slug>.review.json ({checklist}) when it exists, else
//            {}; string entries only, the first 40, each cut to 300 chars
// No row unless the node is in_progress: compare the returned slug with the
// one sent. Output values must be scalars or lists of scalars — a nested value
// fails the whole call with InvalidPropertyType and writes nothing.
// `unselected`: for a completed decision node, the pending dependents reading
// one of its outputs whose string / list-of-strings value names some readers
// but not them — cancel them with set-status.cypher before the next dispatch.
//   cypherlite query --database <git-common-dir>/gbuild/<slug>/db --mode jsonl \
//     --param 'verdict={"slug":"<node-slug>","verdict":"pass","failed_criteria":[]}' \
//     --fetch-params result=<git-common-dir>/gbuild/<slug>/inbox/<node-slug>.json \
//     --fetch-params review=<git-common-dir>/gbuild/<slug>/inbox/<node-slug>.review.json < cypher/record.cypher
//   cypherlite query --database <git-common-dir>/gbuild/<slug>/db --mode jsonl \
//     --param 'verdict={"slug":"<node-slug>","verdict":"fail","failed_criteria":["implementer failed: <reason>"]}' \
//     --param 'result={}' --param 'review={}' < cypher/record.cypher
WITH $verdict AS v, $result AS res, $review AS rev
MATCH (n:GbuildNode {slug: v.slug})
WHERE n.status = 'in_progress' AND v.verdict IN ['pass', 'fail']
WITH n, v, res, rev,
     COUNT { (n)-[:REVIEWED]->(:Review) } + 1 AS attempt,
     CASE WHEN v.verdict = 'pass'
          THEN [k IN COLLECT { MATCH (n)-[:OUTPUT]->(f:Field) WITH f ORDER BY f.name RETURN f.name } WHERE res.outputs[k] IS NULL]
          ELSE [] END AS missing
WITH n, v, res, rev, attempt, missing, (v.verdict = 'pass' AND size(missing) = 0) AS ok
CREATE (n)-[:REVIEWED]->(review:Review {
  attempt: attempt,
  verdict: CASE WHEN ok THEN 'pass' ELSE 'fail' END,
  failed_criteria: coalesce(v.failed_criteria, []) + [k IN missing | 'missing output value: ' + k],
  checklist: [c IN coalesce(rev.checklist, []) WHERE (c IS :: STRING) | left(c, 300)][0..40],
  at: toString(datetime())
})
WITH n, res, attempt, missing, ok, review
OPTIONAL MATCH (n)-[:OUTPUT]->(f:Field) WHERE ok
SET f.value = res.outputs[f.name]
WITH DISTINCT n, res, attempt, missing, ok, review
FOREACH (_ IN CASE WHEN ok THEN [1] ELSE [] END |
  SET n.status = 'completed', n.started_at = res.started_at, n.completed_at = res.completed_at)
RETURN n.slug AS slug, attempt, review.verdict AS verdict, ok AS completed, missing AS missing_outputs,
       0 AS notes_added, 0 AS symbols_added,
       CASE WHEN ok AND n.type = 'decision' THEN COLLECT {
         MATCH (n)-[:OUTPUT]->(f:Field)
         WITH f, COLLECT { MATCH (f)<-[:FROM]-(:Field)<-[:INPUT]-(d:GbuildNode {status: 'pending'}) RETURN d.slug } AS readers,
              CASE WHEN f.value IS :: STRING THEN [f.value] WHEN f.value IS :: LIST<STRING> THEN f.value ELSE [] END AS named
         WHERE any(r IN readers WHERE r IN named)
         UNWIND [r IN readers WHERE NOT r IN named] AS u
         RETURN DISTINCT u ORDER BY u
       } ELSE [] END AS unselected;
