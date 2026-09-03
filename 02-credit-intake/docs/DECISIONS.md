# Decisions

Every decision starts **OPEN** with the options laid out. I fill in *Chosen*
and *Why* — in my own words — before the code that depends on it gets written.
When I change my mind, I do not edit the original: I add a **Revised** block
underneath with the date and what changed my mind. Those are the entries worth
reading.

Format: Status / Options / Chosen / Why / Revisit when.

---

## D-000 — Prediction

**Status:** OPEN — write this before increment 1. **Do not edit it afterwards.**

This is not a decision. It is a bet, made before the code exists, so that at
the end there is something to be wrong against. Answer in your own words, then
freeze the section and add a **Scored** block at the very end of the project.

**What I expect Celery to give me that the Postgres queue did not:**

>

**What I expect it to cost me:**

>

**What I think will break first, and why:**

>

**What I think will happen when I kill a worker mid-task:**

>

**What I think happens to a `chord` when one of forty pages fails:**

>

**Wall-clock time to extract one 40-page bundle — project 1's serial approach
vs. this:**

>

**Scored:** *(fill in after increment 10 — what I got right, what I got wrong,
and what I had not thought of at all)*

---

## D-001 — Why a broker at all, given D-001 of `01-claim-loop`

**Status:** OPEN

Project 1 argued at length that the review queue belongs in Postgres, and that
argument has not been refuted. So this project has to justify itself.

- **Keep everything in Postgres** — add a `pages` table and a completion
  counter; the last page to finish runs the join
- **Celery + Redis for machine work only** — human queue stays in Postgres
- **Celery + Redis for everything** — one mechanism, no split

Question that decides it: what does the fan-out/join actually require, and can
Postgres express it without a race on "who runs the join"?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-002 — Redis or RabbitMQ as the broker

**Status:** OPEN

Celery is a library, not a broker; it needs one underneath.

- **Redis** — one process for broker *and* result backend, trivial to run
- **RabbitMQ** — real acks, redelivery, dead-letter queues, per-message routing

Question that decides it: this project is *about* delivery semantics. Does
picking the weaker broker hide the lesson, or does it expose it more sharply
by making the failure visible?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-003 — Unit of work: document or page

**Status:** OPEN

- **One task per document** — simple, but no parallelism within a bundle
- **One task per page** — real fan-out, N times the messages, and a join to write
- **Chunks of K pages** — fewer messages, coarser retry granularity

Question that decides it: when a single page fails, how much work is thrown
away and re-done?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-004 — Delivery semantics and idempotency

**Status:** OPEN

Celery acks early by default. `acks_late` moves the ack to completion, which
turns "lost work" into "duplicated work".

- **Default (ack on receipt)** — a killed worker silently drops the page
- **`acks_late`** — the page is redelivered, so extraction must be idempotent

Question that decides it: what is the idempotency key, and what stops a
duplicate from writing two `field_events` rows for the same extraction?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-005 — What `partially_extracted` means

**Status:** OPEN

Thirty-nine pages succeed, one fails after three retries.

- **Fail the whole application** — clean, wasteful, and infuriating for the applicant
- **Route to human review with the failed page flagged** — the human does what the machine could not
- **Hold and retry the single page on a schedule** — the application sits in limbo

Question that decides it: where are the 39 successful page results *stored*
while this is being decided, and what happens if the result backend expires
them first?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-006 — Where the join result is written, and the two-store problem

**Status:** OPEN

The chord callback assembles page results and writes one record to Postgres.
The task is acked when it returns. If the write fails after the ack, the work
is gone and nothing knows.

- **Write then ack, accept duplicates** — at-least-once, needs D-004 to hold
- **Transactional outbox** — the honest fix, and a relay to build
- **Reconciliation sweep** — a periodic job that finds applications stuck in
  `extracting` past a deadline and re-dispatches

Question that decides it: project 1 could not have this bug, because the job
*was* the record. What is the cheapest thing that restores that guarantee?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-007 — Bounding concurrency

**Status:** OPEN

In project 1, in-flight API calls were bounded by worker count. With fan-out,
one bundle can put forty calls in flight.

- **Celery `rate_limit` per task** — per-worker, not global; drifts as workers scale
- **A shared token bucket in Redis** — global and correct, one more thing to run
- **Small `prefetch_multiplier` + fixed worker concurrency** — crude but real
- **Nothing; let the provider 429 and rely on retries** — cheap, and burns money

Question that decides it: which of these still holds when you run
`--scale worker=5`?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-008 — Retry policy

**Status:** OPEN

Forty pages hit the same 429 at the same moment and, without jitter, retry at
the same moment.

Decide: max attempts, base delay, growth factor, jitter, and which errors are
retryable at all. A 429 is. A malformed-PDF error is not — retrying it three
times is three times the cost for the same failure.

**Chosen:**

**Why:**

**Revisit when:**

---

## D-009 — Circuit breaking and degradation

**Status:** OPEN

Provider is down. Forty pages x three attempts x every queued bundle.

- **No breaker** — the queue drains into failures at full speed
- **Breaker that fails fast** — stop calling, mark the batch retryable, back off
- **Breaker plus fallback model** — degrade to a weaker or local extractor

Question that decides it: when the breaker opens, what happens to the messages
already in the queue — dropped, held, or requeued with delay?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-010 — Caching and invalidation

**Status:** OPEN

A resubmitted bundle is usually 39 identical pages and one corrected one.
Hashing the rendered page image makes the skip trivial.

The hard half is invalidation: when the prompt, the model, or the field schema
changes, every cached result is silently wrong.

- **Hash the image only** — maximum hit rate, stale on every prompt change
- **Hash image + prompt + model + schema version** — correct, lower hit rate
- **TTL only** — wrong for a bounded window, no thought required

**Chosen:**

**Why:**

**Revisit when:**

---

## D-011 — What stays on Postgres

**Status:** OPEN

Celery is now in the stack, which makes it tempting to put the human review
queue on it too.

Question that decides it: what does a reviewer's "submit correction" have to
do atomically, and does moving that queue to Redis reintroduce exactly the
problem D-001 of project 1 was avoiding?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-012 — The comparison

**Status:** OPEN — write last.

Side by side against `01-claim-loop`:

- What got genuinely easier
- What got harder, and whether the fan-out paid for it
- Lines of code and number of moving parts, honestly counted
- Which failure modes are new, and which of them project 1 simply could not have
- If you were starting a third system tomorrow, which would you reach for and
  under what condition would you switch

**Chosen:**

**Why:**
