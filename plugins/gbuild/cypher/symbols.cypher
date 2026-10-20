// Helpers, types and utilities completed nodes added, for reuse: the reviewer
// reads it before grepping for duplication, the implementer before writing a
// new helper. Only completed (merged) nodes' symbols exist, so nodes running at
// the same time can't see each other's unmerged helpers. At most 100 rows.
//   cypherlite query --read-only --database <git-common-dir>/gbuild/<slug>/db --mode jsonl < cypher/symbols.cypher
MATCH (:GbuildNode)-[:DEFINES]->(s:Symbol)
RETURN s.name AS name, s.file AS file, s.purpose AS purpose, s.by_node AS by
ORDER BY file, name
LIMIT 100;
