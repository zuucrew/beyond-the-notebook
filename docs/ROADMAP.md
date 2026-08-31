# Roadmap

Seventeen projects, ordered low to high complexity, drawn from five sources and
rotated so no two consecutive projects come from the same one.

**Sources**

| Tag | What it is |
|---|---|
| **TPD** | *[Solution Design] TPD Claims Automation* — the real client build. Section numbers refer to it |
| **Graphs** | The Neural Maze — *Building Agent Memory with Knowledge Graphs* |
| **Ambient** | The Neural Maze — *Building a Local Ambient Agent* |
| **OCR/Infra** | The Neural Maze — *SLM OCR Course*, *Modern OCR Guide*, *Kubernetes for Production AI*, *LLM Inference*, *Rust for Production AI*, `neural-maze/production-ocr-course` |
| **LinkedIn** | A credit-application OCR system taken from notebook to production — status model, Celery/Redis jobs, PDF overlay review, metadata filtering, swappable components |

**The rule every project follows:** it is a real system with a name, a user who
asks for it, and a guarantee that can fail — not a pattern with a demo attached.
If it cannot fail, it is not a system.

---

## The list

| # | Name | What it does | Source | Design | New tools | Depth |
|---|---|---|---|---|---|---|
| 01 | **claim-loop** | Low-confidence extractions go to a human; the correction is kept as signal | **TPD** §7.12, §8 | Moderate | Postgres | L2 |
| 02 | **credit-intake** | Loan officers upload credit-application PDFs; OCR and an LLM extract the fields; the officer verifies them on a **PDF overlay** with confidence boxes | **LinkedIn** | Moderate | FastAPI, Celery, Redis, real OCR, blob storage, a frontend | L2 |
| 03 | **model-scorecard** | Reports extraction accuracy field by field, and sets each confidence threshold | **OCR/Infra** — SLM OCR | Simple | pandas *(your ground)* | L1 |
| 04 | **audit-trail** | Records everything that happened to a claim, and proves the record was not edited | **TPD** §13, §17.7 | Simple | Postgres roles & grants | L1 |
| 05 | **doc-watcher** | Watches a folder and triages documents the moment they land | **Ambient** | Simple | file/SFTP events | L1 |
| 06 | **approval-workflow** | Who may do what, and which actions need a second person | **TPD** §3, §8.4 | Moderate | OIDC, JWT, RBAC | L2 |
| 07 | **member-history** | One member across claims, policies, funds and employers — spots duplicate and concurrent claims | **Graphs** | Moderate | graph database | L2 |
| 08 | **follow-up-scheduler** | Chases insurers and members for months, surviving outages and deploys | **TPD** §7.4 | Moderate–hard | durable timers | L2 |
| 09 | **document-redactor** | Strips tax file numbers, Medicare numbers and bank details before anything leaves | **OCR/Infra** — Rust | Simple | **Rust** | L2 |
| 10 | **insurer-gateway** | One submission call — four insurers, three transports, same evidence and retries | **TPD** §11.2 | Hard | Playwright, SMTP, SFTP | L2 |
| 11 | **letter-reader** | Reads insurer decision letters as they arrive and proposes the next step for a human | **Ambient** | Moderate | Graph API, LLM | L2 |
| 12 | **task-dispatcher** | Sends work to external systems exactly once, and proves it | **TPD** §1.3, §2.3 | Hard | message broker, DLQs | L3 |
| 13 | **evidence-tracker** | Traces every statement in a trustee pack to its source, and surfaces contradictions | **Graphs** | Hard | graph traversal | L3 |
| 14 | **eligibility-engine** | Versioned rules — replay last year's claims against a new version before shipping it | **TPD** §7.9, §9 | **Very hard** | almost none | L2 |
| 15 | **document-extractor** | Reads a scanned pack and shows exactly where on the page each value came from | **OCR/Infra** — Modern OCR | Hard | layout model, VLM serving | L3 |
| 16 | **bulk-processor** | 500 documents land at once — latency degrades, nothing is lost | **OCR/Infra** — Kubernetes | Moderate | **Kubernetes**, KEDA | L4 |
| 17 | **onshore-ai** | Runs extraction on your own hardware, in-country, because the data cannot legally leave | **OCR/Infra** — LLM Inference | Simple | **vLLM, GPU, quantisation** | L4 |

