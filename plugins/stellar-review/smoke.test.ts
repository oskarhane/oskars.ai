// Smoke test for the OpenCode plugin entry: skill + command registration,
// Claude→OpenCode content translation, and command→session.prompt forwarding.
// Run via repo-root `npm test` (node --import tsx --test).
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

test("registers the stellar-review skill and /stellar-review command", () => {
  assert.equal(skills.length, 1)
  assert.equal(commands.length, 1)
  const skill = skills[0]
  assert.equal(skill.id, "stellar-review")
  assert.equal(skill.name, "stellar-review")
  assert.equal(skill.path, join(root, "skills", "stellar-review", "SKILL.md"))
  assert.equal(skill.location, skill.path)
  assert.match(skill.description, /maintainability review/i)
  const command = commands[0]
  assert.equal(command.name, "stellar-review")
  assert.equal(command.description, skill.description)
})

test("translates the skill body for OpenCode and appends the runtime notes", () => {
  const content = skills[0].content as string
  // The SKILL.md body is fully translated: the one-command local round
  // resolves to this checkout's prep script.
  assert.ok(content.includes(`${root}/scripts/stellar-prep.sh local`))
  assert.ok(content.includes(`${root}/skills/stellar-review/tools`))
  // No untranslated plugin-root token survives above the runtime notes;
  // the notes themselves quote the token (they explain the mapping), so
  // the split is the assertion.
  const [body, notes] = content.split("## OpenCode runtime notes")
  assert.ok(notes !== undefined, "runtime notes must be appended")
  assert.ok(!body.includes("${CLAUDE_PLUGIN_ROOT}"))
  // The notes carry the OpenCode dispatch mapping: general subagents read
  // the plugin's agent files, never registered agents.
  assert.match(notes, /general.*subagent/s)
  assert.ok(notes.includes(join(root, "agents", "stellar-<pass>.md")))
  // The frontmatter never leaks into the registered content.
  assert.ok(!content.startsWith("---"))
  assert.ok(!content.includes("disable-model-invocation"))
})

test("the command forwards to a skill-loading prompt", async () => {
  await commands[0].execute({
    sessionID: "ses_test",
    prompt: { text: "  --quick 123  " },
    delivery: "steer",
  })
  assert.equal(prompted.length, 1)
  const text = prompted[0].text
  assert.ok(text.includes("invoked /stellar-review with these arguments"))
  assert.ok(text.includes("--quick 123"))
  assert.ok(text.includes('Load the skill with id "stellar-review"'))
})
