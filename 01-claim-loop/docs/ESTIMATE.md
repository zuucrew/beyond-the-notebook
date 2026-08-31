# Estimate

What this project costs to build and practise on — money and evenings.

Short version: **under $20 in cash, and about 9 evenings.** The cash is fully
covered by GCP free credit. The evenings are the real budget.

---

## Money

### Increments 0–4 — the core of the project

**$0.** Postgres runs in Docker on the laptop. The extractor is a stub that reads
the ground-truth JSON in `dataset/`. No API calls, no cloud, nothing metered.

This is most of the learning — schema, state machine, `SKIP LOCKED`, leases — and
it costs nothing at all.

### Increment 5 — real extraction

The dataset is 18 documents at roughly 5 pages each. A full run is on the order
of ~135k input tokens. Open models on Groq are cheap enough that a full pass
costs cents, and development means running it dozens of times, not thousands.

**Budget $5.** It will almost certainly come in under that.

Verify current rates before relying on this — provider pricing moves, and these
are estimates rather than quotes.

### Increments 6–9

**$0.** Langfuse Cloud has a free tier that a few hundred traces will not trouble.
Docker is free. Nothing here is metered.

### Increment 10 — deployed on GCP

| Service | Monthly | Note |
|---|---|---|
| **Cloud SQL** (smallest instance) | **$8–15** | The only thing always running |
| Cloud Run (Service + Jobs) | ~$0 | Scales to zero; free tier covers 2M requests |
| Cloud Storage | ~$0 | 18 PDFs is ~5 MB against a 5 GB free tier |
| Artifact Registry | ~$0 | 0.5 GB free |
| Cloud Build | ~$0 | 120 build-minutes/day free |
| Secret Manager | ~$0 | Free tier covers a handful of secrets |
| **Total** | **~$10–15/month** | Essentially all Cloud SQL |

### All in

| | Cost |
|---|---|
| Building locally, increments 0–9 | $0 |
| Model experimentation | < $5 |
| One month deployed, to learn increment 10 | ~$15 |
| **Total** | **< $20** |

Comfortably inside the $300 credit — with the caveat that the credit has an
expiry window, so the constraint is the calendar, not the balance. Check the
current terms when you activate it.

---

## The one thing that can actually burn money

**A forgotten Cloud SQL instance.**

Compute scales to zero. Storage is free at this size. The database does not stop,
and it is the only line item that accrues while nothing is happening. Three
forgotten months is ~$45 — not a disaster, but entirely avoidable.

Controls, in order of usefulness:

1. **Delete the instance when you are done with increment 10.** Take a `pg_dump`
   first; recreating takes minutes.
2. **Stop it between sessions** — `gcloud sql instances patch <name>
   --activation-policy NEVER`. You still pay for storage, which is pennies.
3. **Set a budget alert at $50.** Takes two minutes, catches everything else.
4. **Cap `--max-instances` on Cloud Run.** Protects against a runaway retry loop,
   and against connection exhaustion at the same time.

Two traps worth naming because they are easy to walk into:

- **Enabling Cloud SQL high availability** doubles the cost and teaches nothing
  here. Leave it off.
- **Sizing up "to be safe."** The smallest shared-core instance is more than
  enough for 18 documents and a handful of workers.

---

## Evenings

The scarcer budget, and the one worth planning.

| Increments | Evenings | What happens |
|---|---|---|
| 0 — decisions | 1 | Fill in `DECISIONS.md`. The state machine and D-003 settle the schema |
| 1–2 — schema, routing | 2 | Migration, two tables, submit, stub extractor, confidence threshold |
| **3–4 — locking, leases** | **2** | **The core of the project.** Two workers racing, then crash recovery |
| 5–7 — real model, tracing | 2–3 | Groq, Langfuse, queue metrics |
| 8 — containerise | 1 | Dockerfile, compose. **L2** |
| 9–10 — idempotency, deploy | 1–2 | Unique index; then Cloud Run + Cloud SQL |
| **Total** | **~9** | |

Increments 3 and 4 are the ones to slow down on. Everything before them is setup
and everything after is extension — the locking and lease work is the reason the
project exists.

### The cheapest hour in the whole project

Two `psql` terminals, before writing any application code. Watch `SKIP LOCKED`
hand out different rows, then watch it block without it, then watch a rollback
release the row.

Five minutes, zero cost, and it changes what you write afterwards.

---

## What would change these numbers

- **Real OCR instead of the stub in v0.1** — several evenings, no new system design
- **Long PDFs at hundreds of pages** — token cost per document rises sharply; see
  `LIMITS.md`
- **A layout model** — a second deployable, GPU or CPU workers, and a crossover
  around ~1M pages/year before it pays for itself. Tracked in `IDEAS.md` as a
  separate project
- **Leaving it deployed** — the only recurring cost, and it is the database
