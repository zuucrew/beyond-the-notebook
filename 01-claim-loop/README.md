# claim-loop

Claim documents arrive, a machine extracts the fields, low-confidence fields
are routed to a human reviewer, and the human's correction is kept as a
first-class signal instead of overwriting the model's answer.

The extraction is deliberately boring. **The queue is the project.**

---

## The idea

Human-in-the-loop is not a UI feature.

> A human is a worker that is **slow, expensive, unreliable, and impossible to
> retry cheaply.** Putting one inside a pipeline turns a request/response call
> into an async queue with a state machine.

Every hard problem here follows from that one sentence: work has to be handed
out without two people getting the same item, a reviewer who walks away must
not strand the claim forever, and finishing a review has to be atomic with the
data it changes.

## What it teaches

- Async queues and producer/consumer, built on Postgres with no broker
- Task claiming without double-assignment (`FOR UPDATE SKIP LOCKED`)
- Leases, abandoned work, and at-least-once delivery with a human consumer
- Storing variable-shaped documents without schema migrations (`JSONB`)
- Append-only audit design — why corrections are events, not updates
- Confidence routing and the cost model behind the threshold
- LLM observability, and closing the loop by attaching human verdicts to traces

---

## Architecture

**There is no message broker.** The database is the queue. A claim's queue
entry and its data are the same row, so completing a review is one transaction
against one store — nothing to keep in sync, nothing to half-fail.

```mermaid
flowchart LR
    DATA[dataset/<br/>PDFs + ground truth] --> SUBMIT[submit<br/>CLI]
    SUBMIT --> DB[(PostgreSQL)]
    WORKER[extraction worker<br/>stub, then VLM] <--> DB
    DB <--> REVIEW[reviewer<br/>CLI]
    REAPER[lease reaper] --> DB
```

Four processes, one store. The extraction worker and the reviewer never talk to
each other — they only ever meet through a row.

## How a claim flows

```mermaid
flowchart TD
    A[claim submitted] --> B[extract fields<br/>+ confidence]
    B --> C{all fields<br/>confident?}
    C -->|yes| D([auto-approved])
    C -->|mandatory field<br/>blank on the form| E([incomplete —<br/>go back to claimant])
    C -->|no| F[pending_review]
    F --> G[reviewer claims<br/>next task]
    G --> H{lease expires<br/>before submit?}
    H -->|yes| F
    H -->|no| I[reviewer corrects fields]
    I --> J([approved])
```

The `incomplete` branch is the one people miss. A field that is **genuinely
blank on the form** is not an extraction problem — a reviewer cannot fix it by
looking harder. That claim needs to go back to the claimant, which is a
different outcome from "the model misread it."

## Claim lifecycle

Every arrow has a trigger. An unlabelled arrow means the transition hasn't been
thought through.

```mermaid
stateDiagram-v2
    [*] --> submitted
    submitted --> extracting: worker claims it
    extracting --> extracted: model returns fields
    extracting --> extraction_failed: retries exhausted

    extracted --> auto_approved: every field above threshold
    extracted --> pending_review: any field below threshold
    extracted --> incomplete: mandatory field blank on form

    pending_review --> in_review: reviewer claims it
    in_review --> pending_review: lease expired
    in_review --> approved: reviewer submits corrections
    in_review --> rejected: reviewer rejects the claim
    in_review --> incomplete: reviewer confirms field is blank

    auto_approved --> [*]
    approved --> [*]
    rejected --> [*]
    incomplete --> [*]
    extraction_failed --> [*]
```

`in_review → pending_review` is at-least-once delivery. A reviewer whose lease
expires mid-edit has their claim handed to someone else, which means two people
can submit corrections for the same claim. That is a real race and the schema
has to say who wins.

---

## Database

Two tables. Field flexibility lives in a `JSONB` column, so **adding a client,
a form type, or a field is never a migration.**

```mermaid
erDiagram
    CLAIMS ||--o{ FIELD_EVENTS : "has history"
    CLAIMS {
        uuid id PK
        text client_id
        text form_code
        text form_version
        text storage_uri
        text status
        timestamptz lease_expires_at
        text reviewer_id
        jsonb extracted
        timestamptz created_at
        timestamptz updated_at
    }
    FIELD_EVENTS {
        bigint id PK
        uuid claim_id FK
        text field_key
        text event_type
        text old_value
        text new_value
        float confidence
        text actor
        timestamptz created_at
    }
```

### Why this shape

**Typed columns for what the queue needs.** `status`, `lease_expires_at`,
`reviewer_id` and the timestamps never vary between clients and are queried on
every claim operation, so they are real indexed columns.

**`JSONB` for what varies.** A claim's extracted fields:

```json
{
  "member_number":      { "value": "MP-5531208",   "confidence": 0.97 },
  "date_of_disability": { "value": "18/03/2025",   "confidence": 0.62 },
  "diagnosis":          { "value": "Multiple sclerosis, relapsing-remitting",
                          "confidence": 0.88 }
}
```

A different client with a forty-field form writes different JSON. **The table
never changes.** `JSONB` is binary and indexable, so this still works:

```sql
SELECT id FROM claims
WHERE (extracted -> 'date_of_disability' ->> 'confidence')::float < 0.8;
```

**`field_events` is append-only and never updated.** The model's answer and the
human's correction are both rows. Overwriting `extracted` in place would destroy
the single most valuable signal the system produces — how often, and where, the
model is wrong.

### Indexes

