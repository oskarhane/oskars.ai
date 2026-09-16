# oskars.ai

Claude Code plugin marketplace by Oskar Hane. Some plugins also target OpenCode — noted per plugin.

## Plugins

| Plugin | Description | OpenCode |
|--------|-------------|----------|
| [autoresearch](./plugins/autoresearch/) | Autonomous experiment loop: try ideas, keep what works, discard what doesn't | |
| [coding-skills](./plugins/coding-skills/) | Language-specific coding skills (TypeScript security, more to come) | |
| [product-skills](./plugins/product-skills/) | Product management skills — discovery, specs, prioritization, and reviews | |
| [gbuild](./plugins/gbuild/) | Graph-native task planning and execution: dependency-graph plans, concurrent fan-out, per-node review | ✓ |

## Install

Add the marketplace, then install any plugin:

```bash
claude plugin marketplace add oskarhane/oskars.ai
claude plugin install autoresearch@oskars.ai
```

For plugins marked OpenCode-compatible (gbuild):

```bash
opencode plugin add opencode-gbuild
```
