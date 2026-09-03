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

**Chosen:** Postgres. The queue is the `claims` table — a `status` column plus
a partial index. No broker, no Redis, no Celery.

**Why:** The queue entry and the claim are the *same row*, so completing a
review is one transaction against one store. Split them and "reviewer submits a
correction" becomes two writes to two systems with no shared transaction, and
both orderings break: commit the correction and fail to dequeue, and a second
reviewer gets finished work; dequeue and fail to commit, and the claim is
silently lost. The standard fix is the transactional outbox — which means
keeping a Postgres table anyway, plus a broker, plus a relay.

The "never use a database as a queue" objection is real, but it is aimed at
machine-consumer queues doing 100k messages a second. **The consumer here is a
human.** Ten reviewers at two minutes each is 0.08 claims per second — four
orders of magnitude of headroom, and it comes from humans being slow rather
than Postgres being fast. The consumer being slow is what makes the simple
architecture correct.

Also: the queue's access pattern is relational. "Oldest pending claim of this
type that this reviewer is qualified for" is a `WHERE` clause, not a `pop()`.

**Revisit when:** sustained throughput exceeds ~1,000 claim operations/sec, or
a second service needs to consume claim events. The first is a broker; the
second is an outbox, not a rewrite.

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

**Chosen:** `submitted → extracting → {auto_approved | pending_review |
incomplete | submitted | extraction_failed}`, and `pending_review → in_review →
{approved | rejected | incomplete | pending_review}`.

Notably **there is no `extracted` state**, and `incomplete` is reachable from
both routing and a reviewer.

**Why:** Two rules shaped this.

**Every non-terminal state must have a process that acts on it.** `submitted` →
the worker. `pending_review` → the reviewer. `extracting` and `in_review` → the
reaper, via lease expiry. A state nothing queries is a place claims fall into
and die silently, with no error and no alert.

That rule is why `extracted` was removed. Routing is a pure function of the
extraction result, so extraction and routing commit in the same transaction —
persisting the claim in between would create exactly such a state.

`extracting → submitted` on lease expiry is the machine equivalent of a
reviewer walking away. A worker that crashes mid-call abandons its claim the
same way a human does; it just does it by dying instead of going to lunch.

**`incomplete` exists because the dataset forced it.** A mandatory field that is
genuinely blank on the form is not an extraction failure — no human reading it
more carefully will produce the value. That claim goes back to the claimant,
which is a different outcome from "the model misread it" and therefore a
different state.

**Revisit when:** a second form type arrives with a different lifecycle, or an
outcome appears that is neither approved, rejected nor incomplete.

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

**Chosen:** `SELECT ... FOR UPDATE SKIP LOCKED`, with the `SELECT` and the
`UPDATE` inside one transaction, plus a lease (`locked_by`,
`lease_expires_at`).

**Still unresolved: who wins when a lease expires mid-edit.** See below.

**Why:** Three things make it correct, and each is easy to get wrong.

1. **One transaction.** The row lock lives for the life of the transaction, not
   the statement. Split the `SELECT` and `UPDATE` into two transactions and two
   workers take the same claim — the code looks almost identical and is wrong.
2. **`SKIP LOCKED`, not plain `FOR UPDATE`.** Without it, worker B *blocks*
   until A commits, so three workers behave exactly like one. This is what turns
   "start more processes" into "more work done" — without it, scaling does
   nothing.
3. **A lease.** A crashed worker leaves the claim recoverable rather than
   stranded in a state nothing queries.

Rejected: an application-level mutex (works on one process, fails on two);
optimistic `UPDATE ... WHERE status = 'pending'` with retry (correct, but a
retry loop under contention where the database already has the primitive).

**Open — the lost update.** `complete_review` currently issues an
unconditional `UPDATE ... WHERE id = %s`. A reviewer whose lease expired can
therefore overwrite whoever picked the claim up afterwards, silently. The fix is
a conditional update — `WHERE id = %s AND locked_by = %s AND status =
'in_review'` — and a rowcount check, so losing the lease is reported rather than
discarded. The policy question underneath it is mine: is the second reviewer's
work discarded, merged, or is the first reviewer warned before they start?

**Revisit when:** the lost update is fixed, and again if reviewers ever need to
hold a claim longer than one sitting.

---

## D-004 — How human corrections are recorded

**Status:** OPEN

