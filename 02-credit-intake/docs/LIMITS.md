# Limits

What this system does not do, where it breaks, and what it would cost to fix.
Written up front from what is already known, and added to every time something
breaks in a way that was not predicted.

---

## Scope

- **L2 only.** Runs under Docker Compose on one machine. Not deployed, no
  Kubernetes, no CI/CD. Project 1 covered deployment.
- **Synthetic documents.** The credit bundles are generated. Real bank
  statements are worse: scanned at an angle, stapled, photographed on a phone,
  occasionally upside down.
- **One tenant.** No per-lender configuration, no per-lender field schemas.
- **No object storage.** Bundles live on a mounted volume. A container restart
  keeps them; a lost volume does not.

## Known weaknesses, before building

- **Three stores.** Postgres holds the record, Redis holds the work, and the
  result backend holds unjoined page results. Any inconsistency between them is
  a bug this system can have and `01-claim-loop` structurally could not.
- **Redis is not durable by default.** A broker restart can drop queued
  messages. The applications stay in `received` or `extracting` forever with
  nothing to notice.
- **Result backend expiry.** Page results have a TTL. A chord that waits longer
  than the TTL joins against results that are no longer there.
- **The chord is a coordination point.** It is one task that must not be lost,
  and losing it strands every page result behind it.
- **No global rate limit without extra machinery.** Celery's `rate_limit` is
  per worker process, so it drifts the moment you scale workers.
- **Page-level parallelism assumes pages are independent.** They are not always:
  a table of transactions that runs across a page break has to be stitched, and
  nothing here does that.

## Carried over from `01-claim-loop`

- **Model confidence is not calibrated.** A self-reported 0.95 is not a 95%
  chance of being right. Structural validation and cross-field consistency are
  better signals and are still not used.
- **The three-way null.** "Field does not apply" / "model could not read it" /
  "genuinely blank on the form" are different things and collapsing them loses
  information.
- **No tests yet.** Same gap as project 1. `SKIP LOCKED` was never proven there
  either.

## Scale

Sized for one machine, tens of bundles, a handful of workers. It has not been
run against sustained load and no number in this repo should be quoted as a
throughput figure.

## Where it breaks first

*(Fill this in as it happens. Predictions live in D-000 — this section is for
what actually broke.)*
