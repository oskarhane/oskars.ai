// One compact row per wave: node counts by state, and `open` — the slugs in
// that wave not yet completed or cancelled. A wave with `open: []` is done;
// the graph is done when every row's `open` is empty. `wave` is the longest
// DEPENDS_ON chain below a node (0 = no dependencies).
//   cypherlite .gbuild/<slug>/db --mode jsonl < cypher/progress.cypher
MATCH (n:GbuildNode)
OPTIONAL MATCH p = (n)-[:DEPENDS_ON*]->()
WITH n, coalesce(max(length(p)), 0) AS wave
WITH n, wave,
     CASE
       WHEN n.status <> 'pending' THEN n.status
       WHEN EXISTS { MATCH (n)-[:DEPENDS_ON]->(d:GbuildNode) WHERE NOT d.status IN ['completed', 'cancelled'] } THEN 'blocked'
       ELSE 'frontier'
     END AS state
ORDER BY n.slug
RETURN wave,
       count(*) AS total,
       sum(CASE WHEN state = 'completed' THEN 1 ELSE 0 END) AS completed,
       sum(CASE WHEN state = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
       sum(CASE WHEN state = 'in_progress' THEN 1 ELSE 0 END) AS in_progress,
       sum(CASE WHEN state = 'failed' THEN 1 ELSE 0 END) AS failed,
       sum(CASE WHEN state = 'frontier' THEN 1 ELSE 0 END) AS frontier,
       sum(CASE WHEN state = 'blocked' THEN 1 ELSE 0 END) AS blocked,
       [s IN collect(CASE WHEN NOT state IN ['completed', 'cancelled'] THEN n.slug END) WHERE s IS NOT NULL] AS open
ORDER BY wave;
