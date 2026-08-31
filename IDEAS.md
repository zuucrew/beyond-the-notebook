# Ideas

Projects considered but not started. Kept short on purpose — a backlog with
essays in it is a second thing to maintain.

Each entry names the concepts it would cover, so overlap is visible before an
evening gets spent on it. Concepts are the ones tracked in the README map.

---

## Rate limiter in front of an LLM API

Shared token bucket across many workers. Two-dimensional — requests/min *and*
tokens/min — where the token cost of a call is unknown until after it returns,
so you estimate, reserve, then reconcile.

**Covers:** rate limiting · backpressure · caching, TTLs, invalidation

**Why it's a good Redis project:** run two instances with in-memory counters
and the limit is silently 2×. The failure is loud and immediate, which is how
a tool should teach you it exists. `INCR` is atomic; check-then-increment is a
race — the same lesson `SKIP LOCKED` teaches, in a different tool.

**Open:** does this stand alone, or is it a component of the OCR pipeline below?
If both, they overlap on backpressure and only one should own it.

---

## Two-stage document pipeline — layout model then VLM

Layout model finds regions of interest, crops are sent to a vision model.
Cheaper per page and higher effective resolution, and ROI coordinates give
per-field provenance for free.

**Covers:** retries, exponential backoff, jitter · circuit breakers, graceful
degradation · backpressure · Kubernetes · autoscaling, health checks

**The framing that matters:** this is not an OCR project. Scoped as "improve
extraction accuracy" it becomes model tuning, which teaches nothing new. Scoped
as **"a pipeline that calls a slow, expensive, occasionally failing service"**
it becomes a resilience project, and the layout model is just the thing that is
slow and flaky.

**Why it's a natural L4:** two services with genuinely different resource
profiles — one tiny and I/O-bound, one compute-heavy and batch. Scaling them
independently *is* the lesson, which is the only condition under which
Kubernetes earns its place.

**Overlap warning:** async queues and producer/consumer are already covered by
01-claim-loop. This project must earn its place on the resilience concepts, not
by rebuilding a queue.

**Open:** buy-vs-build. Textract and Document AI already implement exactly this
architecture with calibrated per-field confidence. "Because building it is the
point" is a valid answer — but it should be an explicit decision.
