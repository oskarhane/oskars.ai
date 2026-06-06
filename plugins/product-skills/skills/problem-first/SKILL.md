---
name: problem-first
description: Inverts a proposed solution back into the problem underneath it. Use when a stakeholder, team, or roadmap hands you a solution ("we need a new notification system", "let's build X", "add a dashboard") and you need to find the real problem before committing build time — or when triaging a backlog of your own half-baked ideas to see which have a real problem and evidence behind them. Triggers on "problem-first", "what problem does this solve", "decompose this feature/idea", "triage my ideas", "is this the right thing to build", or a roadmap/feature/idea handed over as a fait accompli.
---

# problem-first

Every solution someone hands you is a **compressed, imprecise confession of a problem** they sense but haven't articulated. This skill decompresses it back into the problem — so you can check whether their chosen solution is one of several reasonable responses, or a jump to the wrong one.

It runs both directions:

- **Forward** — someone hands you a solution/roadmap. Decompress to the problem, expose the alternative builds they folded into one spec.
- **Reverse** — you have a backlog of your own ideas. Extract the problem each one solves, check evidence, triage. Most ideas die at "Evidence: none."

Same skill, both directions.

## The posture

Do **not** tell the team to stop and do research first — teams holding solutions have political and emotional momentum, and halting them burns your influence. Instead, **use the solution as the starting point for the research.** Treat the proposed solution as a research artifact: evidence of a real pain someone felt, compressed into an answer. Your job is to dig *underneath* the roadmap, not stand in front of it blocking.

## How to run it

Take the proposed solution as input. Produce **all eight sections below, every time, in order.** The value of this skill is that it forces the sections a PM under pressure reliably skips — the assumption challenges, the alternative framings, and the draft message. A partial run is worse than none; complete all eight before returning anything.

Ground every section in the user's actual product, users, and constraints if those are available (company context files, prior conversation, the codebase). Generic PM advice is a failure mode — be specific.

### 1. Solution-jumping diagnosis
What signal did they detect that made them propose *this* solution? Name the symptoms — support tickets, complaints, a metric, a competitor, a gut feeling. This is the evidence, compressed.

### 2. Underlying problem
Decompress the signal into the pain. One or two sentences. What is actually going wrong for the user, beneath the proposed feature?

### 3. Assumption challenges
List each load-bearing assumption the solution rests on. For each:
- **Assumption:** what must be true for this solution to work.
- **Risk if wrong:** the concrete cost of building on it and being wrong.
- **Validation:** the cheapest test that would confirm or kill it (read N support tickets, pull engagement data, ask in the next 5 interviews).

### 4. Problem statement
One structured sentence:
> [Users who …] struggle to [job] because [cause], which leads to [consequence]. Success would mean [observable outcome].

### 5. Three alternative framings
Three *different* problem framings the original brief may have collapsed into one. For each, name the **solution space** it opens. The point is to surface that the team's single feature spec hid two or three equally viable — but different — builds. Make at least one framing clearly *not* the originally proposed solution.

### 6. Evidence status
`none` / `weak` / `strong` — and what evidence exists. This is the triage gate in reverse mode: ideas at `none` get parked, not built.

### 7. Draft message
A short, ready-to-send message to the team/stakeholder that reframes from solution to problem **without ambushing them.** Skipping this is how new PMs end up quietly not-building-the-roadmap while the team has no idea why. Acknowledge the signal they detected, then open the problem.

### 8. Recommended next step
The single cheapest action that moves this forward: which assumption to validate first, or — in reverse mode — park / pitch / spec.

## Reverse mode (idea triage)

Feed in your own idea instead of someone else's solution. Run the same eight sections, but lead with **Evidence status** as the gate. Across a backlog, expect ~90% to die at `Evidence: none`, a handful to survive with a real problem underneath, and rarely one ready to pitch with the evidence pack already assembled. The bottleneck for idea-rich PMs is triage capacity, not idea generation — this is the triage protocol.

## Why run it in AI rather than in your head

You *can* do this by hand — people have for decades. But under time pressure, humans skip the three hard sections (assumption challenges, alternative framings, draft message) — exactly the ones that prevent committing a quarter of engineering to the wrong build, or ambushing the team. Forcing all eight outputs every run is the whole point.
