# Decisions

Every decision starts **OPEN** with the options laid out. I fill in *Chosen*
and *Why* — in my own words — before the code that depends on it gets written.
When I change my mind, I do not edit the original: I add a **Revised** block
underneath with the date and what changed my mind. Those are the entries worth
reading.

Format: Status / Options / Chosen / Why / Revisit when.

---

## D-001 — Where does the review queue live?

**Status:** OPEN

The queue holds claims waiting for a human. Options:

- **Postgres table** — queue state and review state are the same rows
- **Redis list / stream** — fast, but a second store to keep in sync with Postgres
- **Cloud Pub/Sub or SQS** — managed, durable, but opaque and no cheap "show me the queue"

Question that decides it: when a reviewer submits a correction, what has to
happen atomically? If the queue is separate from the data, what happens when
one write succeeds and the other fails?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-002 — The claim state machine

**Status:** OPEN

Every claim is in exactly one state. List the states, and every legal
transition between them, before writing any schema.

States (draft — replace with mine):

```
uploaded → extracting → extracted → pending_review → in_review → approved
                                                              → rejected
```

For each transition, answer:

- What triggers it?
- What can interrupt it, and what state is left behind?
- Is it reversible?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-003 — Preventing double-assignment

**Status:** OPEN

Two reviewers ask for the next task in the same millisecond. What stops them
getting the same claim?

- **`SELECT ... FOR UPDATE SKIP LOCKED`** — Postgres hands each a different row
- **Optimistic: read then conditional `UPDATE ... WHERE status = 'pending'`** — retry on zero rows
- **Application-level lock / mutex** — works on one process, fails the moment there are two
- **`SELECT ... FOR UPDATE`** without `SKIP LOCKED` — correct, but reviewer B blocks

Understand what happens under each *before* choosing. This is the core of the
project.

**Chosen:**

**Why:**

**Revisit when:**

---

## D-004 — How human corrections are recorded

**Status:** OPEN

- **Update the extracted value in place** — simple, and destroys the signal
- **Append-only event log** — every model output and every human edit is a row
- **Both** — event log is the source of truth, a projection holds current values

What questions do I want to answer later? "How often is the model wrong on
field X?" "Did accuracy improve after the prompt change?" A schema that can't
answer those has thrown away the most valuable data in the system.

**Chosen:**

**Why:**

**Revisit when:**

---

## D-005 — Database access layer

**Status:** OPEN

- **Raw SQL (`psycopg` 3)** — every query visible; more boilerplate
- **SQLAlchemy Core** — composable SQL, still explicit
- **SQLAlchemy ORM** — fastest to write; hides exactly the things I'm here to learn

*Recommendation on file: raw SQL.* An ORM is an excellent machine for not
learning databases, and databases are goal #2. Costs me row→dict mapping by hand.

**Chosen:**

**Why:**

**Revisit when:**

---

## D-006 — Migrations

**Status:** OPEN

- **Numbered `.sql` files + a ~30-line runner I write** — a `schema_migrations`
  table, applied in order. Teaches what a migration *is*
- **Alembic** — real tool, autogenerate, couples to SQLAlchemy
- **`dbmate` / `golang-migrate`** — language-agnostic binary

Real test of whether I understand it: write a *down* migration and actually
roll one back. Most people never do, then find out in production that they can't.

**Chosen:**

**Why:**

**Revisit when:**

---

## D-007 — What escalates to a human?

**Status:** OPEN

Sending everything to a human defeats the purpose. Sending nothing makes the
loop decorative. The threshold is a cost decision:

- Cost of a human review: minutes × loaded hourly rate
- Cost of a wrong auto-approval: depends entirely on the claim
- Options: per-field confidence threshold / whole-document score / always
  escalate specific fields (totals, dates) regardless of confidence / sample a
  fixed % of auto-approvals for audit

Write the arithmetic down, even with made-up numbers. Made-up numbers I can
defend beat a threshold of 0.8 chosen because it looked round.

**Chosen:**

**Why:**

**Revisit when:**

---

## D-008 — Extraction backend

**Status:** OPEN

