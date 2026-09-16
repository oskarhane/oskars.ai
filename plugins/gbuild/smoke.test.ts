// Smoke test for the OpenCode plugin entry: registration counts, Claude→OpenCode
// content translation, and command→session.prompt forwarding. Run via repo-root
// `npm test` (node --import tsx --test).
import assert from "node:assert"
import test from "node:test"
import plugin from "./index.js"

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

test("registers one skill and one command per gbuild phase", () => {
  assert.deepEqual(
    skills.map((s) => s.id),
    ["gbuild-plan", "gbuild-run", "gbuild-status", "gbuild-review", "gbuild-pr"],
  )
  assert.deepEqual(
    commands.map((c) => c.name),
    ["gbuild-plan", "gbuild-run", "gbuild-status", "gbuild-review", "gbuild-pr"],
  )
})

test("skill content is translated for OpenCode", () => {
  const plan = skills.find((s) => s.id === "gbuild-plan")
  assert.ok(plan.description.length > 20, "description extracted from frontmatter")
  assert.ok(!plan.content.startsWith("---"), "frontmatter stripped")
  assert.ok(!plan.content.includes("${CLAUDE_PLUGIN_ROOT}"), "no untranslated CLAUDE_PLUGIN_ROOT")
  assert.ok(!/\/gbuild:(plan|run|status|review|pr)\b/.test(plan.content), "no untranslated /gbuild: refs")
  assert.ok(plan.content.includes("/plugins/gbuild/scripts/validate_format.py"), "plugin root substituted")
  assert.ok(plan.content.includes("## Mode"), "body preserved")
  assert.ok(plan.content.includes("## OpenCode runtime notes"), "runtime notes appended")
  assert.ok(plan.path.endsWith("plugins/gbuild/skills/plan/SKILL.md"), "path points at real file")
  assert.equal(plan.location, plan.path, "location and path both sent (server/SDK schema rename)")
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
