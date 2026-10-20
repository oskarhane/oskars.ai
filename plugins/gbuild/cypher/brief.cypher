// One node's brief: everything its implementer or reviewer needs, read by the
// agent itself (never by the orchestrator). An input with a FROM edge carries
// the upstream output value and `from` = '<upstream-slug>.output.<name>'; an
// external input has a null `from` and `value`, and its `shape` says where to
// look. `failed_criteria` is the latest Review's when it failed (a retry), else
// []. `notes` holds every note written by a transitive upstream node plus setup
// and testing notes from any node, upstream first, then newest, at most 20.
//   cypherlite query --read-only --database <git-common-dir>/gbuild/<slug>/db --mode jsonl --param 'slug="<node-slug>"' < cypher/brief.cypher
MATCH (n:GbuildNode {slug: $slug})
RETURN n.slug AS slug,
       n.title AS title,
       n.type AS type,
       n.acceptance AS acceptance,
       n.verify AS verify,
       COLLECT {
         MATCH (n)-[:INPUT]->(i:Field)
         OPTIONAL MATCH (i)-[:FROM]->(o:Field)<-[:OUTPUT]-(u:GbuildNode)
         WITH i, o, u ORDER BY i.name
         RETURN {name: i.name, shape: i.shape, from: u.slug + '.output.' + o.name, value: o.value}
       } AS inputs,
       COLLECT {
         MATCH (n)-[:OUTPUT]->(f:Field)
         WITH f ORDER BY f.name
         RETURN {name: f.name, shape: f.shape}
       } AS outputs,
       COLLECT {
         MATCH (n)-[:REVIEWED]->(r:Review)
         WITH r ORDER BY r.attempt DESC LIMIT 1
         WITH r WHERE r.verdict = 'fail'
         UNWIND r.failed_criteria AS c
         RETURN c
       } AS failed_criteria,
       COLLECT {
         MATCH (w:GbuildNode)-[:WROTE]->(nt:Note)
         WITH nt, CASE WHEN EXISTS { MATCH (n)-[:DEPENDS_ON*]->(w) } THEN 0 ELSE 1 END AS rank
         WHERE rank = 0 OR nt.topic IN ['setup', 'testing']
         WITH nt, rank ORDER BY rank, nt.at DESC, nt.text LIMIT 20
         RETURN {topic: nt.topic, text: nt.text, by: nt.by_node}
       } AS notes;
