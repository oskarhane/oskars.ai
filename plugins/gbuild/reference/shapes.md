# Graph shapes

`plan` classifies each cluster of nodes it creates into one of these. `run` uses the classification to
decide how to schedule it. This is a lens for judgement, not a field stored on the node — the shape
falls out of `dependencies`.

## Chain

`A -> B -> C`. Each node genuinely reads the previous one's output. Runs serially — there is no
fan-out to exploit. **Before encoding a chain, run the cut test on every edge** (see
`graph-format.md`): a chain is often three unrelated nodes someone thought of in order, which should
instead be three nodes in the same wave.

## Diamond (fan-out / join)

`A -> {B, C} -> D`. `A` produces something `B` and `C` both need; `D` needs both `B` and `C`. `B` and
`C` have no edge between them — they land in the same wave and `run` dispatches them concurrently. `D`
is the join: it waits for every incoming edge, not just the first.

This is the shape gbuild exists to execute properly. hone-ai v1 would serialize `B` then `C` even
though nothing requires it; the whole point of a real dependency graph is that `plan` states the truth
(`B` and `C` are independent) and `run` acts on it (dispatches both at once).

## Router

One node whose output selects which of several downstream nodes actually runs — not all of them, not
none, exactly the branch the output implies. Model this as a `decision`-type node whose `contract.output`
names the chosen branch, with the downstream nodes each depending on it; `run`'s job is to only dispatch
the node(s) the router's output actually selected, and mark the un-selected siblings `cancelled` (which,
per the derived-queries rule, still satisfies anything waiting on "the router resolved").

## Controlled cycle

A bounded loop — e.g. generate → verify → repair → re-verify. Never an open-ended `while`. Every cycle
in a graph must have, at plan time:

- a **hard round cap** (a number, not "until it looks right")
- a **dedup rule** against everything already seen this cycle, so repair doesn't re-surface a fix that
  already failed once
- an explicit **exit node** reached either by the verify passing or by hitting the cap and escalating

`run` implements this as a bounded loop (see `skills/run/SKILL.md`), never as extra graph edges that
loop back on themselves — `scripts/graph.py` rejects literal cycles in `dependencies` (that's how it
catches a malformed graph). A controlled cycle is a *behavior* `run` executes around a small
sub-cluster, not a topology `graph.py` has to tolerate.

## Choosing a shape

Ask, per pair of nodes: does one actually read the other's output (cut test)? If two nodes both come
out "no" against everything else in the cluster, they're a diamond's fan-out, not a chain. If a node's
output determines *which* of several next steps applies, it's a router, not a diamond (a diamond runs
every branch; a router runs one). If the same node needs to run again based on feedback about its own
prior output, it's a controlled cycle, not an edge back to itself.
