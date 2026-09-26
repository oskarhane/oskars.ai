// A worked 4-node diamond: A produces a value, B and C each consume it
// independently, D joins both. This is exactly the script plan writes for a
// new feature — one atomic statement, piped into the store:
//   cypherlite .gbuild/<slug>/db < plan.cypher
// Variables (f, a1, a, a_value, ...) are only scoped to this one statement, so
// the whole graph is created in a single CREATE chain.
.begin
CREATE (f:Feature {
  feature: 'example-diamond',
  destination: 'A tiny worked example: A produces a shared value, B and C each consume it independently, D joins both.',
  context: "Ships with the plugin as the toy graph used in gbuild's own tests. Not a real feature.",
  out_of_scope: ['Anything beyond demonstrating fan-out and join scheduling.']
})
CREATE (a1:Acceptance {id: 'a-1', text: 'run dispatches B and C concurrently, not one after the other'})
CREATE (a2:Acceptance {id: 'a-2', text: 'D does not start until both B and C are recorded completed'})
CREATE (f)-[:HAS_ACCEPTANCE]->(a1), (f)-[:HAS_ACCEPTANCE]->(a2)

CREATE (a:GbuildNode:Chore {
  slug: 'a-produce-shared-value', title: 'Produce the shared value B and C both need', type: 'chore',
  acceptance: ['output.value is a single integer'],
  failure_policy: 'retry', model_tier: 'cheap', status: 'pending'
})
CREATE (a)-[:OUTPUT]->(a_value:Field {name: 'value', shape: '<integer>'})

CREATE (b:GbuildNode:Code {
  slug: 'b-consume-doubled', title: 'Consume the shared value, produce its double', type: 'code',
  acceptance: ['output.doubled equals input.value multiplied by 2'],
  failure_policy: 'repair', model_tier: 'cheap', status: 'pending'
})
CREATE (b)-[:DEPENDS_ON]->(a)
CREATE (b)-[:INPUT]->(:Field {name: 'value', shape: '<integer>'})-[:FROM]->(a_value)
CREATE (b)-[:OUTPUT]->(b_doubled:Field {name: 'doubled', shape: '<integer>'})
CREATE (b)-[:SATISFIES]->(a1)

CREATE (c:GbuildNode:Code {
  slug: 'c-consume-squared', title: 'Consume the shared value, produce its square', type: 'code',
  acceptance: ['output.squared equals input.value raised to the power of 2'],
  failure_policy: 'repair', model_tier: 'cheap', status: 'pending'
})
CREATE (c)-[:DEPENDS_ON]->(a)
CREATE (c)-[:INPUT]->(:Field {name: 'value', shape: '<integer>'})-[:FROM]->(a_value)
CREATE (c)-[:OUTPUT]->(c_squared:Field {name: 'squared', shape: '<integer>'})
CREATE (c)-[:SATISFIES]->(a1)

CREATE (d:GbuildNode:Code {
  slug: 'd-join-and-sum', title: 'Join B and C, produce their sum', type: 'code',
  acceptance: ['output.sum equals input.doubled plus input.squared',
               'only runs after both b-consume-doubled and c-consume-squared are recorded completed'],
  failure_policy: 'repair', model_tier: 'cheap', status: 'pending'
})
CREATE (d)-[:DEPENDS_ON]->(b), (d)-[:DEPENDS_ON]->(c)
CREATE (d)-[:INPUT]->(:Field {name: 'doubled', shape: '<integer>'})-[:FROM]->(b_doubled)
CREATE (d)-[:INPUT]->(:Field {name: 'squared', shape: '<integer>'})-[:FROM]->(c_squared)
CREATE (d)-[:OUTPUT]->(:Field {name: 'sum', shape: '<integer>'})
CREATE (d)-[:SATISFIES]->(a2);
.commit
.checkpoint