**Rotation:** TPD → LinkedIn → OCR → TPD → Ambient → TPD → Graphs → TPD → Rust
→ TPD → Ambient → TPD → Graphs → TPD → OCR → K8s → Inference. Every second
project is the client design; the rest cycle through the other four sources.

---

## Detail

### 02 · credit-intake
> *"Five thousand credit applications a year. A loan officer should verify one in minutes, not hours."*

Upload a PDF, preprocess it, OCR it, structure the text with an LLM, and put the
result in front of a loan officer as an **overlay on the original page** — each
extracted field boxed where it was found, with its confidence.

**It overlaps claim-loop heavily, and that is the point.** Of the five design
decisions in the source post, three are already built in 01: the formal state
machine, async jobs with independent retry, and human-in-the-loop by design.
Metadata-driven filtering is 01's routing plus the template question in D-012,
and modular swappable components is the layered structure already adopted.

So this project earns its place on what 01 deliberately does **not** have:

- **A real OCR pipeline.** 01 stubs extraction. This does preprocessing, OCR,
  text cleaning and LLM structuring for real.
- **The PDF overlay.** 01's reviewer is a CLI table. Showing the field boxed on
  the page it came from is the single biggest lever on review speed, and it is
  what TPD §8 verification screens need.
- **Object storage and a web frontend.** 01 has neither.
- **Celery and Redis** — deliberately, because 01 rejected them.

That last one is the reason to build it rather than extend 01. Project 01 argues
at length that a broker splits the queue state from the claim state and costs a
shared transaction. This builds the same shaped system the other way, so the
comparison becomes something measured rather than something taken on trust.
Write both sides up in its DECISIONS.md; the changed-my-mind entry is the
deliverable either way.

**Scope warning:** FastAPI, Celery, Redis, real OCR, blob storage and a frontend
is six new tools at once. It sits at 02 for domain continuity, not because it is
the second easiest thing here. Consider splitting it — pipeline first, overlay
second — if it stalls.

**Absorbs:** most of 15 · document-extractor, if built in full.

### 03 · model-scorecard
> *"Can we auto-approve date of birth? Prove it."*

Field-level precision and recall against a golden set, plus calibration curves
relating stated confidence to observed accuracy. Produces the per-field
thresholds that §7.12 depends on — you cannot pick a threshold without this.

Consumes **claim-loop**'s corrections: every human correction is a labelled
example, which is the loop TPD §7.14 describes as *"refreshed quarterly with
verified live corrections."*

### 04 · audit-trail
> *"AFCA asks what happened on claim 4471 on 3 March. Reconstruct it, and prove nobody edited the record."*

Append-only history, INSERT-only at the database grant level, hash-chained so
tampering is detectable. Teaches Postgres roles and grants, immutability, and
reconstructing state from events.

### 05 · doc-watcher
> *"A medical certificate just landed in the SFTP drop. What is it, is it legible, and whose claim is it?"*

The ambient pattern with nothing else attached: no chat, no prompt, no user —
it reacts to arrival. Cheap deterministic gates (type, legibility, certification)
before anything expensive runs. TPD BE-04 requires exactly this.

### 06 · approval-workflow
> *"Nobody releases a payment alone. Nobody sends a decline without a senior approving."*

Roles from an identity provider, a permission matrix, and four-eyes on the
actions that matter. Separation of duties enforced structurally rather than by
policy document.

### 07 · member-history
> *"Have we seen this member before, and is this a new claim or the same event twice?"*

A member across claims, policies, funds and employers. Entity resolution over a
small graph, answering TPD BE-06 — duplicate versus concurrent claims. The
gentler graph project; **evidence-tracker** is the hard one.

### 08 · follow-up-scheduler
> *"Chase the insurer at day 7, 14 and 21. Escalate at 30. The procedural fairness deadline is hard."*

Claims run for months. The interesting question is what happens to a timer that
should have fired while the system was down for three days — fire them all, or
skip? Neither is obviously right, and TPD §2.7 requires timers survive
deployments and restarts.

