# coding-skills — Claude Code Plugin

Language-specific coding skills: security guidance, anti-patterns, and review checklists. Designed to grow — more language skills land here over time.

## Install

From the marketplace:

```bash
claude plugin marketplace add oskarhane/oskars.ai
claude plugin install coding-skills@oskars.ai
```

For local development:

```bash
claude --plugin-dir ./plugins/coding-skills
```

## Skills

| Skill | Description |
|-------|-------------|
| [typescript-security](./skills/typescript-security/) | Security best practices for TypeScript / Node.js (Express, Next.js, NestJS) — injection, crypto, filesystem, network, cookies, secrets, logging, threat modeling |

## Usage

Invoke a skill directly or let Claude pick it up from context:

```
/typescript-security review src/api/auth.ts
```

Or: "review this TS code for security issues", "audit the auth flow", "find vulnerabilities in this handler".