- **Update the extracted value in place** — simple, and destroys the signal
- **Append-only event log** — every model output and every human edit is a row
- **Both** — event log is the source of truth, a projection holds current values

What questions do I want to answer later? "How often is the model wrong on
field X?" "Did accuracy improve after the prompt change?" A schema that can't
answer those has thrown away the most valuable data in the system.

**Chosen:** Both. `claims.extracted` (jsonb) holds current values;
`field_events` is an append-only log that is never updated and never deleted.
The model's answer and the human's correction are both rows in it.

**Why:** Overwriting the extracted value in place destroys the single most
valuable thing the system produces — **where, and how often, the model is
wrong.** Those rows answer "how often is the model wrong on this field", "did
accuracy improve after the prompt change", and "which fields never clear the
threshold". A schema that cannot answer those has thrown away its own training
and evaluation data.

They are also the only data in the entire system that cannot be regenerated.
Everything else — the extracted values, the states — is derived from files in
git and can be rebuilt in thirty seconds. Human judgment cannot. That makes
`field_events` the only table worth backing up.

**Revisit when:** the events table grows large enough that queries against it
slow down; at that point it wants partitioning by month, not deletion.

---

## D-005 — Database access layer

**Status:** OPEN

- **Raw SQL (`psycopg` 3)** — every query visible; more boilerplate
- **SQLAlchemy Core** — composable SQL, still explicit
- **SQLAlchemy ORM** — fastest to write; hides exactly the things I'm here to learn

*Recommendation on file: raw SQL.* An ORM is an excellent machine for not
learning databases, and databases are goal #2. Costs me row→dict mapping by hand.

**Chosen:** Raw SQL through `psycopg` 3. No ORM.

**Why:** Databases are the second thing on my list of what I want to learn,
and an ORM is an excellent machine for not learning databases.

More specifically: the correctness of this project lives in *exactly when a
transaction begins and ends*, and SQLAlchemy's Session — autoflush, identity
map, expire-on-commit — puts a layer of indirection precisely there. When two
workers take the same claim, I want to be debugging eight lines of SQL, not the
abstraction over them. `.with_for_update(skip_locked=True)` exists, but the
generated SQL is hidden unless you go looking.

The cost is real: row-to-dict mapping by hand, and no compile-time check that a
query matches the schema. **Revised once, in part** — see below.

**Revised (2026-09-02):** the drift problem is real — `001_initial.sql`
declares the columns, the repository names them in strings, and nothing checks
they agree until runtime. The answer is *typed rows without an ORM*: dataclasses
in `domain/`, `psycopg.rows.class_row` to map them, raw SQL for the queries.
That keeps the SQL visible and the transaction boundaries obvious while getting
autocomplete and type checking. Not yet implemented.

**Revisit when:** the project grows past two tables and the same joins start
being written repeatedly.

---

## D-006 — Migrations

**Status:** OPEN

- **Numbered `.sql` files + a ~30-line runner I write** — a `schema_migrations`
  table, applied in order. Teaches what a migration *is*
- **Alembic** — real tool, autogenerate, couples to SQLAlchemy
- **`dbmate` / `golang-migrate`** — language-agnostic binary

Real test of whether I understand it: write a *down* migration and actually
roll one back. Most people never do, then find out in production that they can't.

**Chosen:** Numbered `.sql` files in `migrations/`, applied in order by a
~30-line runner, recorded in a `schema_migrations` table. Each migration runs in
its own transaction.

**Why:** A migration is a numbered file and a discipline. Alembic teaches you
Alembic, and its autogenerate misses renames and gets column-type changes wrong,
so every migration needs reviewing by hand anyway.

Per-file transactions rather than per-run: a failure leaves the earlier
migrations applied and you fix that one file, rather than replaying everything.

The consequence that matters in production: **migrations must never run on
application startup.** Ten Cloud Run instances booting means ten concurrent
`CREATE TABLE`s and this runner has no lock. They run as their own job, which
must exit 0 before the new revision deploys.

**Revisit when:** I need a down-migration and discover I cannot roll back —
which is the real test of whether I understood this, and I have not done it
yet.

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

**Chosen:** Per-field confidence against a threshold (0.80), **plus** an
unconditional escalation list for date fields, **plus** any mandatory field that
is blank on the form routing to `incomplete` rather than to a reviewer.

Threshold and escalation list live in `config.yml`, not in code.

