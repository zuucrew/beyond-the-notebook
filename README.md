# beyond-the-notebook

Production system design for AI engineers, one buildable project at a time.

Most of us can train a model and lose the thread the moment it has to survive
concurrency, failure, and other people. These projects are the missing half:
small, real systems where the hard part is the design, not the maths.

Every project ships with the reasoning attached — what was considered, what was
chosen, why, and what breaks at scale. **The decisions are the product. The code
is the excuse to write them down.**

## Projects

### [claim-loop](claim-loop/) · L2 + deployed · in progress

**Human-in-the-loop claims processing.** Documents arrive, a machine extracts
fields, low-confidence extractions are routed to a human reviewer, and the
human's correction is captured as a first-class signal rather than an overwrite.

The idea it's built around: *human-in-the-loop is not a UI feature.* A human is
a worker that is slow, expensive, unreliable, and impossible to retry cheaply —
so putting one in a pipeline turns a request/response call into an async queue
with a state machine. Every hard problem in the project follows from that.

Built on Postgres with no message broker, because the queue entry and the claim
are the same row.

*Covers:* async queues · task claiming without double-assignment · leases and
at-least-once delivery · append-only audit design · confidence routing and its
cost model · LLM observability

## How these are structured

Every project is a folder in this repo containing four files:

| File | What's in it |
|---|---|
| `README.md` | What it does, how to run it, architecture and schema diagrams |
| `DECISIONS.md` | Options considered, what was chosen, why, and what changed my mind |
| `LIMITS.md` | What breaks at scale, and what I'd do about it |
| `src/` | The code |

Plus `Dockerfile` at L2, `.github/workflows/` at L3, `k8s/` at L4.

`DECISIONS.md` is started **before** any code and updated whenever I change my
mind — the changed-my-mind entries are the most useful thing in the repo.
`LIMITS.md` exists even for projects that only run locally, because reasoning
about what breaks is free and doesn't require deploying anything.

## Depth levels

Each project declares how far it goes, and why. Choosing the depth is itself a
design decision — overbuilding wastes as much time as underbuilding.

| Level | Means | Used when |
|---|---|---|
| **L1** | Runs locally | The lesson is design, algorithm, or database. Deployment would add noise |
| **L2** | Containerised — runs anywhere | Default for most projects |
| **L3** | Tests and CI on every push | The CI/CD reps are the point |
| **L4** | Kubernetes, CD, observability | Deployment or scaling *is* the lesson |

## Conventions

- Each project is developed on its own branch, `project/<name>`, and merged to
  `main` when it reaches its declared depth.
- Increment commits are **never squashed**. Each commit adds exactly one concept,
  so the commit history is the lesson log.
- Diagrams are Mermaid in fenced code blocks — text, so they diff in review and
  don't rot into a stale PNG nobody regenerates.
