import { readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import type { Plugin } from "@opencode/plugin"

/**
 * gbuild — OpenCode front for the skills in ./skills (shared verbatim with the
 * Claude Code plugin in this directory). At load time each SKILL.md is read,
 * translated for OpenCode (${CLAUDE_PLUGIN_ROOT} → this package's directory,
 * /gbuild:<name> → /gbuild-<name>), and registered as a skill plus a slash
 * command that loads it.
 *
 * The SDK is a dev-only, type-only dependency: the default export is a plain
 * `{ id, setup }` definition, so the plugin has zero runtime dependencies and
 * no version coupling to the SDK. Skill.Info carries both `location` and
 * `path` (same value): the 2.0.1 server schema requires `location`, the
 * 2.0.4 SDK types require `path` — sending both straddles the rename.
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
  backend described in step 2.
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
  readonly path: string
  readonly content: string
}

const load = (slug: Slug): LoadedSkill => {
  const path = join(root, "skills", slug, "SKILL.md")
  const { description, body } = frontmatter(readFileSync(path, "utf8"))
  return {
    slug,
    id: `gbuild-${slug}`,
    description: translate(description),
    path,
    content: translate(body) + OPENCODE_NOTES,
  }
}

const plugin: Plugin.Plugin = {
  id: "gbuild",
  async setup(ctx) {
    const skills = SLUGS.map(load)

    await ctx.skill.transform((editor) => {
      for (const skill of skills) {
        editor.add({
          id: skill.id,
          name: skill.id,
          description: skill.description,
          location: skill.path, // 2.0.1 server schema
          path: skill.path, // 2.0.4 SDK schema
          content: skill.content,
        } as unknown as Parameters<typeof editor.add>[0])
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
}

export default plugin
