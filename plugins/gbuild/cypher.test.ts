// Contract tests for the Cypher layer every gbuild skill drives: schema
// constraints, the validator, the reads, and run's write scripts — plus a
// token budget for a full run. Runs the real `cypherlite` binary against
// throwaway stores; skipped when it is not on PATH. Run via repo-root
// `npm test`.
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

// Params are always passed JSON-encoded, output is always JSONL — the same
// rules the skills follow.
const run = (db: string, input: string, params: Params = {}, extra: string[] = []) =>
  spawnSync(
    "cypherlite",
    [db, "--mode", "jsonl", ...extra, ...Object.entries(params).flatMap(([k, v]) => ["--param", `${k}=${JSON.stringify(v)}`])],
    { input, encoding: "utf8" },
  )

const parse = (stdout: string): Row[] => stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line))

const rows = (db: string, input: string, params: Params = {}): Row[] => {
  const r = run(db, input, params)
  assert.equal(r.status, 0, `cypherlite failed: ${r.stderr}${r.stdout}`)
  return parse(r.stdout)
}

const fresh = (): string => {
  const db = join(mkdtempSync(join(tmpdir(), "gbuild-")), "db")
  mkdirSync(db)
  const r = run(db, script("schema.cypher"), {}, ["--snapshot-format", "json"])
  assert.equal(r.status, 0, r.stderr)
  return db
}

const load = (plan: string): string => {
  const db = fresh()
  const r = run(db, plan)
  assert.equal(r.status, 0, r.stderr)
  return db
}

const exampleStore = () => load(example)
const checks = (db: string) => rows(db, script("validate.cypher")).map((r) => r.check)
const states = (db: string) => Object.fromEntries(rows(db, script("status.cypher")).map((r) => [r.slug, r.state]))
const claim = (db: string) => rows(db, script("dispatch.cypher"))
const record = (db: string, results: Row[]) => rows(db, script("record.cypher"), { results })

const times = { started_at: "2026-09-26T10:00:00Z", completed_at: "2026-09-26T10:05:00Z" }
const pass = (slug: string, outputs: Params) => ({ slug, verdict: "pass", failed_criteria: [], outputs, ...times })