**Why:** Dates on these forms are DD/MM/YYYY, so `03/04/2025` is genuinely
ambiguous and a model reading it as March 4th will be *confidently* wrong. That
failure mode is invisible to a confidence threshold, which is why those fields
escalate unconditionally rather than relying on a score.

The threshold itself is a cost decision: a human review is minutes of loaded
salary, and a wrong auto-approval on a disability claim is far more expensive
than that. But 0.80 is currently a number chosen because it looked round, which
is exactly what this file exists to stop.

**The flaw found by running it:** every form has a `date_of_birth`, and that
field is on the escalation list, so **no claim can ever reach `auto_approved`
and the threshold currently decides nothing.** `CONFIDENCE_THRESHOLD` could be
0.1 or 0.99 with identical output. A blanket rule silently disabled the
mechanism sitting next to it.

Unresolved: either narrow the escalation list, or accept that this form family
is human-verified in full and say so — in which case the confidence score is
for reporting, not routing.

**Revisit when:** there is measured per-field accuracy to set the threshold
from. That is the `model-scorecard` project, and until it exists this number is
a guess.

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

**Chosen:** A stub while the queue was built, then a real vision model —
`qwen/qwen3-vl-32b-instruct` through **OpenRouter**, called with the `openai`
SDK. The provider module is named `openai_compatible.py`, not after any vendor,
and base URL, model, DPI and page cap are all `config.yml`.

**Why:** The stub was right for the first four steps. It reads the ground-truth
JSON beside each PDF and corrupts it deterministically — free, instant,
repeatable, and because the correct answer is known you can measure whether
routing sent the right things to a human. Crucially it makes mistakes *on
purpose*: a perfect extractor means nothing ever escalates, and the entire
human-in-the-loop half of the system never executes.

Real OCR was deliberately deferred because it is the part I already know how to
do, and it would have eaten every evening while teaching me nothing new.

**Changed my mind on the provider, twice.** Started with Anthropic, moved to
OpenRouter for model variety, moved to Groq because I had a key — then found
Groq serves **no vision model at all** (14 models, all text or audio) and these
PDFs are scanned images with a **zero-character text layer**, so no text model
could substitute. Back to OpenRouter.

That round trip is the argument for the seam paying off: switching provider
three times was two lines of YAML and one environment variable, because the
module is named for the wire format rather than the vendor.

**Deliberate:** the model's response is normalised against the known field list
rather than trusted. A model that invents, drops or renames a field cannot
corrupt the shape the queue depends on; a missing field becomes confidence 0.0
and goes to a human.

**Unresolved — citations.** Structured output and citations are mutually
exclusive in one call, so a reviewer cannot yet be shown *where on the page* a
value came from. Current answer: show the whole PDF beside the fields. The
better answer is bounding boxes, which is a layout model and a separate
project.

**Revisit when:** measured accuracy exists to compare models on, or the
citation gap starts costing reviewer time.

---

## D-009 — Reviewer interface

**Status:** OPEN

- **CLI** — `next-task` / `submit`, zero UI work
- **HTTP API + curl** — forces me to think about the API contract
- **Minimal web page** — needed eventually if this is a community demo

Note the trap: a UI makes the lease problem *invisible* during development,
because I'll only ever have one browser tab open. The CLI makes it easy to run
two workers at once and watch them race, which is the whole point of D-003.

**Chosen:** Both. A CLI first, then a FastAPI layer and a React UI with
"act as user" and "act as reviewer" modes. The CLI was not replaced.

**Why:** The CLI came first deliberately — it makes it trivial to run two
reviewers at once and watch them race, which is the whole point of D-003. A
browser hides that: one tab, one claim, no visible concurrency.

The web UI was added once the queue was proven, and it earns its place on one
thing: **the source document beside the extracted values.** Checking a field
against the page it came from is the job; reading a value in a table is
guesswork.

Roles are a client-side view switch, not accounts. No login, no session, no user
table — which is honest about what this is. Real authentication is a separate
project.

Notably, adding the browser touched **no domain or application code** — only a
second module in `infrastructure/api/`. That was the layered structure earning
its place rather than being asserted.

**Revisit when:** more than one person uses it, at which point roles stop
being a view switch and become authorisation.

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

**Chosen:** Neither, for now. Structured queries against Postgres —
`status_counts()`, `stuck_claims()`, `field_history()` — and no tracing
platform.

