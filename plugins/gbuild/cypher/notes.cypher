// Stored agent notes of the given topics, newest first, at most 20. Notes
// exist only for completed nodes. run reads topics ["setup"] before creating
// worktrees for newly claimed nodes; also handy ad hoc.
//   cypherlite query --read-only --database <git-common-dir>/gbuild/<slug>/db --mode jsonl --param 'topics=["setup"]' < cypher/notes.cypher
MATCH (nt:Note) WHERE nt.topic IN $topics
RETURN nt.topic AS topic, nt.text AS text, nt.by_node AS by
ORDER BY nt.at DESC, text
LIMIT 20;
