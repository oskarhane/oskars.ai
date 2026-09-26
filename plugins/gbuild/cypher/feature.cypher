// Feature-level context: destination, the acceptance bar with the nodes that
// cover each criterion, and every node's recorded output values. What review
// hands the auditor and what pr builds the description from.
//   cypherlite .gbuild/<slug>/db -json < cypher/feature.cypher
MATCH (f:Feature)
RETURN f.feature AS feature,
       f.destination AS destination,
       f.context AS context,
       f.out_of_scope AS out_of_scope,
       COLLECT {
         MATCH (f)-[:HAS_ACCEPTANCE]->(a:Acceptance)
         WITH a ORDER BY a.id
         RETURN {id: a.id, text: a.text,
                 covered_by: COLLECT { MATCH (a)<-[:SATISFIES]-(n:GbuildNode) WITH n ORDER BY n.slug RETURN n.slug }}
       } AS acceptance,
       COLLECT {
         MATCH (n:GbuildNode)
         WITH n ORDER BY n.slug
         RETURN {slug: n.slug, title: n.title, status: n.status,
                 outputs: COLLECT { MATCH (n)-[:OUTPUT]->(o:Field) WITH o ORDER BY o.name RETURN {name: o.name, value: o.value} }}
       } AS nodes;
