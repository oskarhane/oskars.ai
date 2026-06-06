# product-skills — Claude Code Plugin

Product management skills: discovery, specs, prioritization, and product reviews. Designed to grow — more product skills land here over time.

## Install

From the marketplace:

```bash
claude plugin marketplace add oskarhane/oskars.ai
claude plugin install product-skills@oskars.ai
```

For local development:

```bash
claude --plugin-dir ./plugins/product-skills
```

## Skills

| Skill | Description |
|-------|-------------|
| [problem-first](./skills/problem-first/) | Inverts a proposed solution back into the problem underneath it — decompress a handed-down roadmap, or triage your own idea backlog by evidence |

## Usage

Invoke a skill directly or let Claude pick it up from context:

```
/product-skills:problem-first we need to build a new notification system
```

Or: "what problem does this actually solve?", "decompose this feature", "triage my ideas".
