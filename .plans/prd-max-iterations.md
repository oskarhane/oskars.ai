# PRD: Max Iterations for Autoresearch

## Overview
Add an optional max iterations limit to the autoresearch plugin so users can cap how many experiments run before the agent stops. Passed naturally via skill invocation (e.g., "autoresearch optimize X for 20 iterations").

## Goals
- Let users cap experiment runs to a known number
- Graceful stop with final commit + summary when limit is hit
- Stop hook should not block exit when max iterations reached

## Non-Goals
- Config file-based max iterations (skill arg only)
- Pause/resume with remaining iteration count across sessions
- Time-based limits

## Requirements

### Functional Requirements
- REQ-F-001: SKILL.md setup section instructs the agent to look for an iteration limit in the user's input (number or phrase like "for 20 iterations"). If not provided, behavior is unchanged (loop forever).
- REQ-F-002: When `maxIterations` is set, the config header in `autoresearch.jsonl` includes a `"maxIterations"` field (number or `null`).
- REQ-F-003: After each experiment, the agent checks the current segment's result count against `maxIterations`. When reached, the agent stops looping.
- REQ-F-004: On reaching the limit, the agent: (1) updates `.research/<dir>/autoresearch.md` "What's Been Tried" section, (2) commits final state with message like `autoresearch: max iterations (N) reached — final summary`, (3) prints a summary of results (best metric, total kept/discarded, confidence), (4) stops.
- REQ-F-005: The stop hook (`stop-hook.sh`) must allow exit when max iterations has been reached. It should check `autoresearch.jsonl` to determine if the configured `maxIterations` has been met by counting results in the current segment.

### Non-Functional Requirements
- REQ-NF-001: No new dependencies — stop hook uses only bash, jq, and standard unix tools already in use.
- REQ-NF-002: Backward compatible — sessions without `maxIterations` behave exactly as before (loop forever).

## Technical Considerations

### Files to modify
1. **`skills/autoresearch/SKILL.md`** — Setup section: extract `maxIterations` from user input. Loop Rules section: add iteration check + stop behavior. Config header schema: add `maxIterations` field. Add "Final Summary" section describing stop behavior.
2. **`scripts/stop-hook.sh`** — Parse `autoresearch.jsonl` to find current segment's `maxIterations` and result count. Allow exit if limit reached.

### Iteration counting
Count only `{"type":"result"}` lines in the current (highest) segment. This matches how confidence is already scoped to segments.

### Stop hook logic
```
1. Find autoresearch.jsonl (existing behavior)
2. Read last config header → extract maxIterations
3. If maxIterations is null/missing → block exit (existing behavior)
4. Count results in current segment
5. If count >= maxIterations → allow exit
6. Otherwise → block exit
```

## Acceptance Criteria
- [ ] `/autoresearch optimize X for 20 iterations` sets maxIterations=20, stops after 20 experiments
- [ ] `/autoresearch optimize X` with no iteration mention loops forever as before
- [ ] Config header in jsonl includes `maxIterations` field
- [ ] On reaching limit: autoresearch.md updated, final commit made, summary printed
- [ ] Stop hook allows exit when max iterations reached
- [ ] Stop hook still blocks exit for unlimited sessions and sessions under the limit

## Out of Scope
- Persisting remaining iterations across context-limit resumes (resume just re-reads jsonl and counts)
- Config file support for maxIterations
- Changing maxIterations mid-session

## Open Questions
- Should resumed sessions (after context limit) also respect the original maxIterations across the total experiment count? (Current design: yes, since we count results in jsonl which persists across resumes — this seems correct.)