### 09 · document-redactor
> *"No tax file number ever leaves this building."*

Per-page, CPU-bound, embarrassingly parallel text and image work — the shape
where a compiled language genuinely beats Python, and where a small memory-safe
binary is the right thing to sit in front of an expensive model. TPD §10
requires TFN redaction before a trustee pack goes out.

### 10 · insurer-gateway
> *"Submit to MetLife via their portal, AIA by email, TAL via their platform — same call, same evidence, same retries."*

One submission contract, several transports. TPD §2.5 makes this the thing that
decides whether Phase 2 is a connector addition or a redesign.

### 11 · letter-reader
> *"A decision letter arrived. Read it, tell me the outcome and the deadline, and let a human confirm before anything commits."*

TPD §7.10 — the LLM interprets, the assessor confirms. A procedural fairness
deadline starts ticking the day the letter arrives, so a letter sitting unread
for three days is a real cost. Teaches event-driven triggers, mailbox
idempotency, and extraction into a *proposed state transition* rather than a value.

### 12 · task-dispatcher
> *"Submit claim 4471 to MetLife. The portal timed out. Did it arrive?"*

The transactional outbox: claim mutation, audit entry and outbound task written
in one transaction, dispatched to an idempotent worker. TPD §1.3 and §2.3 rest
entirely on this — get it wrong and the audit trail lies.

The name promises something the internals cannot literally deliver. Explaining
why at-least-once plus idempotency is indistinguishable from exactly-once is the
best DECISIONS.md entry in the whole roadmap.

### 13 · evidence-tracker
> *"Why do we believe the date of disablement is 18 March, and what disagrees with it?"*

Every assertion links to a document, a page and the extraction event that
produced it. TPD §7.14 measures *grounding pass rate — every sentence sourced*,
and BE-03 requires surfacing conflicts across intake, the registry and extracted
forms. Traversal, not a table: the correct use of a graph.

### 14 · eligibility-engine
> *"We're changing the PYS rule. Which of last year's 400 claims would have been decided differently?"*

The hardest thinking in the roadmap and almost no new tools. Versioned rule sets,
in-flight claims pinned to the version they started under, replay against
history, and every divergence individually explained. TPD §7.14 makes it a
go-live gate: unexplained divergence blocks the release.

### 15 · document-extractor
> *"Here's a 40-page scanned pack. Give me the fields, tell me how sure you are, and show me where each one came from."*

Layout model finds the regions, a vision model reads them. The differentiator is
not OCR — it is provenance: a reviewer seeing the actual cropped box beats
reading a value in a table.

### 16 · bulk-processor
> *"Five hundred documents just landed. Don't lose any."*

TPD §2.7: *document bursts degrade latency, never correctness.* Two services with
genuinely different resource profiles, scaled independently on queue depth. The
only condition under which Kubernetes teaches something instead of being ceremony.

### 17 · onshore-ai
> *"The model we need isn't available in Australia East. Run it ourselves."*

TPD AD001 names this as the fallback position. Design is nearly trivial; the
tooling is the whole lesson — serving, batching, KV cache, quantisation and the
GPU economics that decide whether it is cheaper than an API.

---

## The two axes come apart

**eligibility-engine** is the hardest design in the set and needs almost no new
tools. **onshore-ai** is the reverse — trivial design, hardest tooling. The
ordering above blends both. To stretch one axis at a time:

- **Design-first:** 04 → 06 → 08 → 10 → 13 → 14
- **Tools-first:** 02 → 05 → 09 → 11 → 15 → 16 → 17

## One conflict worth knowing

Complexity order and dependency order disagree once. **task-dispatcher** sits at
12, but architecturally it is the spine — `follow-up-scheduler`, `insurer-gateway`
and `letter-reader` all assume a reliable task layer, and in TPD §1.3 *every*
side effect goes through it.

Build those three with direct calls first, watch one lose work when a process
dies, then build the dispatcher. A tool learned before you need it teaches the
wrong reflex.

---

*Supersedes `IDEAS.md`, which holds two earlier sketches. Fold or delete when
this settles.*
