# Ad-hoc queries

The plugin scripts (`reference/cypher.md` § Script catalog) cover everything the skills do. These are for
the questions in between. Run them with `cypherlite .gbuild/<feature>/db --mode jsonl "<query>"`, one at a
time; return only the columns you need and keep a `LIMIT` on anything that can grow.

```cypher
-- the whole plan with progress
MATCH (n:GbuildNode) RETURN n.slug, n.type, n.status, n.title ORDER BY n.slug

-- nodes by type
MATCH (n:Code) RETURN n.slug, n.title

-- full transitive dependency chain of a node
MATCH (n:GbuildNode {slug: 'd-join-and-sum'})-[:DEPENDS_ON*]->(d) RETURN DISTINCT d.slug

-- what waits on a node
MATCH (n:GbuildNode {slug: 'a-produce-shared-value'})<-[:DEPENDS_ON]-(w) RETURN w.slug

-- where a node's inputs come from
MATCH (:GbuildNode {slug: 'd-join-and-sum'})-[:INPUT]->(i)-[:FROM]->(o)<-[:OUTPUT]-(u)
RETURN i.name, u.slug, o.name, o.value

-- everything downstream of a node's output field (data lineage)
MATCH (:GbuildNode {slug: 'a-produce-shared-value'})-[:OUTPUT]->(o)<-[:FROM]-(i)<-[:INPUT]-(c)
RETURN o.name, c.slug, i.name

-- critical path (longest dependency chain)
MATCH p = (n:GbuildNode)-[:DEPENDS_ON*]->(m:GbuildNode) RETURN [x IN nodes(p) | x.slug] AS path
ORDER BY length(p) DESC LIMIT 1

-- which nodes cover each feature criterion
MATCH (a:Acceptance)<-[:SATISFIES]-(n:GbuildNode) RETURN a.id, collect(n.slug)

-- nodes that needed a repair pass
MATCH (n:GbuildNode)-[:REVIEWED]->(r:Review {verdict: 'fail'}) RETURN n.slug, count(r) AS failed_reviews
```
