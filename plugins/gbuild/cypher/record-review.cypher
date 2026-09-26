// Record one gbuild-reviewer verdict as a Review node. `attempt` is assigned
// here (previous reviews + 1), so repair history is never lost.
// failed_criteria is the list of acceptance criteria the reviewer failed
// (pass `[]` on a pass).
//   cypherlite .gbuild/<slug>/db -json --param slug=<node-slug> --param verdict=pass \
//     --param 'failed_criteria=[]' < cypher/record-review.cypher
MATCH (n:GbuildNode {slug: $slug})
WHERE $verdict IN ['pass', 'fail']
WITH n, COUNT { (n)-[:REVIEWED]->(:Review) } + 1 AS attempt
CREATE (n)-[:REVIEWED]->(r:Review {
  attempt: attempt,
  verdict: $verdict,
  failed_criteria: $failed_criteria,
  at: toString(datetime())
})
RETURN n.slug AS slug, r.attempt AS attempt, r.verdict AS verdict;
.checkpoint
