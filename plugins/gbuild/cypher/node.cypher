// Everything needed to dispatch or review one node, with inputs resolved
// through FROM edges to the upstream output values. An input with no FROM is
// external (from the codebase / environment): its `from` and `value` are null.
//   cypherlite .gbuild/<slug>/db -json --param slug=<node-slug> < cypher/node.cypher
MATCH (n:GbuildNode {slug: $slug})
RETURN n.slug AS slug,
       n.title AS title,
       n.type AS type,
       n.status AS status,
       n.acceptance AS acceptance,
       n.verify AS verify,
       n.failure_policy AS failure_policy,
       n.model_tier AS model_tier,
       COLLECT {
         MATCH (n)-[:INPUT]->(i:Field)
         OPTIONAL MATCH (i)-[:FROM]->(o:Field)<-[:OUTPUT]-(u:GbuildNode)
         WITH i, o, u ORDER BY i.name
         RETURN {name: i.name, shape: i.shape, from: u.slug + '.output.' + o.name, value: o.value}
       } AS inputs,
       COLLECT {
         MATCH (n)-[:OUTPUT]->(f:Field)
         WITH f ORDER BY f.name
         RETURN {name: f.name, shape: f.shape, value: f.value}
       } AS outputs,
       COLLECT {
         MATCH (n)-[:DEPENDS_ON]->(d:GbuildNode)
         WITH d ORDER BY d.slug
         RETURN d.slug
       } AS depends_on,
       COLLECT {
         MATCH (n)-[:SATISFIES]->(a:Acceptance)
         WITH a ORDER BY a.id
         RETURN {id: a.id, text: a.text}
       } AS satisfies,
       COLLECT {
         MATCH (n)-[:REVIEWED]->(r:Review)
         WITH r ORDER BY r.attempt
         RETURN {attempt: r.attempt, verdict: r.verdict, failed_criteria: r.failed_criteria, at: r.at}
       } AS reviews;