**Why:** The two things that get conflated here are LLM tracing (what went into
the model, what came out, what it cost) and operational metrics (queue depth,
agreement rate, time-to-review, abandoned leases). Langfuse does the first well
and the second only if human verdicts are deliberately pushed back as scores.

The second is what makes this a *loop*, and every question in it is a `SELECT`.
Queue depth, oldest unprocessed item, how often the model is wrong on a given
field — all of it is already in `claims` and `field_events`.

The most valuable piece is the smallest: a query for anything in a non-terminal
state that has not moved in an hour. If it ever returns rows, a component is
down — and *which* status is piling up names which one. `submitted` means no
workers; `extracting` means no reaper.

Self-hosting Langfuse is ClickHouse, Redis and MinIO — an evening spent learning
someone else's infrastructure rather than mine.

**Revisit when:** cost per document matters enough to need per-call
attribution, or there are enough corrections to plot calibration curves — which
is the `model-scorecard` project.

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

- Cloud SQL runs **PostgreSQL 18**, matched by `docker-compose.yml`'s local
  profile. Keeping those equal is what stops works-here-breaks-there.
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

**Why:** Cloud SQL rather than Postgres in a container because backups,
point-in-time restore, failover and patching are somebody's full-time job, and
the managed markup buys all of it for ten to fifteen dollars a month. Running it
myself at this scale would be paying with my evenings to save pennies.

Sandbox tier and single-zone deliberately: high availability doubles the bill
and teaches nothing, and **sizing up would raise `max_connections` and hide the
connection-exhaustion lesson this deployment exists to demonstrate.**

Region chosen for latency, not price. The cheapest region saves about a dollar
over the week and adds ~200ms to every query, which is felt on every command.

Connected from a laptop through the Cloud SQL Auth Proxy with my own ADC
credentials. **No service account key** — the organisation enforces
`iam.disableServiceAccountKeyCreation`, and that policy is correct rather than
an obstacle; downloaded keys never expire and are a leading cause of cloud
breaches. Using the proxy is the alternative the error message points at.

**Revisit when:** the app actually deploys to Cloud Run, at which point
`instances × pool_max ≤ max_connections` stops being arithmetic on paper.

---

## D-012 — Supporting more than one form type

**Status:** OPEN — not needed yet, recorded so the schema does not block it.

One form type today (`metlife-tpd`), so the field list is a constant in
`domain/routing.py` and the extraction schema is a constant in
`domain/form_schema.py`.

Making this general means the form definition becomes data rather than code: a
`form_templates` table, **versioned**, with field definitions as rows — key,
type, required, always-escalate, validation rule — and each claim pinning the
template *version* it was extracted under. Without the version, a claim
extracted in 2026 becomes uninterpretable when the form changes in 2027.

The current `JSONB` column already absorbs varying fields without a migration,
so this is additive rather than a rewrite.

Questions when it matters:

- How is a document's form type identified — filename, human choice, a
  classifier? And what state does an *unrecognised* form go into?
- Do validation rules live as data on the field definition, or as code keyed by
  type?
- What happens to in-flight claims when a template gets a new version?

The elegant part worth noticing: authoring a template from a blank form is
itself a human-in-the-loop problem — a model proposes the field list, a human
approves it. Same queue, same lease, different payload.

**Chosen:**

**Why:**

**Revisit when:** a second form type actually exists.

---

## D-013 — Telling other systems that a claim was approved

**Status:** OPEN — nothing downstream exists yet.

When a claim reaches a terminal state, something outside will eventually need to
know: notify the claimant, export to a claims system, push to a warehouse.

That is the first time this design crosses a system boundary, and it brings back
the problem D-001 avoided. Calling an external API *inside* the approval
transaction means a rollback can un-happen something the outside world already
saw; calling it *after* the commit means a crash in between loses the
notification silently and permanently.

The answer is the **transactional outbox**: write an outbox row in the same
transaction as the approval, and let a relay ship it. Delivery becomes
at-least-once, so the downstream system must be idempotent — the same lesson as
lease expiry, one layer out.

Worth stating plainly, because it is the honest limit of D-001: **not having a
broker is free only while nothing outside needs to react.** The moment something
does, the outbox is the cost of admission.

**Chosen:**

**Why:**

**Revisit when:** anything downstream needs to know a claim was decided.
