# PRD: coding-skills plugin with typescript-security skill

## Overview

Add a new Claude Code plugin `coding-skills` to this marketplace repo, shipping one initial skill `typescript-security` adapted from the user's globally-installed `golang-security` skill (`~/.claude/skills/golang-security/`). The skill provides security guidance, anti-patterns, and tooling recommendations for TypeScript / Node.js code (Express, Next.js, NestJS, plain Node). The plugin is structured so additional per-language coding skills can be added later under the same plugin.

## Goals

- Ship a working `typescript-security` skill in the local marketplace with the same shape and quality bar as the source `golang-security` skill.
- Translate Go-specific idioms (`database/sql`, `exec.Command`, `html/template`, `crypto/rand`, `os.Root`, `gosec`, `govulncheck`, `-race`) into their TypeScript/Node.js equivalents.
- Register the new plugin in `.claude-plugin/marketplace.json` so it installs alongside `autoresearch`.
- Keep the plugin extensible: structure supports adding more coding skills (e.g., `python-security`, `rust-security`, language idioms) later without restructuring.

## Non-Goals

- Translating the source skill's `evals/` benchmark suite (`evals.json`, ~49 KB of Go cases). No evals folder in v1.
- Browser-only / DOM-only security (XSS coverage stays at the level the source skill had — sufficient for full-stack TS, not a frontend-only deep dive).
- Adding additional language skills beyond `typescript-security` in this PR.
- Publishing the plugin to a remote marketplace; install path is local-only via this repo.
- Adapting `samber/cc-skills-golang@...` cross-references to invented TS equivalents. Drop or generalize them.

## Requirements

### Functional Requirements

- REQ-F-001: Create `plugins/coding-skills/.claude-plugin/plugin.json` mirroring the shape of `plugins/autoresearch/.claude-plugin/plugin.json`, with `name: "coding-skills"`, `version: "0.1.0"`, `license: "MIT"`, `keywords: ["review", "typescript", "security"]`, author block matching the repo author.
- REQ-F-002: Create `plugins/coding-skills/README.md` with a short description and a Plugins-style table listing the included skill(s) and their purpose, modeled on the root `README.md`.
- REQ-F-003: Create `plugins/coding-skills/skills/typescript-security/SKILL.md` adapted from `~/.claude/skills/golang-security/SKILL.md`:
  - Frontmatter `name: typescript-security`, `user-invocable: true`, `license: MIT`, `metadata.version: "0.1.0"`, `metadata.author`, a `description` that mirrors the source description but mentions TypeScript / Node.js / common frameworks (Express, Next.js, NestJS) and TS-specific concerns (prototype pollution, async race conditions).
  - `allowed-tools` set to `Read Edit Write Glob Grep Bash(npm:*) Bash(npx:*) Bash(node:*) Bash(git:*) Bash(eslint:*) Bash(snyk:*) Bash(semgrep:*) Agent WebFetch WebSearch AskUserQuestion`.
  - Drop the Go-specific `openclaw.install` block.
  - Keep the source skill's overall structure: Persona, Thinking mode, Modes (Review / Audit / Coding), Security Thinking Model, Severity Levels, Research Before Reporting, Threat Modeling (STRIDE), Quick Reference table, Detailed Categories list (links to refs), Code Review Checklist link, Tooling & Verification, Common Mistakes, Security Anti-Patterns, Cross-References, Additional Resources.
  - Replace all Go code/idioms with TS/Node equivalents per the mapping in "Technical Considerations".
  - Remove `samber/cc-skills-golang@...` cross-refs; replace with a short note that more coding skills are planned in this plugin.
