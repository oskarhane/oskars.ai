# Failure policies

Every node declares exactly one `failure_policy`. `run` applies it when a node's `gbuild-reviewer` pass
returns `fail`, or the node's own agent errors out.

| policy     | `run` does                                                                                          |
| ---------- | ----------------------------------------------------------------------------------------------------- |
| `retry`    | Re-dispatch the same node, same contract, up to 2 more attempts. Same agent role, fresh context.      |
| `fallback` | On failure, dispatch a named alternate approach (`plan` records it in the node's `contract.input`) instead of retrying the same approach. |
| `skip`     | Mark `cancelled`, not `failed`. Downstream nodes treat it as satisfied (see derived queries). Use only when the node is genuinely optional to the destination. |
| `repair`   | Feed the reviewer's `acceptance_results` failures back into a repair pass targeting just the failed criteria, then re-review. Bounded: 2 repair attempts, then escalate. |
| `escalate` | Stop dispatching this node's dependents, checkpoint it `failed`, and surface it to the user in `/gbuild:status` as needing a decision. `run` does not guess a fix. |
| `stop`     | Halt the entire run — not just this node's downstream. Reserved for failures that put the whole graph's premise in doubt (e.g. a `decision` node's answer contradicts an already-completed node). |

## Choosing a policy at plan time

- Most `code`/`test` nodes: `repair` — the reviewer's per-criterion verdict is exactly the feedback a
  repair pass needs.
- `research`/`decision` nodes: `retry` or `escalate` — there's rarely a mechanical "repair" for a wrong
  answer; either try again with a fresh context or hand it to the user.
- Nodes explicitly marked non-essential to the destination in `plan`'s own judgement: `skip`.
- Nodes with a known, nameable alternate approach: `fallback`.
- Anything whose failure would make a sibling's already-completed work suspect: `stop`. Use sparingly —
  this is the escape hatch for "the graph's premise broke," not a normal failure mode.

## Bounds are mandatory

`retry`, `repair`, and `fallback` all have hard caps enforced by `run` (2 attempts unless the node
overrides it in `contract.input`). No policy allows an unbounded loop — that's what turns a bounded
retry into the "controlled cycle" shape's job (`reference/shapes.md`), which has its own explicit round
cap and dedup rule.