// A realistic graph for the token budget: `waves` waves of `width` code nodes,
// each reading two outputs of the wave below.
const layered = (waves: number, width: number): string => {
  const lines = [
    ".begin",
    "CREATE (f:Feature {feature: 'layered', destination: 'A layered graph for the token budget.', context: 'test', out_of_scope: []})",
    "CREATE (a1:Acceptance {id: 'a-1', text: 'every node lands'}) CREATE (f)-[:HAS_ACCEPTANCE]->(a1)",
  ]
  for (let w = 0; w < waves; w++) {
    for (let k = 0; k < width; k++) {
      const v = `n${w}_${k}`
      lines.push(
        `CREATE (${v}:GbuildNode:Code {slug: 'w${w}-node-${k}-does-a-realistic-thing', title: 'Implement part ${k} of wave ${w} properly', type: 'code', acceptance: ['the module exports the function with the documented signature', 'unit tests cover the empty, single and many-item cases and pass'], failure_policy: 'repair', model_tier: 'cheap', status: 'pending'})`,
        `CREATE (${v})-[:OUTPUT]->(${v}_o:Field {name: 'result', shape: '<list of changed file paths>'})`,
        `CREATE (${v})-[:SATISFIES]->(a1)`,
      )
      if (w > 0) {
        for (const j of new Set([k % width, (k + 1) % width])) {
          lines.push(
            `CREATE (${v})-[:DEPENDS_ON]->(n${w - 1}_${j}) CREATE (${v})-[:INPUT]->(:Field {name: 'from_${j}', shape: '<list of changed file paths>'})-[:FROM]->(n${w - 1}_${j}_o)`,
          )
        }
      }
    }
  }
  lines.push(";", ".commit", ".checkpoint")
  return lines.join("\n")
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

  test("feature reports acceptance coverage and nothing per node", () => {
    const [f] = rows(exampleStore(), script("feature.cypher"))
    assert.equal(f.feature, "example-diamond")
    assert.deepEqual(
      f.acceptance.map((a: Row) => [a.id, a.covered_by]),
      [
        ["a-1", ["b-consume-doubled", "c-consume-squared"]],
        ["a-2", ["d-join-and-sum"]],
      ],
    )
    assert.equal(f.nodes, undefined)
  })

  test("dispatch claims the whole frontier once, with only what an agent needs", () => {
    const db = exampleStore()
    const [a] = claim(db)
    assert.deepEqual(Object.keys(a).sort(), [
      "acceptance", "failure_policy", "inputs", "model_tier", "outputs", "slug", "title", "type", "verify",
    ])
    assert.equal(a.slug, "a-produce-shared-value")
    assert.deepEqual(a.outputs, [{ name: "value", shape: "<integer>" }])
    assert.deepEqual(claim(db), [], "nothing is ready while the root is in flight")
    assert.equal(states(db)["a-produce-shared-value"], "in_progress")
  })

  test("a full run: fan-out, input flow, and the join waiting for both branches", () => {
    const db = exampleStore()
    assert.deepEqual(claim(db).map((n) => n.slug), ["a-produce-shared-value"])
    record(db, [pass("a-produce-shared-value", { value: 7 })])

    const wave1 = claim(db)
    assert.deepEqual(wave1.map((n) => n.slug), ["b-consume-doubled", "c-consume-squared"])
    assert.ok(wave1.every((n) => n.inputs[0].value === 7), "a's value flows into both branches")

    record(db, [pass("b-consume-doubled", { doubled: 14 })])
    assert.deepEqual(claim(db), [], "the join waits for c")
    record(db, [pass("c-consume-squared", { squared: 49 })])

    const [d] = claim(db)
    assert.deepEqual(d.inputs.map((i: Row) => i.value), [14, 49])
    record(db, [pass("d-join-and-sum", { sum: 63 })])
    assert.deepEqual(claim(db), [])
    assert.deepEqual(checks(db), [])
  })

  test("record batches a wave: completes passes, keeps failures in progress", () => {
    const db = exampleStore()
    claim(db)
    record(db, [pass("a-produce-shared-value", { value: 7 })])
    claim(db)
    const results = record(db, [
      pass("b-consume-doubled", { doubled: 14 }),
      { slug: "c-consume-squared", verdict: "fail", failed_criteria: ["output.squared equals input.value raised to the power of 2"] },
    ])
    assert.deepEqual(
      results.map((r) => [r.slug, r.verdict, r.completed, r.attempt]),
      [
        ["b-consume-doubled", "pass", true, 1],
        ["c-consume-squared", "fail", false, 1],
      ],
    )
    assert.equal(states(db)["c-consume-squared"], "in_progress")
    const [retry] = record(db, [pass("c-consume-squared", { squared: 49 })])
    assert.equal(retry.attempt, 2)
    assert.equal(retry.completed, true)
    const c = rows(db, script("status.cypher")).find((r) => r.slug === "c-consume-squared")
    assert.equal(c?.review_attempts, 2)
  })

  test("a pass missing outputs is recorded as a failed review naming them", () => {
    const db = exampleStore()
    claim(db)
    const [r] = record(db, [pass("a-produce-shared-value", { wrong: 1 })])
    assert.equal(r.verdict, "fail")
    assert.equal(r.completed, false)
    assert.deepEqual(r.missing_outputs, ["value"])
    const [a] = rows(db, script("node.cypher"), { slug: "a-produce-shared-value" })
    assert.deepEqual(a.reviews[0].failed_criteria, ["missing output value: value"])
  })

  test("record ignores nodes that are not in progress", () => {
    const db = exampleStore()
    assert.deepEqual(record(db, [pass("a-produce-shared-value", { value: 7 }), pass("ghost", {})]), [])
    assert.equal(states(db)["a-produce-shared-value"], "frontier")
  })

  test("one nested output value rejects the whole batch", () => {
    const db = exampleStore()
    claim(db)
    record(db, [pass("a-produce-shared-value", { value: 7 })])
    claim(db)
    const r = run(db, script("record.cypher"), {
      results: [pass("b-consume-doubled", { doubled: 14 }), pass("c-consume-squared", { squared: { nested: 49 } })],
    })
    assert.notEqual(r.status, 0)
    assert.match(r.stderr + r.stdout, /InvalidPropertyType/)
    assert.equal(states(db)["b-consume-doubled"], "in_progress", "b was not recorded either")
  })

  test("progress summarises each wave; the graph is done when nothing is open", () => {
    const db = exampleStore()
    claim(db)
    record(db, [pass("a-produce-shared-value", { value: 7 })])
    assert.deepEqual(
      rows(db, script("progress.cypher")).map((w) => [w.wave, w.total, w.completed, w.frontier, w.blocked, w.open]),
      [
        [0, 1, 1, 0, 0, []],
        [1, 2, 0, 2, 0, ["b-consume-doubled", "c-consume-squared"]],
        [2, 1, 0, 0, 1, ["d-join-and-sum"]],
      ],
    )
    claim(db)
    record(db, [pass("b-consume-doubled", { doubled: 14 }), pass("c-consume-squared", { squared: 49 })])
    claim(db)
    record(db, [pass("d-join-and-sum", { sum: 63 })])
    assert.ok(rows(db, script("progress.cypher")).every((w) => w.open.length === 0))
  })

  test("attention lists only what needs a decision", () => {
    const db = exampleStore()
    assert.deepEqual(rows(db, script("attention.cypher")), [])
    claim(db)
    assert.deepEqual(rows(db, script("attention.cypher")), [
      { slug: "a-produce-shared-value", reason: "in_progress", detail: [] },
    ])
    record(db, [{ slug: "a-produce-shared-value", verdict: "fail", failed_criteria: ["output.value is a single integer"] }])
    rows(db, script("set-status.cypher"), { slugs: ["a-produce-shared-value"], status: "failed" })
    assert.deepEqual(
      rows(db, script("attention.cypher")).map((r) => [r.reason, r.slug, r.detail]),
      [
        ["blocked-by-failed", "b-consume-doubled", ["a-produce-shared-value"]],
        ["blocked-by-failed", "c-consume-squared", ["a-produce-shared-value"]],
        ["blocked-by-failed", "d-join-and-sum", ["a-produce-shared-value"]],
        ["failed", "a-produce-shared-value", ["output.value is a single integer"]],
      ],
    )
  })

  test("a cancelled dependency counts as satisfied; completed cannot be set directly", () => {
    const db = exampleStore()
    claim(db)
    record(db, [pass("a-produce-shared-value", { value: 7 })])
    claim(db)
    record(db, [pass("b-consume-doubled", { doubled: 14 })])
    assert.deepEqual(rows(db, script("set-status.cypher"), { slugs: ["c-consume-squared"], status: "cancelled" }), [
      { slug: "c-consume-squared", status: "cancelled" },
    ])
    assert.deepEqual(claim(db).map((n) => n.slug), ["d-join-and-sum"])
    assert.deepEqual(rows(db, script("set-status.cypher"), { slugs: ["d-join-and-sum"], status: "completed" }), [])
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
    claim(db)
    record(db, [pass("a-produce-shared-value", { value: 7 })])
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
    const writes = readdirSync(join(root, "cypher")).filter((f) => /\b(CREATE|SET)\b/.test(script(f).replace(/^\/\/.*$/gm, "")))
    assert.deepEqual(writes.sort(), ["dispatch.cypher", "record.cypher", "schema.cypher", "set-status.cypher"])
    for (const f of writes) assert.match(script(f).trimEnd(), /\.checkpoint$/, `${f} must end with .checkpoint`)
    assert.match(example.trimEnd(), /\.checkpoint$/)
  })

  test("token budget: a 40-node run costs two calls per wave and reads only its own wave", () => {
    const waves = 8
    const width = 5
    const db = load(layered(waves, width))
    let calls = 0
    let bytes = 0
    let largest = 0
    const call = (name: string, params: Params = {}) => {
      const r = run(db, script(name), params)
      assert.equal(r.status, 0, r.stderr)
      calls++
      bytes += r.stdout.length
      largest = Math.max(largest, r.stdout.length)
      return parse(r.stdout)
    }

    for (;;) {
      const wave = call("dispatch.cypher")
      if (wave.length === 0) break
      assert.equal(wave.length, width)
      call("record.cypher", { results: wave.map((n) => pass(n.slug, { result: [`src/${n.slug}.ts`] })) })
    }
    const done = call("progress.cypher")

    assert.ok(done.every((w) => w.open.length === 0), "the run finished")
    assert.equal(calls, 2 * waves + 2, "dispatch + record per wave, one empty dispatch, one progress")
    assert.ok(largest < 4_000, `largest single read was ${largest} bytes`)
    assert.ok(bytes < 30_000, `whole run read ${bytes} bytes`)
    assert.ok(rows(db, script("progress.cypher")).length === waves)
  })
})
