# autoresearch — Claude Code Plugin

Autonomous experiment loop: try ideas, keep what works, discard what doesn't, never stop.

## Install

From the marketplace:

```bash
claude plugin marketplace add oskarhane/oskars.ai
claude plugin install autoresearch@oskars.ai
```

For local development:

```bash
claude --plugin-dir ./plugins/autoresearch
```

## Usage

```
/autoresearch optimize test suite speed
```

Or just tell Claude: "run autoresearch on X", "optimize X in a loop", "start experiments for X".

To limit the number of experiments, specify an iteration count:

```
/autoresearch optimize test suite speed for 20 iterations
```

Any phrasing works — "for 20 iterations", "20 runs", or just a bare number. When the limit is reached, Claude stops, commits a final summary, and reports the best result. Omitting it defaults to unlimited (loop forever).

Claude will:

1. Ask/infer: goal, command, metric, files in scope, constraints
2. Create a git branch `autoresearch/<goal>-<date>`
3. Create `.research/<goal>-<date>/` and write session doc + benchmark script there
4. Run baseline, then loop forever: try idea → run → measure → keep or discard → repeat

## How It Works

- **Keep**: primary metric improved → `git commit`
- **Discard**: metric regressed or unchanged → `git revert` (experiment record preserved)
- **State**: `.research/<dir>/autoresearch.jsonl` — append-only log of every run
- **Context**: `.research/<dir>/autoresearch.md` — living document so any new session can resume
- **Auto-resume**: stop hook detects active session and blocks context-limit exits

## Making It Domain-Specific

The skill is generic — it works for any optimization target. You make it domain-specific through what you tell Claude:

### Performance Optimization
> "Run autoresearch to optimize the API response time. Primary metric is p99 latency in ms (lower is better). Only touch files in `src/api/`. Tests must pass."

### Bundle Size Reduction
> "Set up autoresearch to minimize the production bundle size. Metric is total KB (lower is better). Don't remove any features. Run `bun build` and measure output size."

### ML Training
> "Start autoresearch to optimize training loss. Metric is val_bpb (lower is better). Only modify the model config and training loop in `train.py`. Each run takes ~2min so single runs are fine."

### Test Speed
> "Optimize test suite execution time with autoresearch. Metric is total seconds (lower is better). Tests must still pass — create autoresearch.checks.sh for that."

### Accuracy / Quality
> "Run autoresearch to maximize accuracy on the eval set. Metric is accuracy_pct (higher is better). Don't change the eval harness, only the prompt template."

### Key Levers

- **Goal**: what you're optimizing — be specific
- **Metric + direction**: what to measure, whether lower or higher is better
- **Files in scope**: what Claude is allowed to modify
- **Constraints**: hard rules (tests pass, no new deps, no feature removal)
- **Checks script**: optional `.research/<dir>/autoresearch.checks.sh` for correctness validation (tests, types, lint) — runs after every passing benchmark, failures auto-revert
- **Ideas file**: Claude maintains `.research/<dir>/autoresearch.ideas.md` with promising directions not yet explored

## Files Created During a Session

All session files live in `.research/<goal>-<date>/`, keeping the repo root clean and supporting multiple concurrent sessions.

| File | Purpose |
|------|---------|
| `.research/<dir>/autoresearch.md` | Session doc: objective, metrics, what's been tried |
| `.research/<dir>/autoresearch.sh` | Benchmark script outputting `METRIC name=value` lines |
| `.research/<dir>/autoresearch.jsonl` | Append-only experiment log (config + results) |
| `.research/<dir>/autoresearch.checks.sh` | Optional correctness checks (tests, types, lint) |
| `.research/<dir>/autoresearch.ideas.md` | Optional backlog of promising ideas |

## Plugin Structure

```
autoresearch/
├── .claude-plugin/
│   └── plugin.json           # Plugin metadata
├── skills/
│   └── autoresearch/
│       └── SKILL.md          # Workflow instructions for Claude
├── hooks/
│   └── hooks.json            # Stop hook config
├── scripts/
│   └── stop-hook.sh          # Auto-resume on context limit
└── README.md
```