| Index | Why |
|---|---|
| `claims (created_at) WHERE status = 'pending_review'` | Partial. Stops the claiming query becoming a sequential scan as terminal claims accumulate |
| `claims (lease_expires_at) WHERE status = 'in_review'` | The reaper's scan |
| `field_events (claim_id)` | Loading one claim's history |
| `claims (storage_uri)` unique | Idempotent submit — same file, one claim |
| GIN on `claims (extracted)` | Only when a real containment query needs it |

---

## Transaction boundaries

This is where correctness lives.

**Claiming a task — one transaction.**

```sql
BEGIN;
  SELECT id FROM claims
  WHERE status = 'pending_review'
  ORDER BY created_at
  LIMIT 1
  FOR UPDATE SKIP LOCKED;

  UPDATE claims
  SET status = 'in_review',
      reviewer_id = $1,
      lease_expires_at = now() + interval '15 minutes'
  WHERE id = $2;
COMMIT;
```

The row lock lives for the life of the **transaction**, not the statement. Split
this into a select, a commit, and a separate update and two reviewers will get
the same claim — the code looks almost identical and is wrong.

`SKIP LOCKED` is what makes reviewer B get a *different* row instead of blocking
until reviewer A finishes.

**Completing a review — one transaction.** Insert the correction events, update
`extracted`, set the terminal status, clear the lease. One store, so it is
atomic by construction. This is the entire argument for not using a broker.

**Reaping expired leases — one statement.** Rows where `status = 'in_review'`
and `lease_expires_at < now()` go back to `pending_review`.

### See it for yourself

Two `psql` sessions, five minutes, before writing any application code:

- **A:** `BEGIN;` then the claiming `SELECT`. Don't commit.
- **B:** run the same query → gets a **different** row.
- **B:** drop `SKIP LOCKED` and rerun → **blocks**.
- **A:** `ROLLBACK;` → B immediately returns A's row.

---

## Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.12+, `uv` |
| Database | PostgreSQL 16, in Docker |
| Driver | `psycopg[binary,pool]` — psycopg 3, raw SQL, no ORM |
| Migrations | numbered `.sql` in `migrations/`, applied by a runner in `src/` |
| Queue | the `claims` table |
| CLI | `typer` + `rich` |
| Tests | `pytest` + `testcontainers[postgres]` |
| Extraction (inc. 5) | `openai` SDK against Groq — OpenAI-compatible, Qwen VL |
| Tracing (inc. 6) | `langfuse`, Cloud free tier |
| Deploy (inc. 10) | Cloud Run + Cloud SQL + Secret Manager |

**Not used:** Redis · Celery/RQ · any ORM · Alembic · Kafka · Kubernetes · CI.
Each is excluded for a reason recorded in `DECISIONS.md`, not by oversight.

---

## Running it

**Config** — `.env`, gitignored, never committed:

```
GROQ_API_KEY=...
DATABASE_URL=postgresql://claim:claim@localhost:5432/claimloop
```

**Start Postgres:**

```bash
docker run -d --name claim-loop-db -e POSTGRES_USER=claim -e POSTGRES_PASSWORD=claim -e POSTGRES_DB=claimloop -p 5432:5432 postgres:16
```

**Install:**

```bash
uv add "psycopg[binary,pool]" typer rich
```

```bash
uv add --dev pytest "testcontainers[postgres]"
```

**Open a psql shell:**

```bash
docker exec -it claim-loop-db psql -U claim -d claimloop
```

---

## Build plan

Each increment adds exactly **one** concept, so every commit has a lesson
attached. Commits are never squashed.

| # | Adds | Concept |
|---|---|---|
| 0 | `DECISIONS.md` filled in before any code | — |
| 1 | Schema + state machine, single reviewer, happy path | schema design, transactions |
| 2 | Confidence routing — auto-approve vs escalate | the cost model behind the threshold |
| 3 | **Concurrent claiming with `SKIP LOCKED`, two workers racing** | row locking ← the real lesson |
| 4 | Lease expiry + reaper | at-least-once, crash recovery |
| 5 | Real extraction — Qwen VL via Groq, replacing the stub | LLM integration behind a stable seam |
| 6 | Langfuse trace on extraction, human verdict as a score | closing the feedback loop |
| 7 | Queue depth, agreement rate, review latency | operational observability |
| 8 | Dockerfile + compose | **L2** — containers, layers, multi-stage |
| 9 | Idempotent submit — same file twice is one claim | idempotency |
| 10 | Deploy to Cloud Run + Cloud SQL | connection pooling, cost modelling |

### The v0.1 stub

Increments 1–4 do **not** read a PDF. The stub reads the ground-truth JSON in
`dataset/`, applies controlled corruption — drop a field, mangle a value,
assign a confidence — and emits that.

Deterministic, free, instant, and because the correct answer is known you can
actually measure whether routing sent the right things to a human. The 18 PDFs
sit unused until increment 5. If you open a PDF library this week, that's drift.

---

## Repo layout

```
01-claim-loop/
├── README.md       this file
├── DECISIONS.md    what was considered, chosen, why, and what changed my mind
├── LIMITS.md       what breaks at scale, and what I'd do about it
├── dataset/        18 synthetic claim PDFs + ground-truth JSON
├── migrations/     numbered .sql, applied in order
└── src/
```

## Still open

Recorded in `DECISIONS.md`, and worth settling as you build rather than up front:

- **D-003** — when a lease expires mid-edit and two reviewers submit corrections
  for the same claim, who wins?
- **D-007** — where the confidence threshold sits, and the arithmetic behind it
- **D-008** — structured output and citations are mutually exclusive, so how
  does a reviewer see *where* on the page a value came from?
- **D-012** — how a document's form type is identified, and what happens to an
  unrecognised one
