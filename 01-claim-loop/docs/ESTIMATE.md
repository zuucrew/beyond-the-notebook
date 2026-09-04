# Estimate

What this project costs to build and practise on, in money and evenings.

Short version: **under $10 in cash, and about 9 evenings.** The cash is trivial
because the deployment is torn down after about a week. The evenings are the
real budget.

---

## Money

### Building the queue, locally

**$0.** Postgres runs in Docker on the laptop. The extractor is a stub that reads
the ground-truth JSON in `dataset/`. No API calls, no cloud, nothing metered.

This is most of the learning (schema, state machine, `SKIP LOCKED`, leases) and
it costs nothing at all.

### Adding a real extraction model

The dataset is 18 documents at roughly 5 pages each; a full run is on the order
of ~135k input tokens. Open vision models are cheap enough that a full pass
costs cents, and development means running it dozens of times, not thousands.

**Budget $5.** It will almost certainly come in under that.

Verify current rates before relying on this, because provider pricing moves and these
are estimates rather than quotes.

### Tracing, metrics and containers

**$0.** Langfuse Cloud has a free tier that a few hundred traces will not trouble.
Docker is free. Nothing here is metered.

### Deploying to GCP for about a week

The deployment exists to learn one thing: what breaks when the app scales out
and the database does not. That takes days, not months, so it is sized and
budgeted as a **7-day run, then deleted.**

| Service | 7 days | Note |
|---|---|---|
| **Cloud SQL**: smallest shared-core, HA off | **~$2.50–3.50** | The only meter that runs continuously |
| Cloud SQL storage: 10 GB SSD minimum | ~$0.40 | |
| Cloud Run: Service + Jobs | ~$0 | Scales to zero; free tier covers 2M requests |
| Cloud Storage | ~$0 | 18 PDFs is ~5 MB against a 5 GB free tier |
| Artifact Registry | ~$0 | 0.5 GB free |
| Cloud Build | ~$0 | 120 build-minutes/day free |
| Secret Manager | ~$0 | Free tier covers a handful of secrets |
| **Total** | **~$3–4** | |

Turn HA on and it roughly doubles. It teaches nothing here, so leave it off.

### All in

| | Cost |
|---|---|
| Everything built and run locally | $0 |
| Model experimentation | < $5 |
| Deployed to GCP for a week | ~$4 |
| **Total** | **< $10** |

Against $300 of credit this is noise. The binding constraint is the credit's
expiry window and your evenings, not the balance.

---

## Cost control, given a 7-day window

One control, and it is the only one that matters:

```bash
gcloud sql instances delete claim-loop-db
```

**Delete the instance when you are done with it.** Take a `pg_dump` first if you
want the corrections; recreating takes minutes and the schema is in `migrations/`.

If you want to pause rather than delete between sessions:

```bash
gcloud sql instances patch claim-loop-db --activation-policy NEVER
```

You still pay for storage, about $0.50 a week, and nothing else.

Set a budget alert at $50 anyway. It takes two minutes and it catches the thing
you did not think of.

Two traps worth naming because they are easy to walk into:

- **Cloud SQL high availability** doubles the cost and teaches nothing here.
- **Sizing up "to be safe."** The smallest shared-core tier is more than enough
  for 18 documents. A larger tier also raises `max_connections`, which hides the
  connection-exhaustion lesson the deployment exists to teach.

---

## Evenings

The scarcer budget, and the one worth planning.

| Step | Evenings | What happens |
|---|---|---|
| 0: decisions | 1 | Fill in `DECISIONS.md`. The state machine and D-003 settle the schema |
| 1–2: schema, routing | 2 | Migration, two tables, submit, stub extractor, confidence threshold |
| **3–4: locking, leases** | **2** | **The core of the project.** Two workers racing, then crash recovery |
| 5–7: real model, tracing | 2–3 | Groq, Langfuse, queue metrics |
| 8: containerise | 1 | Dockerfile, compose. **L2** |
| 9–10: idempotency, deploy | 1–2 | Unique index; then Cloud Run + Cloud SQL |
| **Total** | **~9** | |

The locking and lease steps are the ones to slow down on. Everything before is setup
and everything after is extension. The locking and lease work is the reason the
project exists.

### The cheapest hour in the whole project

Two `psql` terminals, before writing any application code. Watch `SKIP LOCKED`
hand out different rows, then watch it block without it, then watch a rollback
release the row.

Five minutes, zero cost, and it changes what you write afterwards.

---

## What would change these numbers

- **Real OCR instead of the stub in v0.1**: several evenings, no new system design
- **Long PDFs at hundreds of pages**: token cost per document rises sharply; see
  `LIMITS.md`
- **A layout model**: a second deployable, GPU or CPU workers, and a crossover
  around ~1M pages/year before it pays for itself. Tracked in `IDEAS.md` as a
  separate project
- **Leaving it deployed**: the only recurring cost, and it is the database.
  At roughly $0.50 a day it is not dangerous; it is just untidy.
