// One row per GbuildNode, in wave order. `state` is derived, never stored:
//   frontier  = pending, every DEPENDS_ON target completed or cancelled
//   blocked   = pending, some DEPENDS_ON target not completed or cancelled
//   otherwise = the stored status (in_progress, completed, failed, cancelled)
// `wave` is the longest DEPENDS_ON chain below the node (0 = no dependencies),
// so nodes sharing a wave are safe to run concurrently.
// `last_dependency_at` is the latest completed_at among the node's completed
// DEPENDS_ON targets (null without any): its gap to `started_at` is how long
// the node waited for dispatch once its last dependency landed.
//   cypherlite query --read-only --database <git-common-dir>/gbuild/<slug>/db --mode jsonl < cypher/status.cypher
MATCH (n:GbuildNode)
OPTIONAL MATCH p = (n)-[:DEPENDS_ON*]->()
WITH n, coalesce(max(length(p)), 0) AS wave
OPTIONAL MATCH (n)-[:DEPENDS_ON]->(d:GbuildNode)
WITH n, wave, d ORDER BY d.slug
WITH n, wave, [x IN collect(d) WHERE NOT x.status IN ['completed', 'cancelled'] | x.slug] AS waiting_on,
     max(CASE WHEN d.status = 'completed' THEN d.completed_at END) AS last_dependency_at
OPTIONAL MATCH (n)-[:REVIEWED]->(r:Review)
WITH n, wave, waiting_on, last_dependency_at, r ORDER BY r.attempt DESC
WITH n, wave, waiting_on, last_dependency_at, collect(r) AS reviews
RETURN n.slug AS slug,
       n.title AS title,
       n.type AS type,
       n.status AS status,
       CASE
         WHEN n.status = 'pending' AND size(waiting_on) = 0 THEN 'frontier'
         WHEN n.status = 'pending' THEN 'blocked'
         ELSE n.status
       END AS state,
       wave,
       waiting_on,
       size(reviews) AS review_attempts,
       reviews[0].verdict AS last_verdict,
       reviews[0].failed_criteria AS last_failed_criteria,
       n.started_at AS started_at,
       n.completed_at AS completed_at,
       last_dependency_at
ORDER BY wave, slug;
