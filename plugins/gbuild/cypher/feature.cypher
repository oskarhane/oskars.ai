// Feature-level context: the destination and the acceptance bar, with the
// nodes that cover each criterion. What review hands the auditor and what pr
// builds the description from. Per-node output values are not included — get
// one node's with node.cypher if you actually need it.
//   cypherlite .gbuild/<slug>/db --mode jsonl < cypher/feature.cypher
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
       } AS acceptance;