- **Stub** returning fixed fields + synthetic confidence
- **One LLM call** with a structured output schema
- **Real OCR** (Tesseract, Document AI, Textract)

*Recommendation on file: a stub first, a real model once the queue works.* Real OCR is a
trap — it is the part I already know how to do, and it would eat every evening
I have. Whatever I pick, the interface must be identical across all three so
swapping is a one-line change. Design that seam deliberately.

### Facts that constrain this decision (verified 2026-08-31)

Anthropic API list pricing, per million tokens:

| Model | ID | Input | Output | Context |
|---|---|---|---|---|
| Opus 5 | `claude-opus-5` | $5 | $25 | 1M |
| Sonnet 5 | `claude-sonnet-5` | $2 | $10 | 1M |
| Haiku 4.5 | `claude-haiku-4-5` | $1 | $5 | 200K |

- **Structured output** is `output_config: {format: {...}}` on the Messages API.
  The `output_format` parameter is deprecated. `client.messages.parse()`
  validates the response against the schema for you.
- **Structured output and citations are mutually exclusive** — setting both
  returns a 400. See the tension noted below.
- **PDFs** go in as base64 `document` blocks: 32 MB per request, 600 pages on
  1M-context models, 100 pages on 200K-context models (i.e. Haiku).
- **Batch API costs 50%** of standard rates and runs asynchronously.
- **Prompt caching** applies to the stable prefix (tools → system → messages).
  The extraction schema and instructions are identical on every call, so they
  are cacheable; the document must come after the last cache breakpoint.

### The tension worth resolving deliberately

A reviewer verifying an extracted field wants to know *where in the document it
came from*. That is what citations are for. But citations cannot be combined
with structured output in a single call. So: two calls, give up one, or have
the model return spans as ordinary fields in the schema? Each has a cost.

### Multi-provider (added after deciding to try GLM)

GLM (Zhipu / Z.ai) exposes an OpenAI-compatible endpoint, so it is reachable
with the `openai` SDK pointed at their `base_url` — no new client library
beyond that. Verify current model IDs and pricing against their docs; do not
trust remembered numbers.

Two reasons to run a second provider, one weak and one strong:

- **Weak:** it is cheaper. True, but at 18 documents the absolute cost is
  noise either way.
- **Strong:** **two models disagreeing is a better confidence signal than
  either model's self-reported confidence.** See below.

### Going through OpenRouter — what it costs me

One OpenAI-compatible endpoint, one key, one bill, and swapping models is a
string change. That is worth a lot when comparing models *is* the experiment.
What I give up, and should not be surprised by later:

- **The Batch API.** Anthropic's 50% async discount is a first-party feature
  and does not exist through an aggregator. This workload is inherently async,
  so that discount was genuinely applicable — I am choosing convenience over it.
- **Structured output is not uniform across models.** The OpenAI-compatible
  surface exposes `response_format`, but support varies *per model*: some do
  full JSON-schema, some only loose JSON mode, some neither. "Swap the model
  string" is therefore not quite free — a model without schema support returns
  prose that fails to parse. The extractor needs to handle a parse failure as a
  normal outcome, not an exception.
- **Provider-specific features don't pass through** — prompt caching, logprobs,
  and anything else outside the common surface.
- **A markup**, and a third party in the critical path (see LIMITS.md in this folder).
- **Requests route through a third party.** Irrelevant here because the data is
  synthetic. In a real claims system, routing PII through an aggregator is a
  compliance question, not a technical one.

### The calibration problem (this is the real one)

An LLM that says `"confidence": 0.95` is not reporting a probability. It is
generating the token `0.95` because that is what confident-sounding JSON looks
like. Routing on that number means routing on vibes, and the whole escalation
policy in D-007 rests on it.

Better signals, roughly in order of cost:

1. **Structural validation** — is the date parseable? is the postcode four
   digits? is the member number the right shape? Free, deterministic, catches
   a real class of extraction failure.
2. **Cross-field consistency** — `date_last_worked` should not precede
   `date_symptoms_commenced`. Free, and catches errors validation cannot.
