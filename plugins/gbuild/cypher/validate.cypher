// gbuild format gate. Zero rows = valid; every row is one violation.
//   cypherlite .gbuild/<slug>/db --mode jsonl < cypher/validate.cypher
// Required properties, their types and slug/acceptance-id uniqueness are
// engine constraints (schema.cypher) — a write that breaks them never lands.
// This query checks everything the engine can't: enums, label/type agreement,
// edge shapes, coverage, acyclicity, and the data-flow (FROM) cut test.
CALL {
  MATCH (f:Feature) WITH count(f) AS c WHERE c <> 1
  RETURN 'feature-count' AS check, 'expected exactly 1 Feature node, found ' + toString(c) AS detail
UNION ALL
  MATCH (n) WHERE NOT (n:Feature OR n:Acceptance OR n:GbuildNode OR n:Field OR n:Review)
  RETURN 'unknown-node' AS check, 'node with labels [' + reduce(s = '', l IN labels(n) | s + ' ' + l) + ' ] is not part of the gbuild model' AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE NOT n.slug =~ '^[a-z0-9]+(-[a-z0-9]+)*$'
  RETURN 'bad-slug' AS check, n.slug + ': slug must be kebab-case' AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE NOT n.type IN ['research', 'decision', 'code', 'test', 'verify', 'chore']
  RETURN 'bad-type' AS check, n.slug + ': invalid type ' + n.type AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE NOT n.failure_policy IN ['retry', 'fallback', 'skip', 'repair', 'escalate', 'stop']
  RETURN 'bad-failure-policy' AS check, n.slug + ': invalid failure_policy ' + n.failure_policy AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE NOT n.model_tier IN ['cheap', 'strong']
  RETURN 'bad-model-tier' AS check, n.slug + ': invalid model_tier ' + n.model_tier AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE NOT n.status IN ['pending', 'in_progress', 'completed', 'failed', 'cancelled']
  RETURN 'bad-status' AS check, n.slug + ': invalid status ' + n.status AS detail
UNION ALL
  WITH {research: 'Research', decision: 'Decision', code: 'Code', test: 'Test', verify: 'Verify', chore: 'Chore'} AS label
  MATCH (n:GbuildNode)
  WITH n, label[n.type] AS want,
       [l IN labels(n) WHERE l IN ['Research', 'Decision', 'Code', 'Test', 'Verify', 'Chore']] AS have
  WHERE want IS NOT NULL AND have <> [want]
  RETURN 'type-label' AS check, n.slug + ': type ' + n.type + ' needs exactly the type label ' + want AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE size(n.acceptance) = 0 OR any(c IN n.acceptance WHERE trim(c) = '')
  RETURN 'bad-acceptance' AS check, n.slug + ': acceptance must be a non-empty list of non-blank criteria' AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE n.verify IS NOT NULL AND NOT EXISTS { MATCH (v:GbuildNode) WHERE v.slug = n.verify }
  RETURN 'verify-target' AS check, n.slug + ': verify names unknown node ' + n.verify AS detail
UNION ALL
  MATCH (a:Acceptance) WHERE NOT a.id =~ '^a-[0-9]+$' OR trim(a.text) = ''
  RETURN 'bad-acceptance-node' AS check, a.id + ': id must look like a-1 and text must be non-blank' AS detail
UNION ALL
  MATCH (a:Acceptance) WHERE NOT EXISTS { (:Feature)-[:HAS_ACCEPTANCE]->(a) }
  RETURN 'acceptance-unlinked' AS check, a.id + ': no HAS_ACCEPTANCE from the Feature' AS detail
UNION ALL
  MATCH (a:Acceptance) WHERE NOT EXISTS { (:GbuildNode)-[:SATISFIES]->(a) }
  RETURN 'acceptance-uncovered' AS check, a.id + ': no node SATISFIES it' AS detail
UNION ALL
  MATCH (x)-[r]->(y)
  WHERE NOT ((type(r) = 'HAS_ACCEPTANCE' AND x:Feature AND y:Acceptance)
          OR (type(r) = 'SATISFIES' AND x:GbuildNode AND y:Acceptance)
          OR (type(r) = 'DEPENDS_ON' AND x:GbuildNode AND y:GbuildNode)
          OR (type(r) IN ['INPUT', 'OUTPUT'] AND x:GbuildNode AND y:Field)
          OR (type(r) = 'FROM' AND x:Field AND y:Field)
          OR (type(r) = 'REVIEWED' AND x:GbuildNode AND y:Review))
  RETURN 'bad-edge' AS check,
         type(r) + ' from ' + coalesce(x.slug, x.id, x.name, '?') + ' to ' + coalesce(y.slug, y.id, y.name, '?') + ' is not an allowed edge' AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE EXISTS { (n)-[:DEPENDS_ON*]->(n) }
  RETURN 'cycle' AS check, n.slug + ': DEPENDS_ON cycle' AS detail
UNION ALL
  MATCH (n:GbuildNode {type: 'chore'}) WHERE NOT EXISTS { ()-[:DEPENDS_ON]->(n) }
  RETURN 'orphan-chore' AS check, n.slug + ': chore is not depended on by any node' AS detail
UNION ALL
  MATCH (n:GbuildNode) WHERE NOT EXISTS { (n)-[:OUTPUT]->(:Field) }
  RETURN 'no-output' AS check, n.slug + ': declares no OUTPUT field' AS detail
UNION ALL
  MATCH (f:Field) WITH f, COUNT { ()-[:INPUT|OUTPUT]->(f) } AS owners WHERE owners <> 1
  RETURN 'field-owner' AS check, f.name + ': field has ' + toString(owners) + ' owning nodes, want 1' AS detail
UNION ALL
  MATCH (n:GbuildNode)-[r:INPUT|OUTPUT]->(f:Field)
  WITH n, type(r) AS dir, f.name AS name, count(*) AS c WHERE c > 1
  RETURN 'duplicate-field' AS check, n.slug + ': ' + dir + ' field ' + name + ' declared ' + toString(c) + ' times' AS detail
UNION ALL
  MATCH (i:Field)-[:FROM]->(o:Field)
  WHERE NOT EXISTS { (:GbuildNode)-[:INPUT]->(i) } OR NOT EXISTS { (:GbuildNode)-[:OUTPUT]->(o) }
  RETURN 'bad-from' AS check, i.name + ' -> ' + o.name + ': FROM must run from an INPUT field to an OUTPUT field' AS detail
UNION ALL
  MATCH (i:Field) WITH i, COUNT { (i)-[:FROM]->() } AS c WHERE c > 1
  RETURN 'multi-from' AS check, i.name + ': input field has ' + toString(c) + ' FROM edges, want at most 1' AS detail
UNION ALL
  MATCH (n:GbuildNode)-[:INPUT]->(i:Field)-[:FROM]->(:Field)<-[:OUTPUT]-(u:GbuildNode)
  WHERE NOT EXISTS { (n)-[:DEPENDS_ON]->(u) }
  RETURN 'from-without-dependency' AS check, n.slug + '.' + i.name + ' reads ' + u.slug + ' but does not DEPENDS_ON it' AS detail
UNION ALL
  MATCH (n:GbuildNode)-[:DEPENDS_ON]->(u:GbuildNode)
  WHERE NOT EXISTS { (n)-[:INPUT]->(:Field)-[:FROM]->(:Field)<-[:OUTPUT]-(u) }
  RETURN 'dependency-without-from' AS check, n.slug + ' DEPENDS_ON ' + u.slug + ' but reads none of its outputs (cut test)' AS detail
UNION ALL
  MATCH (n:GbuildNode {status: 'completed'}) WHERE NOT EXISTS { (n)-[:REVIEWED]->(:Review {verdict: 'pass'}) }
  RETURN 'completed-without-pass' AS check, n.slug + ': completed without a passing Review' AS detail
UNION ALL
  MATCH (n:GbuildNode {status: 'completed'})-[:OUTPUT]->(f:Field) WHERE f.value IS NULL
  RETURN 'completed-missing-output' AS check, n.slug + '.' + f.name + ': completed node has no value for this output' AS detail
UNION ALL
  MATCH (r:Review) WHERE NOT r.verdict IN ['pass', 'fail'] OR r.attempt < 1
  RETURN 'bad-review' AS check, 'review attempt ' + toString(r.attempt) + ' has verdict ' + r.verdict AS detail
UNION ALL
  MATCH (r:Review) WITH r, COUNT { (:GbuildNode)-[:REVIEWED]->(r) } AS c WHERE c <> 1
  RETURN 'review-owner' AS check, 'review attempt ' + toString(r.attempt) + ' has ' + toString(c) + ' owning nodes, want 1' AS detail
}
RETURN check, detail
ORDER BY check, detail;
