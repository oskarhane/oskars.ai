import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { Plugin } from "@opencode-ai/plugin"
import type { Skill } from "@opencode-ai/plugin"

/**
 * gbuild — OpenCode front for the skills in ./skills (shared verbatim with the
 * Claude Code plugin in this directory). At load time each SKILL.md is read,
 * translated for OpenCode (${CLAUDE_PLUGIN_ROOT} → this package's directory,
 * /gbuild:<name> → /gbuild-<name>), and registered as a skill plus a slash
 * command that loads it.
 */

const root = dirname(fileURLToPath(import.meta.url))

const SLUGS = ["plan", "run", "status", "review", "pr"] as const
type Slug = (typeof SLUGS)[number]

const OPENCODE_NOTES = `

## OpenCode runtime notes

You are running under OpenCode, not Claude Code. Apply these mappings to the
instructions above:

- \`Agent\`/\`Task\` tool dispatches (including run's per-node fan-out) use the
  \`subagent\` tool. Fan-out stays real: one \`subagent\` call per frontier node,
  all in a single message.
- \`gbuild-reviewer\` and \`gbuild-auditor\` are not registered agents here. When
  the instructions say to spawn one, dispatch the built-in \`general\` subagent
  and start its prompt with the full text of
  \`${join(root, "agents", "gbuild-reviewer.md")}\` (or
  \`${join(root, "agents", "gbuild-auditor.md")}\`, minus the frontmatter) as its
  instructions, followed by everything the instructions say to give it (node
  definition, diff locations, expected verdict format). It is still a fresh,
  isolated agent — never the one that implemented the node.
- \`$ARGUMENTS\` refers to the arguments this skill was invoked with in the
  conversation.
- run's "Workflow tool" backend is Claude-specific; always use the fallback
  backend described in step 3.
`

const frontmatter = (raw: string): { description: string; body: string } => {
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/)
  if (!match) return { description: "", body: raw }
  const description = match[1]?.match(/^description:\s*(.+)$/m)?.[1]?.trim() ?? ""
  return { description, body: match[2] ?? "" }
}

const translate = (text: string): string =>
  text
    .replaceAll("${CLAUDE_PLUGIN_ROOT}", root)
    .replace(/\/gbuild:(plan|run|status|review|pr)\b/g, "/gbuild-$1")

interface LoadedSkill {
  readonly slug: Slug
  readonly id: `gbuild-${Slug}`
  readonly description: string
  readonly location: string
  readonly content: string
}

const load = (slug: Slug): LoadedSkill => {
  const location = join(root, "skills", slug, "SKILL.md")
  const { description, body } = frontmatter(readFileSync(location, "utf8"))
  return {
    slug,
    id: `gbuild-${slug}`,
    description: translate(description),
    location,
    content: translate(body) + OPENCODE_NOTES,
  }
}

export default Plugin.define({
  id: "gbuild",
  async setup(ctx) {
    const skills = SLUGS.map(load)

    await ctx.skill.transform((editor) => {
      for (const skill of skills) {
        editor.add({
          id: skill.id,
          name: skill.id,
          description: skill.description,
          slash: false, // the commands below are the interactive surface
          location: skill.location,
          content: skill.content,
        } as Skill.Info)
      }
    })

    await ctx.command.transform((editor) => {
      for (const skill of skills) {
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
      }
    })
  },
})
