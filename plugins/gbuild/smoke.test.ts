// Smoke test for the OpenCode plugin entry: registration counts, Claude→OpenCode
// content translation, and command→session.prompt forwarding. Run via repo-root
// `npm test` (node --import tsx --test).
import assert from "node:assert"
import { dirname, join } from "node:path"
import test from "node:test"
import { fileURLToPath } from "node:url"
import plugin from "./index.js"

const root = dirname(fileURLToPath(import.meta.url))

const skills: any[] = []
const commands: any[] = []
const prompted: any[] = []

const ctx = {
  skill: {
    transform: async (cb: (editor: any) => void) => {
      cb({ add: (s: any) => skills.push(s) })
      return { dispose: async () => {} }
    },
  },
  command: {
    transform: async (cb: (editor: any) => void) => {
      cb({ add: (c: any) => commands.push(c) })
      return { dispose: async () => {} }
    },
  },
  session: {
    prompt: async (input: any) => prompted.push(input),
  },
}

await (plugin.setup as any)(ctx)

// Same alternation index.ts derives from SLUGS; hoisted so the plan, design and
// cleanup content tests share one source of truth.
const UNTRANSLATED_REF = /\/gbuild:(design|plan|run|status|review|pr|cleanup)\b/

test("registers one skill and one command per gbuild phase", () => {
  assert.deepEqual(
    skills.map((s) => s.id),
    ["gbuild-design", "gbuild-plan", "gbuild-run", "gbuild-status", "gbuild-review", "gbuild-pr", "gbuild-cleanup"],
  )
  assert.deepEqual(
    commands.map((c) => c.name),
    ["gbuild-design", "gbuild-plan", "gbuild-run", "gbuild-status", "gbuild-review", "gbuild-pr", "gbuild-cleanup"],
  )
})

test("skill content is translated for OpenCode", () => {
  const plan = skills.find((s) => s.id === "gbuild-plan")
  assert.ok(plan.description.length > 20, "description extracted from frontmatter")
  assert.ok(!plan.content.startsWith("---"), "frontmatter stripped")
  assert.ok(!plan.content.includes("${CLAUDE_PLUGIN_ROOT}"), "no untranslated CLAUDE_PLUGIN_ROOT")
  assert.ok(!UNTRANSLATED_REF.test(plan.content), "no untranslated /gbuild: refs")
  assert.ok(plan.content.includes("/plugins/gbuild/cypher/validate.cypher"), "plugin root substituted")
  assert.ok(plan.content.includes("## Mode"), "body preserved")
  assert.ok(plan.content.includes("## OpenCode runtime notes"), "runtime notes appended")
  assert.ok(plan.path.endsWith("plugins/gbuild/skills/plan/SKILL.md"), "path points at real file")
  assert.equal(plan.location, plan.path, "location and path both sent (server/SDK schema rename)")
})

test("design skill registers with its placement and is translated", () => {
  const design = skills.find((s) => s.id === "gbuild-design")
  assert.ok(
    design.description.includes("design step before /gbuild-plan"),
    "frontmatter names the design step before plan",
  )
  assert.ok(!design.content.startsWith("---"), "frontmatter stripped")
  assert.ok(!design.content.includes("${CLAUDE_PLUGIN_ROOT}"), "no untranslated CLAUDE_PLUGIN_ROOT")
  assert.ok(!UNTRANSLATED_REF.test(design.content), "no untranslated /gbuild: refs")
  assert.ok(design.content.includes("/plugins/gbuild/skills/plan/SKILL.md"), "plugin root substituted")
  assert.ok(design.content.includes("## Mode"), "body preserved")
  assert.ok(design.content.includes("## OpenCode runtime notes"), "runtime notes appended")
  assert.ok(design.content.includes("## Rules"), "rules section present")
  assert.ok(design.path.endsWith("plugins/gbuild/skills/design/SKILL.md"), "path points at real file")
})

test("cleanup skill registers with its local-only contract and is translated", () => {
  const cleanup = skills.find((s) => s.id === "gbuild-cleanup")
  assert.ok(
    cleanup.description.includes("entire local footprint"),
    "frontmatter names the entire local footprint",
  )
  assert.ok(!cleanup.content.startsWith("---"), "frontmatter stripped")
  assert.ok(!cleanup.content.includes("${CLAUDE_PLUGIN_ROOT}"), "no untranslated CLAUDE_PLUGIN_ROOT")
  assert.ok(!UNTRANSLATED_REF.test(cleanup.content), "no untranslated /gbuild: refs")
  assert.ok(cleanup.content.includes("/plugins/gbuild/cypher/progress.cypher"), "plugin root substituted")
  assert.ok(cleanup.content.includes("never touches the remote"), "local-only contract stated")
  assert.ok(cleanup.content.includes("never infer it"), "slug is required, never inferred")
  assert.ok(cleanup.content.includes("## Step 4: Delete"), "delete step present")
  assert.ok(cleanup.content.includes("## OpenCode runtime notes"), "runtime notes appended")
  assert.ok(cleanup.path.endsWith("plugins/gbuild/skills/cleanup/SKILL.md"), "path points at real file")
})

test("run skill points subagents at agent files instead of inlining them", () => {
  const run = skills.find((s) => s.id === "gbuild-run")
  for (const agent of ["gbuild-implementer", "gbuild-reviewer", "gbuild-auditor"]) {
    const path = join(root, "agents", `${agent}.md`)
    assert.ok(run.content.includes(path), `absolute path of ${agent}.md referenced`)
  }
  assert.ok(!run.content.includes("## REVIEW OBJECTIVE"), "reviewer agent text not inlined")
  assert.ok(!run.content.includes("full text of"), "no instruction to paste agent files")
  assert.ok(run.content.includes("as `Read <path> and follow it.` — the path appears once"), "Agent file field becomes the Read prefix")
})

test("runtime notes agree with the review skill on what the auditor gets", () => {
  const review = skills.find((s) => s.id === "gbuild-review")
  const auditor = join(root, "agents", "gbuild-auditor.md")
  assert.ok(review.content.includes(auditor), "absolute path of gbuild-auditor.md referenced")
  assert.ok(review.content.includes(`Read ${auditor} and follow it.`), "auditor prompt starts with the Read prefix")
  for (const skill of skills) {
    assert.ok(!skill.content.includes("only the placeholders"), `${skill.id}: no placeholder-only rule`)
  }
})

test("commands forward to session.prompt with the skill id and arguments", async () => {
  const plan = commands.find((c) => c.name === "gbuild-plan")
  await plan.execute({ sessionID: "ses_test", prompt: { text: "add oauth login" }, delivery: "steer" })
  assert.equal(prompted[0].sessionID, "ses_test")
  assert.equal(prompted[0].delivery, "steer")
  assert.ok(prompted[0].text.includes('"gbuild-plan"'))
  assert.ok(prompted[0].text.includes("add oauth login"))

  const status = commands.find((c) => c.name === "gbuild-status")
  await status.execute({ sessionID: "ses_test", prompt: { text: "" }, delivery: "queue" })
  assert.ok(prompted[1].text.includes("no arguments"))
})
