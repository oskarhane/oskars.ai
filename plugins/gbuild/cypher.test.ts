// Contract tests for the Cypher layer every gbuild skill drives: schema
// constraints, the validator, the reads, run's write scripts, the agents'
// read-only brief and self-check, and the notes and symbols agents leave for
// later nodes — plus a token budget for a full run. Runs
// the real `cypherlite` binary against throwaway stores; skipped when it is
// not on PATH. Run via repo-root `npm test`.
import assert from "node:assert/strict"
import { type SpawnSyncReturns, spawnSync } from "node:child_process"
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
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
    ["query", "--database", db, "--mode", "jsonl", ...extra, ...Object.entries(params).flatMap(([k, v]) => ["--param", `${k}=${JSON.stringify(v)}`])],
    { input, encoding: "utf8" },
  )

const parse = (stdout: string): Row[] => stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line))

const ok = (r: SpawnSyncReturns<string>): Row[] => {
  assert.equal(r.status, 0, `cypherlite failed: ${r.stderr}${r.stdout}`)
  return parse(r.stdout)
}

const rows = (db: string, input: string, params: Params = {}, extra: string[] = []): Row[] => ok(run(db, input, params, extra))

const one = (rs: Row[]): Row => {
  assert.equal(rs.length, 1, `expected one row, got ${JSON.stringify(rs)}`)
  return rs[0] as Row
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
const node = (db: string, slug: string) => one(rows(db, script("node.cypher"), { slug }))
const brief = (db: string, slug: string) => one(rows(db, script("brief.cypher"), { slug }, ["--read-only"]))
const topics = ["setup", "testing", "conventions", "gotcha"]
const readNotes = (db: string, of: string[] = topics) => rows(db, script("notes.cypher"), { topics: of }, ["--read-only"])
const readSymbols = (db: string) => rows(db, script("symbols.cypher"), {}, ["--read-only"])
const routing = ["failure_policy", "model_tier", "slug", "type"]

type Verdict = { slug: string; verdict: string; failed_criteria: string[] }
const pass = (slug: string): Verdict => ({ slug, verdict: "pass", failed_criteria: [] })
const fail = (slug: string, ...failed_criteria: string[]): Verdict => ({ slug, verdict: "fail", failed_criteria })
const times = { started_at: "2026-09-26T10:00:00Z", completed_at: "2026-09-26T10:05:00Z" }
const result = (outputs: Params) => ({ outputs, ...times })

// result and review bound inline (what run does when there is no file) ...
const record = (db: string, verdict: Verdict, res: Params = {}, review: Params = {}) =>
  rows(db, script("record.cypher"), { verdict, result: res, review })
const land = (db: string, slug: string, outputs: Params) => record(db, pass(slug), result(outputs))
const landNoted = (db: string, slug: string, outputs: Params, notes: unknown[], symbols: unknown[] = []) =>
  one(record(db, pass(slug), { ...result(outputs), notes, symbols }))

// ... or read from the agents' inbox files with --fetch-params, exactly as run
// binds them. An undefined file is bound as {}.
const inboxFile = (name: string, content: unknown): string => {
  const file = join(mkdtempSync(join(tmpdir(), "gbuild-inbox-")), name)
  writeFileSync(file, JSON.stringify(content))
  return file
}
const recordFiles = (db: string, verdict: Verdict, res?: Params, review?: Params) => {
  const bind = (param: string, file: string, content?: Params) =>
    content === undefined ? ["--param", `${param}={}`] : ["--fetch-params", `${param}=${inboxFile(file, content)}`]
  return run(db, script("record.cypher"), { verdict }, [
    ...bind("result", `${verdict.slug}.json`, res),
    ...bind("review", `${verdict.slug}.review.json`, review),
  ])
}
const checkResult = (db: string, slug: string, res: unknown) =>
  one(rows(db, script("check-result.cypher"), { slug }, ["--read-only", "--fetch-params", `result=${inboxFile(`${slug}.json`, res)}`]))

// Two independent chains, A -> C and B -> D. A also reads an external input.
const chains = `.begin
CREATE (f:Feature {feature: 'chains', destination: 'Two independent chains.', context: 'test', out_of_scope: []})
CREATE (a1:Acceptance {id: 'a-1', text: 'each chain advances on its own'}) CREATE (f)-[:HAS_ACCEPTANCE]->(a1)
CREATE (a:GbuildNode:Code {slug: 'a-first', title: 'A', type: 'code', acceptance: ['a works'], failure_policy: 'repair', model_tier: 'cheap', status: 'pending'})
CREATE (a)-[:INPUT]->(:Field {name: 'spec', shape: '<the spec section of README.md>'})
CREATE (a)-[:OUTPUT]->(a_out:Field {name: 'out', shape: '<integer>'})
CREATE (b:GbuildNode:Code {slug: 'b-first', title: 'B', type: 'code', acceptance: ['b works'], failure_policy: 'repair', model_tier: 'strong', status: 'pending'})
CREATE (b)-[:OUTPUT]->(b_out:Field {name: 'out', shape: '<integer>'})
CREATE (c:GbuildNode:Code {slug: 'c-after-a', title: 'C', type: 'code', acceptance: ['c works'], failure_policy: 'retry', model_tier: 'cheap', status: 'pending'})
CREATE (c)-[:DEPENDS_ON]->(a) CREATE (c)-[:INPUT]->(:Field {name: 'out', shape: '<integer>'})-[:FROM]->(a_out)
CREATE (c)-[:OUTPUT]->(:Field {name: 'out', shape: '<integer>'}) CREATE (c)-[:SATISFIES]->(a1)
CREATE (d:GbuildNode:Code {slug: 'd-after-b', title: 'D', type: 'code', acceptance: ['d works'], failure_policy: 'retry', model_tier: 'cheap', status: 'pending'})
CREATE (d)-[:DEPENDS_ON]->(b) CREATE (d)-[:INPUT]->(:Field {name: 'out', shape: '<integer>'})-[:FROM]->(b_out)
CREATE (d)-[:OUTPUT]->(:Field {name: 'out', shape: '<integer>'}) CREATE (d)-[:SATISFIES]->(a1);
.commit`

// A router: pick chooses one of two branches by slug; join reads its other
// output and runs either way.
const router = `.begin
CREATE (f:Feature {feature: 'router', destination: 'A decision picks one branch.', context: 'test', out_of_scope: []})
CREATE (a1:Acceptance {id: 'a-1', text: 'only the chosen branch runs'}) CREATE (f)-[:HAS_ACCEPTANCE]->(a1)
CREATE (r:GbuildNode:Decision {slug: 'pick', title: 'Pick a branch', type: 'decision', acceptance: ['names one branch'], failure_policy: 'retry', model_tier: 'strong', status: 'pending'})
CREATE (r)-[:OUTPUT]->(ch:Field {name: 'choice', shape: '<slug of the chosen branch>'})
CREATE (r)-[:OUTPUT]->(bu:Field {name: 'budget', shape: '<integer>'})
CREATE (x:GbuildNode:Code {slug: 'x-branch', title: 'X', type: 'code', acceptance: ['x works'], failure_policy: 'repair', model_tier: 'cheap', status: 'pending'})
CREATE (x)-[:DEPENDS_ON]->(r) CREATE (x)-[:INPUT]->(:Field {name: 'choice', shape: '<slug>'})-[:FROM]->(ch)
CREATE (x)-[:OUTPUT]->(:Field {name: 'out', shape: '<integer>'}) CREATE (x)-[:SATISFIES]->(a1)
CREATE (y:GbuildNode:Code {slug: 'y-branch', title: 'Y', type: 'code', acceptance: ['y works'], failure_policy: 'repair', model_tier: 'cheap', status: 'pending'})
CREATE (y)-[:DEPENDS_ON]->(r) CREATE (y)-[:INPUT]->(:Field {name: 'choice', shape: '<slug>'})-[:FROM]->(ch)
CREATE (y)-[:OUTPUT]->(:Field {name: 'out', shape: '<integer>'}) CREATE (y)-[:SATISFIES]->(a1)
CREATE (j:GbuildNode:Code {slug: 'join', title: 'J', type: 'code', acceptance: ['j works'], failure_policy: 'repair', model_tier: 'cheap', status: 'pending'})
CREATE (j)-[:DEPENDS_ON]->(r) CREATE (j)-[:INPUT]->(:Field {name: 'budget', shape: '<integer>'})-[:FROM]->(bu)
CREATE (j)-[:OUTPUT]->(:Field {name: 'out', shape: '<integer>'}) CREATE (j)-[:SATISFIES]->(a1);
.commit`

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
  lines.push(";", ".commit")
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

  test("dispatch claims the whole frontier once and returns routing columns only", () => {
    const db = exampleStore()
    const a = one(claim(db))
    assert.deepEqual(Object.keys(a).sort(), routing)
    assert.deepEqual(a, { slug: "a-produce-shared-value", type: "chore", model_tier: "cheap", failure_policy: "retry" })
    assert.deepEqual(claim(db), [], "nothing is ready while the root is in flight")
    assert.equal(states(db)["a-produce-shared-value"], "in_progress")
    assert.doesNotMatch(script("dispatch.cypher"), /INPUT/)
  })

  test("dispatch schedules per node: a finished chain advances while the other is still running", () => {
    const db = load(chains)
    assert.deepEqual(checks(db), [])
    assert.deepEqual(claim(db).map((n) => n.slug), ["a-first", "b-first"])
    land(db, "a-first", { out: 1 })
    assert.deepEqual(claim(db), [{ slug: "c-after-a", type: "code", model_tier: "cheap", failure_policy: "retry" }])
    assert.equal(states(db)["b-first"], "in_progress")
    assert.equal(states(db)["d-after-b"], "blocked")
  })

  test("brief returns exactly the brief columns, read-only", () => {
    const db = exampleStore()
    assert.deepEqual(Object.keys(brief(db, "a-produce-shared-value")).sort(), [
      "acceptance", "failed_criteria", "inputs", "notes", "outputs", "slug", "title", "type", "verify",
    ])
    assert.deepEqual(rows(db, script("brief.cypher"), { slug: "ghost" }, ["--read-only"]), [])
  })

  test("brief and node resolve inputs with one text-identical block", () => {
    const inputs = (name: string) => script(name).match(/ +COLLECT \{\n +MATCH \(n\)-\[:INPUT\][\s\S]*?\} AS inputs/)?.[0]
    assert.ok(inputs("brief.cypher"))
    assert.equal(inputs("brief.cypher"), inputs("node.cypher"))
  })

  test("brief of a fresh frontier node: no input values, no failed criteria, no notes", () => {
    const db = load(chains)
    claim(db)
    const a = brief(db, "a-first")
    assert.equal(a.title, "A")
    assert.deepEqual(a.acceptance, ["a works"])
    assert.equal(a.verify, null)
    assert.deepEqual(a.inputs, [{ name: "spec", shape: "<the spec section of README.md>", from: null, value: null }])
    assert.deepEqual(a.outputs, [{ name: "out", shape: "<integer>" }])
    assert.deepEqual(a.failed_criteria, [])
    assert.deepEqual(a.notes, [])
    assert.deepEqual(brief(db, "c-after-a").inputs.map((i: Row) => [i.from, i.value]), [["a-first.output.out", null]])
  })

  test("brief of a node whose upstream completed carries the recorded output value", () => {
    const db = exampleStore()
    claim(db)
    land(db, "a-produce-shared-value", { value: 7 })
    const recorded = node(db, "a-produce-shared-value").outputs[0].value
    assert.equal(recorded, 7)
    assert.deepEqual(brief(db, "b-consume-doubled").inputs, [
      { name: "value", shape: "<integer>", from: "a-produce-shared-value.output.value", value: recorded },
    ])
  })

  test("brief of a retry carries the latest failed review's criteria", () => {
    const db = exampleStore()
    claim(db)
    record(db, fail("a-produce-shared-value", "output.value is a single integer"))
    assert.deepEqual(brief(db, "a-produce-shared-value").failed_criteria, ["output.value is a single integer"])
    record(db, pass("a-produce-shared-value"))
    const latest = node(db, "a-produce-shared-value").reviews.at(-1)
    assert.deepEqual(latest.failed_criteria, ["missing output value: value"])
    assert.deepEqual(brief(db, "a-produce-shared-value").failed_criteria, latest.failed_criteria)
  })

  test("brief serves every upstream note plus setup and testing notes from any node", () => {
    const db = load(chains)
    claim(db)
    const setup = "deps: `ln -s <FT>/node_modules node_modules`"
    assert.equal(landNoted(db, "a-first", { out: 1 }, [
      { topic: "conventions", text: "a: name files in kebab-case" },
      { topic: "gotcha", text: "a: the parser keeps trailing commas" },
      { topic: "setup", text: setup },
    ]).notes_added, 3)
    assert.equal(landNoted(db, "b-first", { out: 2 }, [
      { topic: "conventions", text: "b: errors are returned, never thrown" },
      { topic: "testing", text: "`npm test -- --test-name-pattern=<name>` runs one test" },
    ]).notes_added, 2)
    assert.deepEqual(claim(db).map((n) => n.slug), ["c-after-a", "d-after-b"])

    const seen = (slug: string) => brief(db, slug).notes.map((n: Row) => `${n.by} ${n.topic}`)
    assert.deepEqual(seen("c-after-a"), ["a-first conventions", "a-first gotcha", "a-first setup", "b-first testing"], "upstream first")
    assert.deepEqual(seen("d-after-b"), ["b-first testing", "b-first conventions", "a-first setup"])
    assert.ok(!brief(db, "d-after-b").notes.some((n: Row) => n.text.startsWith("a: ")), "an unrelated node's conventions and gotcha stay out")
    assert.deepEqual(brief(db, "c-after-a").notes[2], { topic: "setup", text: setup, by: "a-first" })
  })

  test("brief notes are transitive, upstream first and capped at 20", () => {
    const db = exampleStore()
    claim(db)
    const convention = { topic: "conventions", text: "values are plain integers, never strings" }
    landNoted(db, "a-produce-shared-value", { value: 7 }, [convention])
    claim(db)
    land(db, "b-consume-doubled", { doubled: 14 })
    land(db, "c-consume-squared", { squared: 49 })
    claim(db)
    assert.deepEqual(brief(db, "d-join-and-sum").notes, [{ ...convention, by: "a-produce-shared-value" }], "through nodes that wrote none")

    const flood = `MATCH (b:GbuildNode {slug: 'b-consume-doubled'})
UNWIND range(10, 34) AS i
CREATE (b)-[:WROTE]->(:Note {topic: 'setup', text: 'setup step ' + toString(i), by_node: b.slug, at: '2099-01-01T00:00:' + toString(i) + 'Z'})`
    ok(run(db, flood))
    const c = brief(db, "c-consume-squared").notes
    assert.equal(c.length, 20)
    assert.deepEqual(c[0], { ...convention, by: "a-produce-shared-value" }, "an upstream note outranks newer unrelated ones")
    assert.deepEqual(c.slice(1, 3).map((n: Row) => n.text), ["setup step 34", "setup step 33"], "then newest first")
  })

  test("a full run: fan-out, input flow, and the join waiting for both branches", () => {
    const db = exampleStore()
    assert.deepEqual(claim(db).map((n) => n.slug), ["a-produce-shared-value"])
    land(db, "a-produce-shared-value", { value: 7 })

    const wave1 = claim(db)
    assert.deepEqual(wave1.map((n) => n.slug), ["b-consume-doubled", "c-consume-squared"])
    assert.ok(wave1.every((n) => brief(db, n.slug).inputs[0].value === 7), "a's value flows into both branches")

    land(db, "b-consume-doubled", { doubled: 14 })
    assert.deepEqual(claim(db), [], "the join waits for c")
    land(db, "c-consume-squared", { squared: 49 })

    const d = one(claim(db))
    assert.deepEqual(brief(db, d.slug).inputs.map((i: Row) => i.value), [14, 49])
    land(db, "d-join-and-sum", { sum: 63 })
    assert.deepEqual(claim(db), [])
    assert.deepEqual(checks(db), [])
  })

  test("record takes one node per call: completes a pass, keeps a fail in progress", () => {
    const db = exampleStore()
    claim(db)
    land(db, "a-produce-shared-value", { value: 7 })
    claim(db)
    const results = [
      ...land(db, "b-consume-doubled", { doubled: 14 }),
      ...record(db, fail("c-consume-squared", "output.squared equals input.value raised to the power of 2")),
    ]
    assert.deepEqual(
      results.map((r) => [r.slug, r.verdict, r.completed, r.attempt]),
      [
        ["b-consume-doubled", "pass", true, 1],
        ["c-consume-squared", "fail", false, 1],
      ],
    )
    assert.deepEqual(Object.keys(results[0] ?? {}).sort(), [
      "attempt", "completed", "missing_outputs", "notes_added", "slug", "symbols_added", "unselected", "verdict",
    ])
    assert.equal(states(db)["c-consume-squared"], "in_progress")
    assert.deepEqual(node(db, "c-consume-squared").reviews[0].checklist, [], "no review file stores []")
    const retry = one(land(db, "c-consume-squared", { squared: 49 }))
    assert.equal(retry.attempt, 2)
    assert.equal(retry.completed, true)
    const c = rows(db, script("status.cypher")).find((r) => r.slug === "c-consume-squared")
    assert.equal(c?.review_attempts, 2)
  })

  test("record reads the inbox files: outputs, times and the review checklist round-trip", () => {
    const db = exampleStore()
    claim(db)
    const checklist = [
      "[pass] output.value is a single integer",
      "[pass] outputs: value is an <integer> (7)",
      "[pass] duplication: nothing reusable",
      "Issue (low): a.ts:3 imports an unused helper",
    ]
    const r = one(ok(recordFiles(db, pass("a-produce-shared-value"), result({ value: 7 }), { checklist })))
    assert.deepEqual([r.verdict, r.completed, r.attempt, r.missing_outputs], ["pass", true, 1, []])
    const a = node(db, "a-produce-shared-value")
    assert.deepEqual(a.outputs[0].value, 7)
    assert.deepEqual(a.reviews[0].checklist, checklist)
    const status = one(rows(db, script("status.cypher")).filter((s) => s.slug === "a-produce-shared-value"))
    assert.deepEqual([status.started_at, status.completed_at], [times.started_at, times.completed_at])

    claim(db)
    const long = "x".repeat(400)
    const noisy = [42, long, { nested: true }, ...Array.from({ length: 50 }, (_, i) => `Suggestion (low): ${i}`)]
    ok(recordFiles(db, fail("b-consume-doubled", "output.doubled equals input.value multiplied by 2"), undefined, { checklist: noisy }))
    const stored = node(db, "b-consume-doubled").reviews[0].checklist
    assert.equal(stored.length, 40, "the first 40 string entries")
    assert.equal(stored[0], long.slice(0, 300), "each cut to 300 chars")
    assert.equal(stored[1], "Suggestion (low): 0", "non-strings dropped")
  })

  test("record takes slug and verdict only from the verdict param, never from the result file", () => {
    const db = exampleStore()
    claim(db)
    const planted = { slug: "b-consume-doubled", verdict: "pass", failed_criteria: [], ...result({ value: 7 }) }
    const r = one(ok(recordFiles(db, fail("a-produce-shared-value", "output.value is a single integer"), planted)))
    assert.deepEqual([r.slug, r.verdict, r.completed, r.attempt], ["a-produce-shared-value", "fail", false, 1])
    assert.equal(states(db)["a-produce-shared-value"], "in_progress")
    assert.equal(node(db, "a-produce-shared-value").outputs[0].value, null, "a fail stores no outputs")
    assert.deepEqual(node(db, "a-produce-shared-value").reviews[0].failed_criteria, ["output.value is a single integer"])
    assert.equal(states(db)["b-consume-doubled"], "blocked")

    const again = one(ok(recordFiles(db, pass("a-produce-shared-value"), { ...planted, slug: "ghost", verdict: "fail", failed_criteria: ["planted"] })))
    assert.deepEqual([again.slug, again.verdict, again.completed], ["a-produce-shared-value", "pass", true])
    assert.deepEqual(node(db, "a-produce-shared-value").reviews[1].failed_criteria, [])
  })

  test("record stores notes and symbols only on completion: validated, trimmed, capped and de-duplicated", () => {
    const db = exampleStore()
    claim(db)
    const setup = { topic: "setup", text: "deps: `ln -s <FT>/node_modules node_modules`" }
    const helper = { name: "double", file: "src/double.ts", purpose: "doubles a number" }
    const extras = { notes: [setup], symbols: [helper] }
    const failed = one(ok(recordFiles(db, fail("a-produce-shared-value", "output.value is a single integer"), { ...result({ value: 7 }), ...extras })))
    assert.deepEqual([failed.completed, failed.notes_added, failed.symbols_added], [false, 0, 0], "a fail stores none")
    const short = one(record(db, pass("a-produce-shared-value"), { ...result({ wrong: 1 }), ...extras }))
    assert.deepEqual([short.completed, short.notes_added, short.symbols_added], [false, 0, 0], "a downgraded pass stores none")
    assert.deepEqual([readNotes(db), readSymbols(db)], [[], []])

    const long = "y".repeat(400)
    const notes = [
      { topic: "setup", text: `  ${setup.text}  ` },
      setup,
      { topic: "misc", text: "unknown topic" },
      { topic: "gotcha", text: "   " },
      { topic: "testing", text: 42 },
      { text: "no topic" },
      "a bare string",
      null,
      { topic: "gotcha", text: long },
      { topic: "testing", text: "t1" },
      { topic: "conventions", text: "c1" },
      { topic: "conventions", text: "c2" },
      { topic: "conventions", text: "c3 is past the cap" },
    ]
    const symbols = [
      { ...helper, name: ` ${helper.name} ` },
      { ...helper, purpose: "same name and file, dropped" },
      { name: "noPurpose", file: "src/a.ts" },
      { name: "blankFile", file: " ", purpose: "p" },
      { name: 7, file: "src/a.ts", purpose: "p" },
      null,
      { name: "longPurpose", file: "src/a.ts", purpose: "z".repeat(200) },
      ...Array.from({ length: 10 }, (_, i) => ({ name: `h${i}`, file: "src/h.ts", purpose: `helper ${i}` })),
    ]
    const r = one(ok(recordFiles(db, pass("a-produce-shared-value"), { ...result({ value: 7 }), notes, symbols })))
    assert.deepEqual([r.completed, r.notes_added, r.symbols_added], [true, 5, 10])

    const stored = readNotes(db)
    assert.ok(stored.every((n) => n.by === "a-produce-shared-value"))
    assert.deepEqual(stored.map((n) => n.topic).sort(), ["conventions", "conventions", "gotcha", "setup", "testing"])
    assert.ok(stored.some((n) => n.topic === "setup" && n.text === setup.text), "trimmed, and the in-file duplicate dropped")
    assert.ok(stored.some((n) => n.topic === "gotcha" && n.text === long.slice(0, 300)), "cut to 300 chars")
    assert.ok(!stored.some((n) => n.text.startsWith("c3")), "the first 5 only")

    const defined = readSymbols(db)
    assert.deepEqual(defined.map((s) => s.name), ["longPurpose", "double", "h0", "h1", "h2", "h3", "h4", "h5", "h6", "h7"])
    assert.deepEqual(defined[1], { ...helper, by: "a-produce-shared-value" }, "trimmed; the first of a duplicate name and file wins")
    assert.equal(defined[0].purpose, "z".repeat(160), "purpose cut to 160 chars")

    claim(db)
    const again = landNoted(db, "b-consume-doubled", { doubled: 14 }, [setup, { topic: "testing", text: "t2" }])
    assert.equal(again.notes_added, 1, "a note already stored is skipped")
    assert.deepEqual(readNotes(db, ["testing"]).map((n) => [n.by, n.text]).sort(), [["a-produce-shared-value", "t1"], ["b-consume-doubled", "t2"]])
    assert.deepEqual(checks(db), [])
  })

  test("a result file without notes or symbols still records", () => {
    const db = exampleStore()
    claim(db)
    const r = one(ok(recordFiles(db, pass("a-produce-shared-value"), result({ value: 7 }))))
    assert.deepEqual([r.completed, r.verdict, r.notes_added, r.symbols_added], [true, "pass", 0, 0])
    claim(db)
    const odd = one(record(db, pass("b-consume-doubled"), { ...result({ doubled: 14 }), notes: "setup: run it", symbols: { name: "f", file: "src/f.ts", purpose: "p" } }))
    assert.deepEqual([odd.completed, odd.notes_added, odd.symbols_added], [true, 0, 0], "non-list notes and symbols are ignored")
    assert.deepEqual([readNotes(db), readSymbols(db)], [[], []])
  })

  test("a pass missing outputs is recorded as a failed review naming them", () => {
    const db = exampleStore()
    claim(db)
    const r = one(land(db, "a-produce-shared-value", { wrong: 1 }))
    assert.equal(r.verdict, "fail")
    assert.equal(r.completed, false)
    assert.deepEqual(r.missing_outputs, ["value"])
    assert.deepEqual(node(db, "a-produce-shared-value").reviews[0].failed_criteria, ["missing output value: value"])
    const bare = one(record(db, pass("a-produce-shared-value")))
    assert.deepEqual([bare.verdict, bare.attempt, bare.missing_outputs], ["fail", 2, ["value"]], "a pass bound to result={}")
    assert.equal(states(db)["a-produce-shared-value"], "in_progress")
  })

  test("record ignores nodes that are not in progress", () => {
    const db = exampleStore()
    assert.deepEqual(land(db, "a-produce-shared-value", { value: 7 }), [])
    assert.deepEqual(land(db, "ghost", {}), [])
    assert.equal(states(db)["a-produce-shared-value"], "frontier")
    assert.deepEqual(node(db, "a-produce-shared-value").reviews, [])
    claim(db)
    assert.deepEqual(record(db, { slug: "a-produce-shared-value", verdict: "maybe", failed_criteria: [] }), [])
    land(db, "a-produce-shared-value", { value: 7 })
    assert.deepEqual(land(db, "a-produce-shared-value", { value: 8 }), [], "a completed node is not recorded again")
    assert.equal(node(db, "a-produce-shared-value").outputs[0].value, 7)
  })

  test("a nested output value fails the call atomically and leaves the node in progress", () => {
    const db = exampleStore()
    claim(db)
    land(db, "a-produce-shared-value", { value: 7 })
    claim(db)
    const r = recordFiles(db, pass("c-consume-squared"), result({ squared: { nested: 49 } }), { checklist: ["[pass] x"] })
    assert.notEqual(r.status, 0)
    assert.match(r.stderr + r.stdout, /InvalidPropertyType/)
    assert.equal(states(db)["c-consume-squared"], "in_progress")
    assert.deepEqual(node(db, "c-consume-squared").reviews, [], "not even the Review was written")
  })

  test("record names a router's unselected branches, not a join reading another output", () => {
    const db = load(router)
    assert.deepEqual(checks(db), [])
    claim(db)
    const r = one(land(db, "pick", { choice: "x-branch", budget: 3 }))
    assert.equal(r.completed, true)
    assert.deepEqual(r.unselected, ["y-branch"])
    rows(db, script("set-status.cypher"), { slugs: r.unselected, status: "cancelled" })
    assert.deepEqual(claim(db).map((n) => n.slug), ["join", "x-branch"])
    assert.deepEqual(one(land(db, "x-branch", { out: 1 })).unselected, [], "only decision nodes route")
  })

  test("check-result flags what record would downgrade, reject or ignore", () => {
    const db = exampleStore()
    const clean = result({ value: 7 })
    assert.deepEqual(checkResult(db, "a-produce-shared-value", clean), {
      slug: "a-produce-shared-value", missing_outputs: [], invalid_outputs: [], unknown_outputs: [], has_times: true,
    })
    assert.deepEqual(checkResult(db, "a-produce-shared-value", {}), {
      slug: "a-produce-shared-value", missing_outputs: ["value"], invalid_outputs: [], unknown_outputs: [], has_times: false,
    })
    const nested = checkResult(db, "a-produce-shared-value", { outputs: { value: { n: 7 } }, started_at: times.started_at })
    assert.deepEqual([nested.missing_outputs, nested.invalid_outputs, nested.has_times], [[], ["value"], false])
    assert.deepEqual(checkResult(db, "a-produce-shared-value", result({ value: [1, "two"] })).invalid_outputs, ["value"])
    assert.deepEqual(checkResult(db, "a-produce-shared-value", result({ value: 7, valeu: 7 })).unknown_outputs, ["valeu"])

    claim(db)
    const r = one(ok(recordFiles(db, pass("a-produce-shared-value"), clean)))
    assert.equal(r.completed, true, "a self-checked file is not downgraded")
  })

  test("progress summarises each wave; the graph is done when nothing is open", () => {
    const db = exampleStore()
    claim(db)
    land(db, "a-produce-shared-value", { value: 7 })
    assert.deepEqual(
      rows(db, script("progress.cypher")).map((w) => [w.wave, w.total, w.completed, w.frontier, w.blocked, w.open]),
      [
        [0, 1, 1, 0, 0, []],
        [1, 2, 0, 2, 0, ["b-consume-doubled", "c-consume-squared"]],
        [2, 1, 0, 0, 1, ["d-join-and-sum"]],
      ],
    )
    claim(db)
    land(db, "b-consume-doubled", { doubled: 14 })
    land(db, "c-consume-squared", { squared: 49 })
    claim(db)
    land(db, "d-join-and-sum", { sum: 63 })
    assert.ok(rows(db, script("progress.cypher")).every((w) => w.open.length === 0))
  })

  test("attention lists only what needs a decision", () => {
    const db = exampleStore()
    assert.deepEqual(rows(db, script("attention.cypher")), [])
    claim(db)
    assert.deepEqual(rows(db, script("attention.cypher")), [
      { slug: "a-produce-shared-value", reason: "in_progress", detail: [] },
    ])
    record(db, fail("a-produce-shared-value", "output.value is a single integer"))
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
    land(db, "a-produce-shared-value", { value: 7 })
    claim(db)
    land(db, "b-consume-doubled", { doubled: 14 })
    assert.deepEqual(rows(db, script("set-status.cypher"), { slugs: ["c-consume-squared"], status: "cancelled" }), [
      { slug: "c-consume-squared", status: "cancelled" },
    ])
    assert.deepEqual(claim(db).map((n) => n.slug), ["d-join-and-sum"])
    assert.deepEqual(rows(db, script("set-status.cypher"), { slugs: ["d-join-and-sum"], status: "completed" }), [])
  })

  test("the engine rejects writes that break the schema", () => {
    const db = exampleStore()
    const props = "slug: 'x-new', title: 'x', type: 'code', acceptance: ['a'], failure_policy: 'retry', model_tier: 'cheap'"
    const rejected = [
      `CREATE (:GbuildNode:Code {slug: 'b-consume-doubled', title: 'dup', type: 'code', acceptance: ['a'], failure_policy: 'retry', model_tier: 'cheap', status: 'pending'})`,
      `CREATE (:GbuildNode:Code {${props}})`,
      `CREATE (:GbuildNode:Code {${props}, status: 'pending', acceptance: 'not a list'})`,
      `CREATE (:Acceptance {id: 'a-1', text: 'dup id'})`,
      `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:REVIEWED]->(:Review {attempt: 'one', verdict: 'pass', at: 'x'})`,
      `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:REVIEWED]->(:Review {attempt: 1, verdict: 'pass', at: 'x', checklist: '[pass] x'})`,
      `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:REVIEWED]->(:Review {attempt: 1, verdict: 'pass', at: 'x', checklist: [1]})`,
      `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:WROTE]->(:Note {topic: 'setup', text: 'x', at: 'x'})`,
      `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:WROTE]->(:Note {topic: 'setup', text: 7, by_node: 'b-consume-doubled', at: 'x'})`,
      `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:DEFINES]->(:Symbol {name: 'f', file: 'src/f.ts', by_node: 'b-consume-doubled', at: 'x'})`,
      `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:DEFINES]->(:Symbol {name: 'f', file: ['src/f.ts'], purpose: 'p', by_node: 'b-consume-doubled', at: 'x'})`,
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
    ["bad-note", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:WROTE]->(:Note {topic: 'misc', text: 'x', by_node: n.slug, at: 'x'})`],
    ["note-owner", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:WROTE]->(:Note {topic: 'setup', text: 'x', by_node: 'ghost', at: 'x'})`],
    ["bad-symbol", `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) CREATE (n)-[:DEFINES]->(:Symbol {name: ' ', file: 'src/f.ts', purpose: 'p', by_node: n.slug, at: 'x'})`],
    ["symbol-owner", `MATCH (b:GbuildNode {slug: 'b-consume-doubled'}), (c:GbuildNode {slug: 'c-consume-squared'}) CREATE (b)-[:DEFINES]->(s:Symbol {name: 'f', file: 'src/f.ts', purpose: 'p', by_node: b.slug, at: 'x'}) CREATE (c)-[:DEFINES]->(s)`],
  ]
  for (const [check, cypher] of violations) {
    test(`validate flags ${check}`, () => {
      const db = exampleStore()
      const r = run(db, cypher)
      assert.equal(r.status, 0, `setup failed: ${r.stderr}`)
      assert.ok(checks(db).includes(check), `expected ${check} in ${JSON.stringify(checks(db))}`)
    })
  }

  test("validate reserves the slugs tree, db and inbox, and flags ownerless or misattached notes and symbols", () => {
    for (const slug of ["tree", "db", "inbox"]) {
      const db = exampleStore()
      ok(run(db, `MATCH (n:GbuildNode {slug: 'b-consume-doubled'}) SET n.slug = '${slug}'`))
      assert.ok(checks(db).includes("bad-slug"), `${slug} is reserved`)
    }
    const db = exampleStore()
    ok(run(db, `CREATE (:Note {topic: 'setup', text: 'x', by_node: 'b-consume-doubled', at: 'x'})`))
    ok(run(db, `CREATE (:Symbol {name: 'f', file: 'src/f.ts', purpose: 'p', by_node: 'b-consume-doubled', at: 'x'})`))
    ok(run(db, `MATCH (f:Feature) CREATE (f)-[:WROTE]->(:Note {topic: 'gotcha', text: 'y', by_node: 'b-consume-doubled', at: 'x'})`))
    assert.deepEqual([...new Set(checks(db))], ["bad-edge", "note-owner", "symbol-owner"])
  })

  test("a store holding valid notes and symbols validates clean", () => {
    const db = exampleStore()
    claim(db)
    landNoted(db, "a-produce-shared-value", { value: 7 },
      [{ topic: "setup", text: "deps: `ln -s <FT>/node_modules node_modules`" }, { topic: "gotcha", text: "the value is an integer" }],
      [{ name: "double", file: "src/double.ts", purpose: "doubles a number" }])
    claim(db)
    landNoted(db, "b-consume-doubled", { doubled: 14 }, [{ topic: "conventions", text: "one module per node" }],
      [{ name: "square", file: "src/square.ts", purpose: "squares a number" }])
    landNoted(db, "c-consume-squared", { squared: 49 }, [{ topic: "testing", text: "`npm test` runs everything" }])
    assert.equal(rows(db, "MATCH (n:Note) RETURN count(n) AS n")[0].n, 4)
    assert.equal(rows(db, "MATCH (s:Symbol) RETURN count(s) AS n")[0].n, 2)
    assert.deepEqual(rows(db, script("validate.cypher"), {}, ["--read-only"]), [])
  })

  test("notes and symbols read scripts run read-only: topic filter, newest first, capped", () => {
    const db = exampleStore()
    assert.deepEqual([readNotes(db), readSymbols(db)], [[], []])
    claim(db)
    landNoted(db, "a-produce-shared-value", { value: 7 },
      [{ topic: "setup", text: "old setup" }, { topic: "gotcha", text: "a gotcha" }],
      [{ name: "zeta", file: "src/b.ts", purpose: "z" }, { name: "alpha", file: "src/b.ts", purpose: "a" }, { name: "omega", file: "src/a.ts", purpose: "o" }])
    const flood = `MATCH (a:GbuildNode {slug: 'a-produce-shared-value'})
UNWIND range(10, 34) AS i
CREATE (a)-[:WROTE]->(:Note {topic: 'setup', text: 'setup step ' + toString(i), by_node: a.slug, at: '2099-01-01T00:00:' + toString(i) + 'Z'})`
    ok(run(db, flood))

    assert.deepEqual(readNotes(db, ["gotcha"]), [{ topic: "gotcha", text: "a gotcha", by: "a-produce-shared-value" }])
    const setup = readNotes(db, ["setup"])
    assert.equal(setup.length, 20)
    assert.deepEqual(setup.slice(0, 2).map((n) => n.text), ["setup step 34", "setup step 33"])
    assert.ok(!setup.some((n) => n.text === "old setup"), "the oldest fall past the cap")
    assert.deepEqual(Object.keys(setup[0]).sort(), ["by", "text", "topic"])

    assert.deepEqual(readSymbols(db), [
      { name: "omega", file: "src/a.ts", purpose: "o", by: "a-produce-shared-value" },
      { name: "alpha", file: "src/b.ts", purpose: "a", by: "a-produce-shared-value" },
      { name: "zeta", file: "src/b.ts", purpose: "z", by: "a-produce-shared-value" },
    ])
    for (const name of ["notes.cypher", "symbols.cypher"]) assert.doesNotMatch(script(name), /\b(CREATE|MERGE|SET|DELETE|REMOVE)\b/)
  })

  test("a failing statement inside .begin/.commit leaves the store untouched", () => {
    const db = fresh()
    const broken = example.replace("CREATE (d)-[:SATISFIES]->(a2);", "CREATE (d)-[:SATISFIES]->(a2);\nCREATE (:Acceptance {id: 'a-1', text: 'dup'});")
    assert.notEqual(run(db, broken).status, 0)
    assert.deepEqual(rows(db, "MATCH (n) RETURN count(n) AS n"), [{ n: 0 }])
  })

  test("token budget: a 40-node dataflow run costs about two calls per node and reads only routing columns", () => {
    const waves = 8
    const width = 5
    const nodes = waves * width
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
    const dispatch = () => {
      const claimed = call("dispatch.cypher")
      for (const n of claimed) assert.deepEqual(Object.keys(n).sort(), routing)
      return claimed
    }
    const checklist = [
      "[pass] the module exports the function with the documented signature",
      "[pass] unit tests cover the empty, single and many-item cases and pass",
      "[pass] outputs: result is a <list of changed file paths>",
      "[pass] duplication: nothing reusable",
    ]

    const queue = dispatch()
    let recorded = 0
    while (queue.length > 0) {
      const n = queue.shift()!
      const r = one(call("record.cypher", { verdict: pass(n.slug), result: result({ result: [`src/${n.slug}.ts`] }), review: { checklist } }))
      assert.equal(r.completed, true)
      recorded++
      queue.push(...dispatch())
    }
    const done = call("progress.cypher")

    assert.equal(recorded, nodes)
    assert.ok(done.every((w) => w.open.length === 0), "the run finished")
    assert.equal(done.length, waves)
    assert.ok(calls <= 2 * nodes + 2, `${calls} calls: one record and one dispatch per node, the first dispatch, one progress`)
    assert.ok(largest < 4_000, `largest single read was ${largest} bytes`)
    assert.ok(bytes < 30_000, `whole run read ${bytes} bytes`)
  })
})