- REQ-F-004: Create `plugins/coding-skills/skills/typescript-security/references/` containing 10 files:
  - `injection.md` — SQL (pg/mysql2/Prisma/Drizzle/Knex parameter binding), command (`child_process.execFile`/`spawn`, `shell: false`, never `exec` with interpolation), template/XSS (JSX auto-escape, `dangerouslySetInnerHTML`, DOMPurify), SSRF (fetch/undici allowlist, block private IPs).
  - `cryptography.md` — `node:crypto` AES-256-GCM, `crypto.randomBytes`/`randomUUID` vs `Math.random`, `crypto.timingSafeEqual`, Argon2id/bcrypt for passwords, key management, TLS config (`minVersion: 'TLSv1.2'`).
  - `filesystem.md` — `path.resolve` + prefix check, `fs.realpath`, reject `..`, safe file permissions, zip slip, symlinks, temp files.
  - `network.md` — TLS, security headers (helmet/manual), CSRF, open redirects, SSRF deeper coverage, timing attacks, session handling.
  - `cookies.md` — `httpOnly`, `secure`, `sameSite`, `__Host-` prefix, signed cookies, Express `res.cookie`/`cookie` lib.
  - `secrets.md` — `process.env`, `.env` with `--env-file` (Node 22+), secret managers (AWS/GCP/Vault), never commit secrets, dotenv-vault, leaked secret scanning.
  - `logging.md` — `pino` redact paths, JSON logging, log injection, PII redaction, never log tokens / cookies / authorization headers.
  - `checklist.md` — review checklist organized by domain (input handling, database, code execution, crypto, web, authn/authz, errors, dependencies, async/concurrency), with severities. Translate Go-specific items (e.g., `gosec`, `crypto/subtle.ConstantTimeCompare`) to TS equivalents.
  - `threat-modeling.md` — STRIDE + DREAD; mostly language-agnostic, lightly adapted (examples use TS), OWASP Top 10 mapping.
  - `architecture.md` — defense in depth, Zero Trust, auth patterns (session/JWT/OAuth/OIDC), rate limiting (`express-rate-limit`, `@upstash/ratelimit`), anti-patterns with TS code examples.
- REQ-F-005: Update `.claude-plugin/marketplace.json` — append a new entry to the `plugins` array: `{ "name": "coding-skills", "source": "./plugins/coding-skills", "description": "Language-specific coding skills (TypeScript security, more to come)." }`. Preserve formatting (2-space indent, trailing newline) matching the existing file.
- REQ-F-006: Update the root `README.md` Plugins table to add a row for `coding-skills` linking to `./plugins/coding-skills/`, with a one-line description.

### Non-Functional Requirements

- REQ-NF-001: All JSON files (`plugin.json`, `marketplace.json`) MUST be valid JSON (parse cleanly with `jq .`).
- REQ-NF-002: SKILL.md frontmatter MUST be valid YAML and include all required keys (`name`, `description`, `user-invocable`, `allowed-tools`).
- REQ-NF-003: No Go-specific terminology should remain in the SKILL.md or references (no `go.mod`, `goroutine`, `gosec`, `govulncheck`, `crypto/rand` as Go package reference, `database/sql`, `exec.Command`, `html/template`, `os.Root`, etc., except possibly as a comparative footnote where useful).
- REQ-NF-004: Reference docs MUST link back to each other and to SKILL.md using relative paths that work from inside the skill directory (matching how the source skill links — `./references/injection.md` from SKILL.md, sibling-relative inside references/).
- REQ-NF-005: No new dependencies in the repo `package.json`. The skill is markdown-only.

## Technical Considerations

### Go → TypeScript/Node idiom mapping