3. **Two-model disagreement** — run Claude and GLM, escalate every field where
   they differ. Costs a second API call per document. This is a genuine
   uncertainty estimate rather than a self-report.
4. **Self-reported confidence** — nearly free, and the least trustworthy.

Whatever I pick, I can *measure* it: the dataset has ground truth, so I can
compute the actual escalation rate and the actual miss rate for each signal
rather than guessing.

### The batch question

Claims are not latency-sensitive — the whole point is that a human looks at
them later. A workload that is already queue-shaped is the exact workload the
Batch API is for, at half the price. Is there any reason this should be a
synchronous call?

**Chosen:**

**Why:**

**Revisit when:**

---

## D-009 — Reviewer interface

**Status:** OPEN

- **CLI** — `next-task` / `submit`, zero UI work
- **HTTP API + curl** — forces me to think about the API contract
- **Minimal web page** — needed eventually if this is a community demo

Note the trap: a UI makes the lease problem *invisible* during development,
because I'll only ever have one browser tab open. The CLI makes it easy to run
two workers at once and watch them race, which is the whole point of D-003.

**Chosen:**

**Why:**

**Revisit when:**

---

## D-010 — Observability

**Status:** OPEN

- **Langfuse Cloud** — free tier, zero ops
- **Self-hosted Langfuse** — docker-compose with ClickHouse, Redis, MinIO. An
  evening of work that teaches me about Langfuse's infra, not about mine
- **Plain structured logs + SQL queries** — no tracing, but the queue metrics
  that matter are all `SELECT`s anyway

Two different things get conflated here, and I should be explicit about which
I'm buying:

1. **LLM tracing** — what went into the model, what came out, how much it cost
2. **Operational metrics** — queue depth, human agreement rate, time-to-review,
   abandoned-lease rate

Langfuse does (1) well, and does (2) only if I deliberately push human verdicts
back as scores against the trace. (2) is the part that makes this a *loop*.

**Chosen:**

**Why:**

**Revisit when:**

---

## D-011 — Deployment target

**Status:** OPEN

No Kubernetes and no CI/CD in this project — deliberately. Containers yes.

- **GCP: Cloud Run + Cloud SQL Postgres** — scale-to-zero app, managed DB
- **Azure: Container Apps + PostgreSQL Flexible Server** — near-equivalent
- **Local only (docker-compose)** — zero cost, loses the connection-limit lesson

The cost trap to write down: the *app* scales to zero, the *database does not*.
A managed Postgres runs 24/7 and bills 24/7. That is the line item that would
quietly eat the $300 credit — which is why this is scoped as a short run rather
than something left standing.

### Facts that constrain this decision

- Cloud SQL runs **PostgreSQL 16**, matching `docker-compose.yml` exactly.
  `gen_random_uuid()`, `make_interval`, `JSONB`, partial indexes and
  `FOR UPDATE SKIP LOCKED` are all standard and all available.
- No superuser, but `cloudsqlsuperuser` can create roles — enough for the
  INSERT-only audit grants a later project wants.
- **`max_connections` is tied to instance size**, and the smallest tiers give
  roughly 25–50. `pool.py` currently uses `max_size=5`, so ten Cloud Run
  instances is fifty connections and already over. Cap `--max-instances`, or drop
  the pool to 1–2, which is normal on serverless.
- **Migrations must not run on app start.** Ten instances booting means ten
  concurrent `CREATE TABLE`s and the migration runner has no lock. They run as
  their own Cloud Run Job that must exit 0 before the new revision deploys.
- Networking is a fork: public IP behind the Cloud SQL connector is free and
  IAM-gated; private IP matches TPD §2.4's *no public data-plane access* and
  costs about $8/month for the serverless VPC connector.

**Chosen:** GCP. Cloud Run — a Service for the API, Jobs for the worker and
reaper — with Cloud SQL for PostgreSQL 16, Cloud Storage for documents, and
Secret Manager. Smallest shared-core tier, HA off. **Deployed for roughly one
week to learn what breaks when the app scales out, then deleted.** Costed in `ESTIMATE.md` at ~$4.

**Why:**

**Revisit when:**
