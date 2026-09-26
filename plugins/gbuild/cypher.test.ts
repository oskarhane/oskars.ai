// Contract tests for the Cypher layer every gbuild skill drives: schema
// constraints, the validator, status/node/feature reads, and the run write
// scripts. Runs the real `cypherlite` binary against throwaway stores; skipped
// when it is not on PATH. Run via repo-root `npm test`.
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { copyFileSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import test, { describe } from "node:test"
import { fileURLToPath } from "node:url"

const root = dirname(fileURLToPath(import.meta.url))
const script = (name: string) => readFileSync(join(root, "cypher", name), "utf8")
const example = readFileSync(join(root, "templates", "example.cypher"), "utf8")
const hasCypherlite = spawnSync("cypherlite", ["--version"]).status === 0

type Row = Record<string, any>
type Params = Record<string, unknown>

// Params are always passed JSON-encoded — the same rule the skills follow
// (bare values that start with a digit, like timestamps, are rejected).
const run = (db: string, input: string, params: Params = {}, extra: string[] = []) =>
  spawnSync(
    "cypherlite",
    [db, "-json", ...extra, ...Object.entries(params).flatMap(([k, v]) => ["--param", `${k}=${JSON.stringify(v)}`])],
    { input, encoding: "utf8" },
  )

const rows = (db: string, input: string, params: Params = {}): Row[] => {
  const r = run(db, input, params)
  assert.equal(r.status, 0, `cypherlite failed: ${r.stderr}${r.stdout}`)
  return r.stdout.trim() === "" ? [] : JSON.parse(r.stdout)
}

const fresh = (): string => {
  const db = join(mkdtempSync(join(tmpdir(), "gbuild-")), "db")
  mkdirSync(db)
  const r = run(db, script("schema.cypher"), {}, ["--snapshot-format", "json"])
  assert.equal(r.status, 0, r.stderr)
  return db
}

const exampleStore = (): string => {
  const db = fresh()
  const r = run(db, example)
  assert.equal(r.status, 0, r.stderr)
  return db
}

const checks = (db: string) => rows(db, script("validate.cypher")).map((r) => r.check)
const states = (db: string) =>
  Object.fromEntries(rows(db, script("status.cypher")).map((r) => [r.slug, r.state]))

// Drive one node through dispatch -> passing review -> complete, as run does.
const finish = (db: string, slug: string, outputs: Params) => {
  assert.deepEqual(rows(db, script("dispatch.cypher"), { slugs: [slug] }), [{ dispatched: slug }])
  rows(db, script("record-review.cypher"), { slug, verdict: "pass", failed_criteria: [] })
  const [done] = rows(db, script("complete.cypher"), {
    slug,
    outputs,
    started_at: "2026-09-26T10:00:00Z",
    completed_at: "2026-09-26T10:05:00Z",
  })
  assert.equal(done.completed, true, JSON.stringify(done))
}

describe("gbuild cypher layer", { skip: !hasCypherlite && "cypherlite not on PATH" }, () => {
  test("schema installs every constraint it declares", () => {
    const db = fresh()
    const declared = script("schema.cypher").match(/^CREATE CONSTRAINT/gm)?.length
    const [{ n }] = rows(db, "SHOW CONSTRAINTS YIELD name RETURN count(name) AS n")
    assert.equal(n, declared)
  })

  test("the worked example validates clean", () => {
    assert.deepEqual(checks(exampleStore()), [])
  })

  test("status layers the example into waves with a single root frontier", () => {
    const status = rows(exampleStore(), script("status.cypher"))
    assert.deepEqual(
      status.map((r) => [r.wave, r.slug, r.state]),
      [
        [0, "a-produce-shared-value", "frontier"],
        [1, "b-consume-doubled", "blocked"],
        [1, "c-consume-squared", "blocked"],
        [2, "d-join-and-sum", "blocked"],
      ],
    )
    assert.deepEqual(status[3].waiting_on, ["b-consume-doubled", "c-consume-squared"])
  })

  test("node resolves inputs through FROM to the upstream outputs", () => {
    const [d] = rows(exampleStore(), script("node.cypher"), { slug: "d-join-and-sum" })
    assert.deepEqual(d.depends_on, ["b-consume-doubled", "c-consume-squared"])
    assert.deepEqual(
      d.inputs.map((i: Row) => [i.name, i.from]),
      [
        ["doubled", "b-consume-doubled.output.doubled"],
        ["squared", "c-consume-squared.output.squared"],
      ],
    )
    assert.deepEqual(d.outputs.map((o: Row) => o.name), ["sum"])
    assert.deepEqual(d.satisfies.map((a: Row) => a.id), ["a-2"])
  })

  test("feature reports acceptance coverage and every node", () => {
    const [f] = rows(exampleStore(), script("feature.cypher"))
    assert.equal(f.feature, "example-diamond")
    assert.deepEqual(
      f.acceptance.map((a: Row) => [a.id, a.covered_by]),
      [
        ["a-1", ["b-consume-doubled", "c-consume-squared"]],
        ["a-2", ["d-join-and-sum"]],
      ],
    )
    assert.equal(f.nodes.length, 4)
  })

  test("a full run: fan-out, input flow, and the join waiting for both branches", () => {
    const db = exampleStore()
    finish(db, "a-produce-shared-value", { value: 7 })
    assert.deepEqual(states(db), {
      "a-produce-shared-value": "completed",
      "b-consume-doubled": "frontier",
      "c-consume-squared": "frontier",
      "d-join-and-sum": "blocked",
    })
    const [b] = rows(db, script("node.cypher"), { slug: "b-consume-doubled" })
    assert.equal(b.inputs[0].value, 7)

    finish(db, "b-consume-doubled", { doubled: 14 })
    assert.equal(states(db)["d-join-and-sum"], "blocked")
    finish(db, "c-consume-squared", { squared: 49 })
    assert.equal(states(db)["d-join-and-sum"], "frontier")

    const [d] = rows(db, script("node.cypher"), { slug: "d-join-and-sum" })
    assert.deepEqual(d.inputs.map((i: Row) => i.value), [14, 49])
    finish(db, "d-join-and-sum", { sum: 63 })
    assert.deepEqual(checks(db), [])
  })

  test("dispatch only moves pending nodes whose dependencies are satisfied", () => {
    const db = exampleStore()
    const dispatched = rows(db, script("dispatch.cypher"), { slugs: ["a-produce-shared-value", "d-join-and-sum"] })
    assert.deepEqual(dispatched, [{ dispatched: "a-produce-shared-value" }])
    assert.deepEqual(rows(db, script("dispatch.cypher"), { slugs: ["a-produce-shared-value"] }), [])
  })

  test("complete refuses without a passing review or with a missing output", () => {
    const db = exampleStore()
    const slug = "a-produce-shared-value"
    const times = { started_at: "2026-09-26T10:00:00Z", completed_at: "2026-09-26T10:01:00Z" }
    rows(db, script("dispatch.cypher"), { slugs: [slug] })

    const [unreviewed] = rows(db, script("complete.cypher"), { slug, outputs: { value: 7 }, ...times })
    assert.equal(unreviewed.completed, false)
    assert.equal(unreviewed.has_passing_review, false)

    rows(db, script("record-review.cypher"), { slug, verdict: "fail", failed_criteria: ["output.value is a single integer"] })
    const [failedOnly] = rows(db, script("complete.cypher"), { slug, outputs: { value: 7 }, ...times })
    assert.equal(failedOnly.completed, false)

    const [pass] = rows(db, script("record-review.cypher"), { slug, verdict: "pass", failed_criteria: [] })
    assert.equal(pass.attempt, 2)
    const [missing] = rows(db, script("complete.cypher"), { slug, outputs: { wrong: 1 }, ...times })
    assert.equal(missing.completed, false)
    assert.deepEqual(missing.missing_outputs, ["value"])
    assert.equal(missing.status, "in_progress")

    const [status] = rows(db, script("status.cypher")).filter((r) => r.slug === slug)
    assert.equal(status.review_attempts, 2)
    assert.equal(status.last_verdict, "pass")
  })

  test("a nested output value is rejected without a partial write", () => {
    const db = exampleStore()
    const slug = "a-produce-shared-value"
    rows(db, script("dispatch.cypher"), { slugs: [slug] })
    rows(db, script("record-review.cypher"), { slug, verdict: "pass", failed_criteria: [] })
    const r = run(db, script("complete.cypher"), {
      slug,
      outputs: { value: { nested: 1 } },
      started_at: "2026-09-26T10:00:00Z",
      completed_at: "2026-09-26T10:01:00Z",
    })
    assert.notEqual(r.status, 0)
    assert.match(r.stderr + r.stdout, /InvalidPropertyType/)
    assert.equal(states(db)[slug], "in_progress")
  })

  test("a cancelled dependency counts as satisfied; completed cannot be set directly", () => {
    const db = exampleStore()
    finish(db, "a-produce-shared-value", { value: 7 })
    finish(db, "b-consume-doubled", { doubled: 14 })
    rows(db, script("set-status.cypher"), { slug: "c-consume-squared", status: "cancelled" })
    assert.equal(states(db)["d-join-and-sum"], "frontier")
    assert.deepEqual(rows(db, script("set-status.cypher"), { slug: "d-join-and-sum", status: "completed" }), [])
  })

  test("the engine rejects writes that break the schema", () => {
    const db = exampleStore()
    const node = "slug: 'x-new', title: 'x', type: 'code', acceptance: ['a'], failure_policy: 'retry', model_tier: 'cheap'"
    const rejected = [
      `CREATE (:GbuildNode:Code {slug: 'b-consume-doubled', title: 'dup', type: 'code', acceptance: ['a'], failure_policy: 'retry', model_tier: 'cheap', status: 'pending'})`,
      `CREATE (:GbuildNode:Code {${node}})`,
      `CREATE (:GbuildNode:Code {${node}, status: 'pending', acceptance: 'not a list'})`,
      `CREATE (:Acceptance {id: 'a-1', text: 'dup id'})`,
      `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:REVIEWED]->(:Review {attempt: 'one', verdict: 'pass', at: 'x'})`,
    ]
    for (const cypher of rejected) {
      const r = run(db, cypher)
      assert.notEqual(r.status, 0, `expected rejection: ${cypher}`)
      assert.match(r.stderr + r.stdout, /ConstraintValidationFailed/)
    }
  })

  const violations: [string, string][] = [
    ["cycle", `MATCH (a:GbuildNode {slug: 'a-produce-shared-value'}), (d:GbuildNode {slug: 'd-join-and-sum'}) CREATE (a)-[:DEPENDS_ON]->(d)`],
    ["acceptance-uncovered", `MATCH (f:Feature) CREATE (f)-[:HAS_ACCEPTANCE]->(:Acceptance {id: 'a-3', text: 'nobody covers me'})`],
    ["acceptance-unlinked", `MATCH (n:GbuildNode {slug: 'd-join-and-sum'}) CREATE (n)-[:SATISFIES]->(:Acceptance {id: 'a-3', text: 'orphan'})`],
    ["bad-type", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.type = 'banana'`],
    ["bad-failure-policy", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.failure_policy = 'yolo'`],
    ["bad-model-tier", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.model_tier = 'huge'`],
    ["bad-status", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.status = 'done'`],
    ["type-label", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.type = 'test'`],
    ["bad-slug", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.slug = 'Bad_Slug'`],
    ["bad-acceptance", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.acceptance = ['  ']`],
    ["verify-target", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.verify = 'ghost'`],
    ["orphan-chore", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) REMOVE n:Code SET n:Chore, n.type = 'chore' WITH n MATCH (d:GbuildNode {slug: 'd-join-and-sum'})-[r:DEPENDS_ON]->(n) DELETE r`],
    ["no-output", `MATCH (:GbuildNode {slug: 'd-join-and-sum'})-[:OUTPUT]->(f:Field) DETACH DELETE f`],
    ["dependency-without-from", `MATCH (d:GbuildNode {slug: 'd-join-and-sum'}), (a:GbuildNode {slug: 'a-produce-shared-value'}) CREATE (d)-[:DEPENDS_ON]->(a)`],
    ["from-without-dependency", `MATCH (d:GbuildNode {slug: 'd-join-and-sum'}), (:GbuildNode {slug: 'a-produce-shared-value'})-[:OUTPUT]->(v:Field) CREATE (d)-[:INPUT]->(:Field {name: 'raw', shape: '<integer>'})-[:FROM]->(v)`],
    ["bad-from", `MATCH (:GbuildNode {slug: 'b-consume-doubled'})-[:OUTPUT]->(o:Field), (:GbuildNode {slug: 'c-consume-squared'})-[:OUTPUT]->(p:Field) CREATE (o)-[:FROM]->(p)`],
    ["duplicate-field", `MATCH (n:GbuildNode {slug: 'd-join-and-sum'}) CREATE (n)-[:OUTPUT]->(:Field {name: 'sum', shape: '<integer>'})`],
    ["field-owner", `CREATE (:Field {name: 'loose', shape: '<integer>'})`],
    ["bad-edge", `MATCH (f:Feature), (n:GbuildNode {slug: 'd-join-and-sum'}) CREATE (f)-[:DEPENDS_ON]->(n)`],
    ["unknown-node", `CREATE (:Stray {x: 1})`],
    ["feature-count", `CREATE (:Feature {feature: 'two', destination: 'x', context: 'x', out_of_scope: []})`],
    ["completed-without-pass", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.status = 'completed'`],
    ["completed-missing-output", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.status = 'completed' CREATE (n)-[:REVIEWED]->(:Review {attempt: 1, verdict: 'pass', at: 'x'})`],
    ["bad-review", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:REVIEWED]->(:Review {attempt: 1, verdict: 'maybe', at: 'x'})`],
  ]
  for (const [check, cypher] of violations) {
    test(`validate flags ${check}`, () => {
      const db = exampleStore()
      const r = run(db, cypher)
      assert.equal(r.status, 0, `setup failed: ${r.stderr}`)
      assert.ok(checks(db).includes(check), `expected ${check} in ${JSON.stringify(checks(db))}`)
    })
  }

  test("a failing statement inside .begin/.commit leaves the store untouched", () => {
    const db = fresh()
    const broken = example.replace("CREATE (d)-[:SATISFIES]->(a2);", "CREATE (d)-[:SATISFIES]->(a2);\nCREATE (:Acceptance {id: 'a-1', text: 'dup'});")
    assert.notEqual(run(db, broken).status, 0)
    assert.deepEqual(rows(db, "MATCH (n) RETURN count(n) AS n"), [{ n: 0 }])
  })

  test("writes land in graph.json immediately and a clone of just that file is a full store", () => {
    const db = exampleStore()
    writeFileSync(join(db, ".gitignore"), "*\n!.gitignore\n!graph.json\n")
    finish(db, "a-produce-shared-value", { value: 7 })
    const onDisk = JSON.parse(readFileSync(join(db, "graph.json"), "utf8"))
    const a = onDisk.nodes.find((n: Row) => n.properties.slug === "a-produce-shared-value")
    assert.equal(a.properties.status, "completed")

    const clone = join(mkdtempSync(join(tmpdir(), "gbuild-clone-")), "db")
    mkdirSync(clone)
    for (const f of [".gitignore", "graph.json"]) copyFileSync(join(db, f), join(clone, f))
    assert.equal(states(clone)["b-consume-doubled"], "frontier")
    const dup = run(clone, `CREATE (:Acceptance {id: 'a-1', text: 'dup'})`)
    assert.match(dup.stderr + dup.stdout, /ConstraintValidationFailed/)
  })

  test("every write script ends with .checkpoint so graph.json stays current", () => {
    const writes = readdirSync(join(root, "cypher")).filter((f) => /CREATE|SET/.test(script(f).replace(/^\/\/.*$/gm, "")))
    assert.ok(writes.length >= 5)
    for (const f of writes) assert.match(script(f).trimEnd(), /\.checkpoint$/, `${f} must end with .checkpoint`)
    assert.match(example.trimEnd(), /\.checkpoint$/)
  })
})
