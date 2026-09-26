// Only the nodes that need a decision — no rows means nothing does.
//   failed             escalated or exhausted; `detail` = the last review's failed criteria
//   in_progress        claimed but not recorded; if no run is active, an interrupted wave left it
//   blocked-by-failed  pending behind a failed node, so it can never unblock on its own;
//                      `detail` = the failed nodes it waits on
//   cypherlite .gbuild/<slug>/db --mode jsonl < cypher/attention.cypher
CALL {
  MATCH (n:GbuildNode {status: 'failed'})
  RETURN n.slug AS slug, 'failed' AS reason,
         COLLECT { MATCH (n)-[:REVIEWED]->(r:Review) WITH r ORDER BY r.attempt DESC LIMIT 1 UNWIND r.failed_criteria AS c RETURN c } AS detail
UNION ALL
  MATCH (n:GbuildNode {status: 'in_progress'})
  RETURN n.slug AS slug, 'in_progress' AS reason, [] AS detail
UNION ALL
  MATCH (n:GbuildNode {status: 'pending'})-[:DEPENDS_ON*]->(f:GbuildNode {status: 'failed'})
  WITH n, f ORDER BY f.slug
  RETURN n.slug AS slug, 'blocked-by-failed' AS reason, collect(DISTINCT f.slug) AS detail
}
RETURN slug, reason, detail
ORDER BY reason, slug;
