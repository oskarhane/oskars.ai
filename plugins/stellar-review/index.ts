import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import type { Plugin } from "@opencode/plugin"

/**
 * stellar-review — OpenCode front for the stellar-review skill in
 * ./skills/stellar-review (shared verbatim with the Claude Code plugin in
 * this directory). At load time the SKILL.md is read, translated for
 * OpenCode (${CLAUDE_PLUGIN_ROOT} → this package's directory), and
 * registered as a skill plus a /stellar-review slash command that loads it.
 *
 * The SDK is a dev-only, type-only dependency: the default export is a plain
 * `{ id, setup }` definition, so the plugin has zero runtime dependencies and
 * no version coupling to the SDK. Skill.Info carries both `location` and
 * `path` (same value): the 2.0.1 server schema requires `location`, the
 * 2.0.4 SDK types require `path` — sending both straddles the rename.
 */

const root = dirname(fileURLToPath(import.meta.url))

const ID = "stellar-review" as const
const SKILL_PATH = join(root, "skills", "stellar-review", "SKILL.md")

const OPENCODE_NOTES = `

## OpenCode runtime notes

You are running under OpenCode, not Claude Code. Apply these mappings to the
instructions above:

- \`${join(root, "scripts", "stellar-prep.sh")}\` is this plugin's
  stellar-prep.sh (the skill's \`\${CLAUDE_PLUGIN_ROOT}/scripts/stellar-prep.sh\`).
  Runtime dependencies: \`python3\`, \`git\`, \`gh\` and \`jq\` on PATH.
- \`stellar-structure\`, \`stellar-branching\`, \`stellar-boundaries\` and
  \`stellar-comparison\` are not registered agents here — OpenCode plugins
  cannot register agents. When the skill says to dispatch one, dispatch the
  built-in \`general\` subagent instead, one per brief file, in parallel,
  with the per-pass model from the tier guidance / \`STELLAR_MODEL_*\`
  overrides. Prompt per pass:
  > Stellar review round <N>. Read \`${join(root, "agents", "stellar-<pass>.md")}\` and follow it — its \`\${CLAUDE_PLUGIN_ROOT}\` references mean \`${root}\`. Your brief is \`.stellar/briefs/<file>\` — read it fully, then follow your standing instructions (mandate + doctrine + JSON output). Return only your JSON document.

  Never paste the agent file's text into the prompt and never merge two
  briefs into one dispatch; each pass is still a fresh, isolated agent.
  Subagents run in the background and report when they go idle: never end
  your turn while a pass is still in flight — a one-shot run (CI) exits the
  moment your turn ends and loses every in-flight pass. Join each dispatched
  subagent's report before assembling findings.json.
- \`$ARGUMENTS\` refers to the arguments this skill was invoked with in the
  conversation (optionally \`--quick\` and/or a PR number, passed through to
  stellar-prep.sh).
- The pipeline's runtime state lives in \`.stellar/\` at the repository root;
  the reviewed repository should list \`.stellar/\` in its .gitignore.
`

const frontmatter = (raw: string): { description: string; body: string } => {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (!match) return { description: "", body: raw }
  const description = match[1]?.match(/^description:\s*(.+)$/m)?.[1]?.trim() ?? ""
  return { description, body: match[2] ?? "" }
}

const translate = (text: string): string =>
  text.replaceAll("${CLAUDE_PLUGIN_ROOT}", root)

const load = () => {
  const { description, body } = frontmatter(readFileSync(SKILL_PATH, "utf8"))
  return {
    id: ID,
    description: translate(description),
    path: SKILL_PATH,
    content: translate(body) + OPENCODE_NOTES,
  }
}

const plugin: Plugin.Plugin = {
  id: ID,
  async setup(ctx) {
    const skill = load()

    await ctx.skill.transform((editor) => {
      editor.add({
        id: skill.id,
        name: skill.id,
        description: skill.description,
        location: skill.path, // 2.0.1 server schema
        path: skill.path, // 2.0.4 SDK schema
        content: skill.content,
      } as unknown as Parameters<typeof editor.add>[0])
    })

    await ctx.command.transform((editor) => {
      editor.add({
        name: skill.id,
        description: skill.description,
        execute: async ({ sessionID, prompt, delivery }) => {
          const args = prompt.text.trim()
          await ctx.session.prompt({
            sessionID,
            delivery,
            text: [
              `The user invoked /${skill.id}${args ? ` with these arguments:` : ` with no arguments.`}`,
              ...(args ? ["", args, ""] : []),
              `Load the skill with id "${skill.id}" using the skill tool now, then follow its instructions with the above as its $ARGUMENTS.`,
            ].join("\n"),
          })
        },
      })
    })
  },
}

export default plugin
