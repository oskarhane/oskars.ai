This is a repository for agent plugins and skills created by Oskar Hane.

## Structure

- `plugins/<name>/` — one directory per plugin, listed in `.claude-plugin/marketplace.json`.
- A plugin directory is a Claude Code plugin (`.claude-plugin/plugin.json`, `skills/`, `agents/`).
- A plugin directory can additionally be an OpenCode V2 plugin by adding a `package.json`
  (npm package, `exports: "./index.ts"`) and an `index.ts` using `Plugin.define` from
  `@opencode-ai/plugin`. Keep the markdown in `skills/`/`agents/` the single source of truth for
  both harnesses; `index.ts` translates paths and references at load time rather than forking
  content. See `plugins/gbuild/` for the reference implementation.
