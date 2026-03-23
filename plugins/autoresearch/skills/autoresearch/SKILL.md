---
name: autoresearch
description: Set up and run an autonomous experiment loop for any optimization target. Gathers what to optimize, then starts the loop immediately. Use when asked to "run autoresearch", "optimize X in a loop", "set up autoresearch for X", or "start experiments".
---

# Autoresearch

Autonomous experiment loop: try ideas, keep what works, discard what doesn't, never stop.

## Research Directory

All session files live in `.research/<dir>/` where `<dir>` matches the branch suffix. For branch `autoresearch/<goal>-<date>`, the directory is `.research/<goal>-<date>/`.

## How It Works

You use your built-in tools (Bash, Read, Write, git) to run experiments, track state, and manage code changes. There are no special tools — you do everything yourself.

- **Run experiments** — `Bash` to execute `.research/<dir>/autoresearch.sh`, capture output, parse METRIC lines.
- **Track state** — `Write`/`Read` to append results to `.research/<dir>/autoresearch.jsonl`.
- **Keep results** — `Bash` to `git add -A && git commit`.
- **Discard results** — `Bash` to revert code changes while preserving `.research/` directory.
- **Update docs** — `Write`/`Edit` to maintain `.research/<dir>/autoresearch.md`.

## Setup

1. Ask (or infer): **Goal**, **Command**, **Metric** (+ direction), **Files in scope**, **Constraints**.
2. `git checkout -b autoresearch/<goal>-<date>` then derive: `DIR=.research/<goal>-<date>; mkdir -p $DIR`
3. Read the source files. Understand the workload deeply before writing anything.
4. Write `$DIR/autoresearch.md` and `$DIR/autoresearch.sh` (see below). Commit both.
5. Run baseline → log result → start looping immediately.

### `autoresearch.md`

This is the heart of the session. A fresh agent with no context should be able to read this file and run the loop effectively. Invest time making it excellent.

```markdown
# Autoresearch: <goal>

## Objective
<Specific description of what we're optimizing and the workload.>

## Metrics
- **Primary**: <name> (<unit>, lower/higher is better)
- **Secondary**: <name>, <name>, ...

## How to Run
`.research/<dir>/autoresearch.sh` — outputs `METRIC name=number` lines.

## Files in Scope
<Every file the agent may modify, with a brief note on what it does.>

## Off Limits
<What must NOT be touched.>

## Constraints
<Hard rules: tests must pass, no new deps, etc.>

## What's Been Tried
<Update this section as experiments accumulate. Note key wins, dead ends,
and architectural insights so the agent doesn't repeat failed approaches.>
```

Update `.research/<dir>/autoresearch.md` periodically — especially the "What's Been Tried" section — so resuming agents have full context.

### `autoresearch.sh`

Lives in `.research/<dir>/autoresearch.sh`. Bash script (`set -euo pipefail`) that: pre-checks fast (syntax errors in <1s), runs the benchmark, outputs `METRIC name=value` lines to stdout. Keep the script fast — every second is multiplied by hundreds of runs. Update it during the loop as needed.

**For fast, noisy benchmarks** (< 5s), run the workload multiple times inside the script and report the median. This produces stable data points and makes the confidence score reliable from the start. Slow workloads (ML training, large builds) don't need this — single runs are fine.

### `autoresearch.checks.sh` (optional)

Lives in `.research/<dir>/autoresearch.checks.sh`. Bash script (`set -euo pipefail`) for backpressure/correctness checks: tests, types, lint, etc. **Only create this file when the user's constraints require correctness validation** (e.g., "tests must pass", "types must check").

When this file exists:
- Run it automatically after every **passing** benchmark.
- If checks fail, log the result as `checks_failed` and revert.
- Its execution time does **NOT** affect the primary metric.
- You cannot `keep` a result when checks have failed.

**Keep output minimal.** Suppress verbose progress/success output and let only errors through.

```bash
#!/bin/bash
set -euo pipefail
# Example: run tests and typecheck — suppress success output, only show errors
pnpm test --run --reporter=dot 2>&1 | tail -50
pnpm typecheck 2>&1 | grep -i error || true
```

## Parsing METRIC Lines

After running `.research/<dir>/autoresearch.sh`, parse stdout for lines matching:

```
METRIC <name>=<number>
```

Regex: `^METRIC\s+(\S+)=([0-9]*\.?[0-9]+)\s*$`

The primary metric matches the metric name from setup. All other METRIC lines are secondary metrics. If no METRIC lines are found, manually extract values from the output.

