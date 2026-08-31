# beyond-the-notebook

Production system design for AI engineers, one buildable project at a time.

Most of us can train a model and lose the thread the moment it has to survive
concurrency, failure, and other people. These projects are the missing half:
small, real systems where the hard part is the design, not the maths.

Every project ships with the reasoning attached — what was considered, what was
chosen, why, and what breaks at scale. **The decisions are the product. The code
is the excuse to write them down.**

---

## Projects

Numbered in **build order** — the number is when it was built, not a required
sequence or a difficulty ranking. Start anywhere. Each links to its own README
with architecture and schema diagrams.

| Project | What it is | Teaches | Level | Status |
|---|---|---|---|---|
| **[01-claim-loop](01-claim-loop/)** | Claims get OCR'd, low-confidence fields go to a human reviewer, corrections are kept as signal | queues · task claiming · leases · append-only audit | L2 + deployed | 🔨 building |

<!-- Template for the next row — keep it to one line per cell:
| **[NN-name](NN-name/)** | one sentence, what it actually does | 3-4 concepts, dot-separated | L? | ⬜ planned / 🔨 building / ✅ done |
-->

Ideas considered but not started are in [IDEAS.md](IDEAS.md).

---

## Find a concept

What each idea is covered by, and where. This is the map that stops five
projects teaching the same three things.

**APIs and protocols**

| Concept | Covered by |
|---|---|
| HTTP APIs, status codes, idempotency | 🔨 01-claim-loop |
| Streaming — SSE, WebSockets | ⬜ |
| Auth — API keys, JWT, OAuth | ⬜ |

**Resilience**

| Concept | Covered by |
|---|---|
| Retries, exponential backoff, jitter | ⬜ |
| Rate limiting, backpressure | ⬜ |
| Circuit breakers, graceful degradation | ⬜ |

**Async and messaging**

| Concept | Covered by |
|---|---|
| Async queues, producer/consumer | 🔨 01-claim-loop |
| At-least-once vs exactly-once delivery | 🔨 01-claim-loop |

**Data**

| Concept | Covered by |
|---|---|
| Storage choice — SQL vs KV vs object vs vector | 🔨 01-claim-loop |
| Schema design, indexes, query plans | 🔨 01-claim-loop |
| Migrations, transactions, connection pooling | 🔨 01-claim-loop |
| N+1 queries and how to spot them | ⬜ |
| Caching, TTLs, invalidation | ⬜ |

**Delivery**

| Concept | Covered by |
|---|---|
| Containers, layers, multi-stage builds | 🔨 01-claim-loop |
| CI — automated tests on push | ⬜ |
| CD — automated deploy on merge | ⬜ |
| Kubernetes — Deployments, Services, probes | ⬜ |
| Autoscaling, health checks, scale-to-zero | ⬜ |

**Operations**

| Concept | Covered by |
|---|---|
| Observability — logs, metrics, traces | 🔨 01-claim-loop |
| Secrets and security boundaries | ⬜ |
| Cost modelling | 🔨 01-claim-loop |

✅ done · 🔨 building · ⬜ not covered yet

---

## How each project is structured

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

Levels compose with deployment independently — `L2 + deployed` means a container
running in the cloud without Kubernetes or a pipeline, which is a real and
common shape.

## Conventions

- Project folders are numbered in build order — `01-claim-loop`, `02-...`.
  Numbers are assigned once and never reshuffled, so links stay valid.
- Each project is developed on a branch named after it (without the number),
  merged to `main` when it reaches its declared depth. Root-level files are
  edited on `main` directly.
- Increment commits are **never squashed**. Each commit adds exactly one concept,
  so the commit history is the lesson log.
- Diagrams are Mermaid in fenced code blocks — text, so they diff in review and
  don't rot into a stale PNG nobody regenerates.