| Source topic | TS/Node replacement |
| --- | --- |
| `database/sql` `?` / `$1` placeholders | `pg` parameterized (`$1`), `mysql2` (`?`), Prisma/Drizzle/Knex parameter binding |
| `exec.Command` with args | `child_process.execFile` / `spawn` with arg array; never `exec` with interpolated strings; explicit `shell: false` |
| `html/template` auto-escape | React JSX auto-escaping, `dangerouslySetInnerHTML` pitfalls, DOMPurify, template literals warning |
| `os.Root` / `filepath.Clean` | `path.resolve` + prefix check, `fs.realpath`, reject `..`, `node:path/posix` for URLs |
| `crypto/rand` vs `math/rand` | `node:crypto.randomBytes` / `randomUUID` vs `Math.random` |
| `crypto/subtle.ConstantTimeCompare` | `crypto.timingSafeEqual` |
| AES-GCM / Argon2id / bcrypt | `node:crypto` AES-256-GCM, `argon2` package, `bcrypt` / `bcryptjs` |
| TLS config | `https.createServer` `tls.SecureContextOptions`, `minVersion: 'TLSv1.2'` |
| Cookie flags | `cookie` lib / Express `res.cookie` with `httpOnly`, `secure`, `sameSite`, `__Host-` |
| Secrets / env | `process.env`, `.env` via `--env-file` (Node 22+) per repo CLAUDE.md, secret managers |
| Race conditions | Swap for prototype pollution, `Object.create(null)`, JSON parse pitfalls, async race on shared module state |
| `gosec` / `govulncheck` | `npm audit`, `npm audit signatures`, `eslint-plugin-security`, `eslint-plugin-no-secrets`, `snyk test`, `osv-scanner`, `semgrep --config p/typescript` |
| `go test -race` / fuzz | `node --test`, `node --experimental-test-coverage`, fast-check property tests, `node:test` mocks |
| SSRF examples | `fetch` / `undici` with URL allowlist; block private IP ranges; disable redirects to internal hosts |
| Log injection / PII | `pino` redact paths, JSON logging, never log tokens / cookies / PII |

### File layout

```
plugins/coding-skills/
├── .claude-plugin/
│   └── plugin.json
├── README.md
└── skills/
    └── typescript-security/
        ├── SKILL.md
        └── references/
            ├── injection.md
            ├── cryptography.md
            ├── filesystem.md
            ├── network.md
            ├── cookies.md
            ├── secrets.md
            ├── logging.md
            ├── checklist.md
            ├── threat-modeling.md
            └── architecture.md
```

### Integration points

- `/Users/oskarhane/Development/oskars.ai/.claude-plugin/marketplace.json` — append new plugin entry.
- `/Users/oskarhane/Development/oskars.ai/README.md` — add row to Plugins table.
- Source skill (read-only reference): `/Users/oskarhane/.claude/skills/golang-security/`.

### Potential challenges

- Reference docs are substantive (3–10 KB each). Writing them all in one pass risks shallow content. Sequence: write SKILL.md first, then references in priority order (injection → crypto → filesystem → network → cookies → secrets → logging → checklist → threat-modeling → architecture).
- Some content (threat-modeling, architecture, checklist) is largely language-agnostic in the source — adapt examples but don't rewrite from scratch.
- Skill metadata description matters for discoverability — preserve the shape of the source description (lists what it covers, when to apply) but reword for TS.

## Acceptance Criteria

- [ ] `plugins/coding-skills/.claude-plugin/plugin.json` exists, parses as JSON, matches the field set used by `plugins/autoresearch/.claude-plugin/plugin.json`, version `0.1.0`, license `MIT`, keywords include `review`, `typescript`, `security`.
- [ ] `plugins/coding-skills/README.md` exists with a Plugins/Skills table listing `typescript-security`.
- [ ] `plugins/coding-skills/skills/typescript-security/SKILL.md` exists with valid YAML frontmatter (`name`, `description`, `user-invocable: true`, `allowed-tools`, `metadata.version`).
- [ ] All 10 reference files exist under `plugins/coding-skills/skills/typescript-security/references/`.
- [ ] `grep -r "exec.Command\|crypto/rand\|database/sql\|html/template\|govulncheck\|gosec\|goroutine\|os.Root" plugins/coding-skills/` returns no matches (no leftover Go idioms).
- [ ] `cat .claude-plugin/marketplace.json | jq .plugins` shows both `autoresearch` and `coding-skills` entries.
- [ ] Root `README.md` lists `coding-skills` in its Plugins table.
- [ ] All `.md` files in the skill render readable markdown (no broken frontmatter, no truncated code fences).
- [ ] Relative links between SKILL.md and references resolve (e.g., `./references/injection.md` from SKILL.md exists).

## Out of Scope

- `evals/` folder and benchmark cases.
- Additional language skills (`python-security`, `rust-security`, etc.).
- Browser-only / frontend-only deep dive beyond what the source skill's depth implies.
- Publishing or remote marketplace registration.
- Automated tests for skill content (no test harness exists for skill markdown).
- Updating CLAUDE.md or AGENTS.md.
- Bumping any other plugin's version.

## Open Questions

None.
