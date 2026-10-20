// An implementer's self-check of its result file before it replies (and the
// reviewer's mechanical output check). Clean when missing_outputs,
// invalid_outputs and unknown_outputs are [] and has_times is true:
//   missing_outputs  declared outputs with no value (record would downgrade the pass)
//   invalid_outputs  values that are not a scalar or a single-type list of
//                    scalars (record would fail with InvalidPropertyType)
//   unknown_outputs  keys that are not declared outputs (likely typos; record ignores them)
//   has_times        started_at and completed_at are strings
//   cypherlite query --read-only --database <git-common-dir>/gbuild/<slug>/db --mode jsonl --param 'slug="<node-slug>"' \
//     --fetch-params result=<git-common-dir>/gbuild/<slug>/inbox/<node-slug>.json < cypher/check-result.cypher
MATCH (n:GbuildNode {slug: $slug})
WITH n, coalesce($result.outputs, {}) AS outputs
RETURN n.slug AS slug,
       [k IN COLLECT { MATCH (n)-[:OUTPUT]->(f:Field) WITH f ORDER BY f.name RETURN f.name } WHERE outputs[k] IS NULL] AS missing_outputs,
       [k IN keys(outputs) WHERE outputs[k] IS NOT NULL AND NOT (outputs[k] IS :: STRING | INTEGER | FLOAT | BOOLEAN | LIST<STRING> | LIST<INTEGER> | LIST<FLOAT> | LIST<BOOLEAN>)] AS invalid_outputs,
       [k IN keys(outputs) WHERE NOT k IN COLLECT { MATCH (n)-[:OUTPUT]->(f:Field) RETURN f.name }] AS unknown_outputs,
       $result.started_at IS :: STRING NOT NULL AND $result.completed_at IS :: STRING NOT NULL AS has_times;