## Confidence Score

After 3+ experiments, compute a confidence score to distinguish real improvements from benchmark noise.

**Algorithm (MAD-based):**
1. Collect all primary metric values from the current session (excluding crashes where metric=0).
2. If fewer than 3 values, confidence = null (insufficient data).
3. Compute the median of all values.
4. Compute deviations: `|value - median|` for each value.
5. Compute MAD (Median Absolute Deviation) = median of deviations.
6. If MAD = 0 (all identical), confidence = null.
7. Find the best kept metric value in the session.
8. `confidence = |best_kept - baseline| / MAD`

**Interpretation:**
- >= 2.0x — improvement is likely real
- 1.0x - 2.0x — above noise but marginal
- < 1.0x — within noise, consider re-running to confirm before keeping

The score is advisory — it never auto-discards.

## State Tracking: `.research/<dir>/autoresearch.jsonl`

Append-only file. Each line is a JSON object. Two types:

**Config header** (written at session start):
```json
{"type":"config","name":"<session name>","metric_name":"<name>","metric_unit":"<unit>","direction":"lower|higher","segment":0,"timestamp":1234567890}
```

**Result** (written after each experiment):
```json
{"type":"result","metric":15200,"metrics":{"compile_us":4200,"render_us":9800},"status":"keep|discard|crash|checks_failed","description":"what was tried","commit":"abc1234","confidence":2.3,"segment":0,"timestamp":1234567890}
```

The `segment` field increments on each config header. Use the current (highest) segment for confidence calculations.

## Git Workflow

### On `keep` (primary metric improved):
```bash
git add -A && git commit -m "autoresearch: <description> (<metric_name>=<value>)"
```

### On `discard`, `crash`, or `checks_failed`:
Revert all code changes but preserve the `.research/` directory:
```bash
# Save research state
git stash push --include-untracked -- .research/ 2>/dev/null || true
git checkout -- .
git clean -fd
git stash pop 2>/dev/null || true
```

Always append the result to `.research/<dir>/autoresearch.jsonl` BEFORE reverting, so the record is preserved.

## Loop Rules

**LOOP FOREVER.** Never ask "should I continue?" — the user expects autonomous work.

- **Primary metric is king.** Improved → `keep`. Worse/equal → `discard`. Secondary metrics rarely affect this.
- **Watch the confidence score.** After 3+ runs, check confidence. >= 2.0x means the improvement is likely real. < 1.0x means it's within noise — consider re-running to confirm before keeping.
- **Simpler is better.** Removing code for equal perf = keep. Ugly complexity for tiny gain = probably discard.
- **Don't thrash.** Repeatedly reverting the same idea? Try something structurally different.
- **Crashes:** fix if trivial, otherwise log and move on. Don't over-invest.
- **Think longer when stuck.** Re-read source files, study the profiling data, reason about what the CPU is actually doing. The best ideas come from deep understanding, not from trying random variations.
- **Resuming:** if `.research/<dir>/autoresearch.md` exists, read it + git log, continue looping.
- **Never keep when checks fail.** If `.research/<dir>/autoresearch.checks.sh` exists and fails, the result MUST be logged as `checks_failed` and reverted.
- **Validate secondary metrics.** Track them for consistency — a huge regression in a secondary metric warrants investigation even if the primary improves.

**NEVER STOP.** The user may be away for hours. Keep going until interrupted.

## Ideas Backlog

When you discover complex but promising optimizations that you won't pursue right now, **append them as bullets to `.research/<dir>/autoresearch.ideas.md`**. Don't let good ideas get lost.

On resume (context limit, crash), check `.research/<dir>/autoresearch.ideas.md` — prune stale/tried entries, experiment with the rest. When all paths are exhausted, delete the file and write a final summary.

## User Messages During Experiments

If the user sends a message while an experiment is running, finish the current run + log cycle first, then incorporate their feedback in the next iteration. Don't abandon a running experiment.

## Resuming

Detect an active session by checking `.research/` for a subdirectory matching the current branch suffix. For branch `autoresearch/foo-2026-03-20`, look for `.research/foo-2026-03-20/`.

If `.research/<dir>/autoresearch.md` exists when you start:
1. Read `.research/<dir>/autoresearch.md` to understand the objective and what's been tried.
2. Read `.research/<dir>/autoresearch.jsonl` to reconstruct state (latest config header, all results in current segment).
3. Check `git log` for recent commits.
4. Check `.research/<dir>/autoresearch.ideas.md` for pending ideas.
5. Continue the loop from where it left off.
