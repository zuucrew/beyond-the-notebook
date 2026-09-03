# Run

Every command for this project, in one place. Local first, GCP at the bottom.

> `gcloud` flags drift between releases. The shapes here are correct as written,
> but check `gcloud <group> <command> --help` before pasting anything that
> creates a billable resource.

---

## Setting up Cloud SQL — entirely in the Console

No CLI. Console labels shift between releases; the navigation paths are stable.

### 1 · Project and billing

Go to **console.cloud.google.com**. Use the project dropdown in the blue bar at
the top to create or select a project.

**Billing → Link a billing account.** Cloud SQL will not create without it, even
on free credit.

### 2 · Open Cloud SQL

Hamburger menu, top left → scroll to **Databases → SQL**.

Click **CREATE INSTANCE**, then **Choose PostgreSQL**.

If a panel appears asking to enable the Compute Engine or Cloud SQL Admin API,
click **ENABLE API** and wait about thirty seconds.

### 3 · Configure the instance

| Field | Value | Why |
|---|---|---|
| Instance ID | `claim-loop-db` | |
| Password | set one for the `postgres` user | **Save it now.** This is the admin account, not the one the app uses |
| Database version | **PostgreSQL 18** | must match the local profile, or you get works-here-breaks-there |
| Cloud SQL edition | **Enterprise** | not Enterprise Plus |
| Preset | **Sandbox** | the cheapest configuration |
| Region | `australia-southeast1` | Sydney. Keep everything in one region |
| Zonal availability | **Single zone** | "Multiple zones" is HA — it doubles the bill and teaches nothing here |

Expand **SHOW CONFIGURATION OPTIONS** and check two things:

- **Storage** — SSD, **10 GB**. Leave automatic storage increases on; it prevents
  an outage and costs nothing until it triggers.
- **Connections** — **Public IP** ticked, Private IP unticked. Public IP does not
  mean open to the internet: nothing can connect without credentials, and the
  proxy authenticates through IAM.

Click **CREATE INSTANCE**. It takes **five to ten minutes.**

### 4 · Copy the connection name

When it finishes, you land on the instance overview. Find **Connection name** —
it looks like:

```
my-project-123:australia-southeast1:claim-loop-db
```

There is a copy icon next to it. You need this twice.

### 5 · Create the database

Left menu inside the instance → **Databases** → **CREATE DATABASE**.

Name it `claimloop`. Leave character set and collation alone. **CREATE.**

### 6 · Create the application's user

Left menu → **Users** → **ADD USER ACCOUNT**.

- **Built-in authentication**
- Username `claim`
- Set a password and save it

**ADD.**

This is the account the application uses. Keep it separate from `postgres` — the
app has no business holding admin rights.

### 7 · Choose how you connect

Many organisations enforce `iam.disableServiceAccountKeyCreation`, so a
downloaded key file is not an option — and that is a good policy, not an
obstacle. Leaked service account keys are one of the most common causes of cloud
breaches. **Do not ask an admin to disable it.**

Two alternatives. Both are fine for this project.

#### Option A — Authorised networks. No CLI, no keys.

Find your public IP: search "what is my IP", or visit `ifconfig.me`.

**SQL → your instance → Connections → Networking → ADD A NETWORK.**

- Name: `my-laptop`
- Network: `YOUR.IP.ADDRESS/32`
- **DONE**, then **SAVE**

`DATABASE_URL` then points at the instance's **Public IP address**, shown on the
overview page:

```
DATABASE_URL=postgresql://claim:PASSWORD@34.87.x.x:5432/claimloop
```

No proxy service, no credentials file, nothing to install.

The trade: your home IP changes, and you will have to come back and update it.
The instance is reachable from that IP over the internet — still password
protected and TLS encrypted, but reachable. Acceptable for synthetic data over a
week; **not** what the TPD design permits, since §2.4 requires no public
data-plane access at all.

#### Option B — The Auth Proxy with your own identity. One CLI command.

```bash
gcloud auth application-default login
```

A browser opens, you log in as yourself, and credentials are written to
`~/.config/gcloud/application_default_credentials.json`. **No service account
key is created**, so the org policy is satisfied — this is precisely the "more
secure alternative" the error message points at.

Your user needs the **Cloud SQL Client** role. If it does not have it, from the
admin account: **IAM & Admin → IAM → Grant Access →** your working email →
role **Cloud SQL Client**.

Then:

```bash
docker compose --profile proxy up -d cloudsql-proxy
```

and `DATABASE_URL` uses the proxy hostname:

```
DATABASE_URL=postgresql://claim:PASSWORD@cloudsql-proxy:5432/claimloop
```

Works from any network, no IP to maintain, nothing on disk that is worth
stealing.

**Take Option B if you have gcloud installed.** Take Option A if you genuinely
want zero CLI.

### 8 · Write .env

```bash
cp .env.example .env
```

Fill in three lines:

```
# Option A -- authorised networks, straight at the public IP:
DATABASE_URL=postgresql://claim:THE_PASSWORD@34.87.x.x:5432/claimloop

# Option B -- through the proxy:
CLOUDSQL_INSTANCE=my-project-123:us-central1:claim-loop-db
DATABASE_URL=postgresql://claim:THE_PASSWORD@cloudsql-proxy:5432/claimloop

LLM_API_KEY=...
```

### 9 · Check it before touching the app

**SQL → your instance → Cloud SQL Studio** in the left menu. Sign in as `claim`
with the password from step 6, database `claimloop`, and run:

```sql
SELECT version();
```

If that returns, the database, the user and the password are all correct — and
anything that fails next is the proxy or the app, not Cloud SQL.

### 10 · Stop it when you are not using it

**SQL → instance → STOP** at the top of the overview page. Storage still bills,
about 50 cents a week; compute does not. **START** brings it back in a minute.

**DELETE INSTANCE** when the project is finished. It asks you to type the
instance name, which is the point.

---

## Local — running against Cloud SQL

Start the proxy:

```bash
docker compose up -d cloudsql-proxy
```

Apply migrations:

```bash
docker compose run --rm app migrate-up
```

Queue all 18 documents from `dataset/`:

```bash
docker compose run --rm app submit
```

Extract and route everything, then exit:

```bash
docker compose run --rm app work --once
```

Where every claim is:

```bash
docker compose run --rm app status
```

Review the next claim waiting for a human:

```bash
docker compose run --rm app review
```

Return abandoned work to its queue:

```bash
docker compose run --rm app reap
```

Every recorded event for one claim:

```bash
docker compose run --rm app history <claim-id>
```

A psql shell, through the proxy:

```bash
psql "postgresql://claim@localhost:5432/claimloop"
```

Or in the browser: **SQL → your instance → Cloud SQL Studio**.

Rebuild after a code change:

```bash
docker compose build app
```

---

## Local — offline, throwaway Postgres

For working without a network, or for wiping the database and starting again.
Runs on port 5433 so it cannot collide with the proxy.

```bash
docker compose --profile local up -d db
```

```bash
DATABASE_URL=postgresql://claim:claim@db:5432/claimloop docker compose run --rm app migrate-up
```

Destroy it:

```bash
docker compose --profile local down -v
```

---

## Local — without Docker

Postgres natively, if you would rather see the database directly.

```bash
brew install postgresql@16
```

```bash
brew services start postgresql@16
```

```bash
createdb claimloop
```

```bash
cp .env.example .env   # then fill in LLM_API_KEY
```

Parameters — model, thresholds, pool sizes — are in `config.yml`, not `.env`.

```bash
uv sync
```

```bash
uv run claim-loop migrate-up
```

Every `docker compose run --rm app <cmd>` above becomes `uv run claim-loop <cmd>`.

---

## The experiments

These are the point of the project. Run them before trusting anything.

### Watch `SKIP LOCKED` hand out different rows

Two `psql` sessions side by side.

**Session A** — do not commit:

```sql
BEGIN;
SELECT id FROM claims WHERE status='pending_review' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED;
```

**Session B** — same query. You get a *different* row. Now drop `SKIP LOCKED`
and rerun: B **blocks**. Then `ROLLBACK` in A and watch B return A's row.

### Watch workers race

```bash
docker compose up --scale app=3 app
```

Three workers, one queue, no collisions and no configuration.

### Watch the reaper reclaim abandoned work

```bash
LEASE_SECONDS=10 docker compose run --rm app review
```

Sit on the prompt for fifteen seconds, then in another terminal:

```bash
docker compose run --rm app reap
```

Now submit the review you were holding. It succeeds — and overwrites whoever
picked the claim up after you. That is D-003, and it is still unfixed.

### Break it deliberately

Remove `SKIP LOCKED` from `claims_repository.claim_next_for_extraction`, then
split the `SELECT` and `UPDATE` into separate transactions. Run three workers
again and watch double-assignment happen.

A test that cannot fail against the broken version is not testing anything.

---

## GCP — one-time setup

Scoped as a one-week run and then deleted; see `ESTIMATE.md`.

```bash
export PROJECT=your-project-id REGION=australia-southeast1 INSTANCE=claim-loop-db
```

```bash
gcloud config set project $PROJECT
```

```bash
gcloud services enable sqladmin.googleapis.com run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com
```

Smallest shared-core tier, HA off — deliberately, so the connection limit stays
low enough to teach you something:

```bash
gcloud sql instances create $INSTANCE --database-version=POSTGRES_16 --tier=db-f1-micro --region=$REGION --storage-size=10GB --storage-type=SSD
```

```bash
gcloud sql databases create claimloop --instance=$INSTANCE
```

```bash
gcloud sql users create claim --instance=$INSTANCE --prompt-for-password
```

Store the connection string rather than the password. With the Cloud SQL
connector the host is a unix socket, not an IP:

```bash
printf 'postgresql://claim:YOUR_PASSWORD@/claimloop?host=/cloudsql/%s:%s:%s' "$PROJECT" "$REGION" "$INSTANCE" | gcloud secrets create claim-loop-db-url --data-file=-
```

Documents:

```bash
gcloud storage buckets create gs://$PROJECT-claim-loop-docs --location=$REGION --uniform-bucket-level-access
```

A budget alert, because it takes two minutes:

```bash
gcloud billing budgets create --billing-account=YOUR_BILLING_ACCOUNT --display-name=claim-loop --budget-amount=50USD
```

---

## GCP — deploy

Migrations run as their own job and must finish before the app deploys. Never on
app startup: ten instances booting means ten concurrent `CREATE TABLE`s, and the
migration runner has no lock.

```bash
gcloud run jobs deploy claim-loop-migrate --source . --region=$REGION --args=migrate-up --set-cloudsql-instances=$PROJECT:$REGION:$INSTANCE --set-secrets=DATABASE_URL=claim-loop-db-url:latest
```

```bash
gcloud run jobs execute claim-loop-migrate --region=$REGION --wait
```

The worker — a Job, not a Service. A Service throttles CPU between requests, so
a polling loop starves:

```bash
gcloud run jobs deploy claim-loop-worker --source . --region=$REGION --args=work,--once --set-cloudsql-instances=$PROJECT:$REGION:$INSTANCE --set-secrets=DATABASE_URL=claim-loop-db-url:latest --set-env-vars=DB_POOL_MAX=2
```

Drain the queue every two minutes. Overlapping runs are safe — `SKIP LOCKED`
means a second run takes different claims:

```bash
gcloud scheduler jobs create http claim-loop-worker-tick --location=$REGION --schedule="*/2 * * * *" --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT/jobs/claim-loop-worker:run" --http-method=POST --oauth-service-account-email=$(gcloud config get-value account)
```

### There is no service to deploy — yet

A Cloud Run **Service** must listen for HTTP on `$PORT`. This project's only
entrypoint is a Typer CLI, so a Service would fail its health check and never
go healthy.

**Deploy Jobs only.** A Service appears when there is a FastAPI layer to put in
it, and then this is the shape:

```bash
# only once an HTTP entrypoint exists
gcloud run deploy claim-loop-api --source . --region=$REGION --max-instances=10 --set-cloudsql-instances=$PROJECT:$REGION:$INSTANCE --set-secrets=DATABASE_URL=claim-loop-db-url:latest --set-env-vars=APP_ENV=production
```

`--max-instances` is what caps the connection arithmetic: instances x
`pool_max` must stay under the database's `max_connections`.

---

## GCP — the same thing in the Console

Everything above except one step can be clicked. Console labels move between
releases; the navigation paths are stable, the button captions less so.

### 1 · Enable the APIs

**APIs & Services → Library** — search and **Enable** each of: Cloud SQL Admin,
Cloud Run Admin, Artifact Registry, Secret Manager, Cloud Build, Cloud Scheduler.

### 2 · Cloud SQL instance

**SQL → Create Instance → PostgreSQL**

| Setting | Value |
|---|---|
| Instance ID | `claim-loop-db` |
| Database version | PostgreSQL 16 |
| Edition | Enterprise |
| Preset | Sandbox — the cheapest shared-core |
| Region | `australia-southeast1` |
| Zonal availability | **Single zone** — "Multiple zones" is HA and doubles the bill |
| Storage | 10 GB SSD |
| Connections | Public IP (default) |

Then inside the instance:

- **Databases → Create Database** → `claimloop`
- **Users → Add User Account** → built-in authentication → user `claim`, set a password

Copy the **connection name** from the instance overview — it looks like
`project:region:claim-loop-db`. You need it in the next step.

### 3 · The connection string as a secret

**Security → Secret Manager → Create Secret**

Name `claim-loop-db-url`, and paste as the value:

```
postgresql://claim:YOUR_PASSWORD@/claimloop?host=/cloudsql/PROJECT:REGION:claim-loop-db
```

No host and port — the Cloud SQL connector mounts a unix socket, so the host is
a filesystem path.

### 4 · Bucket

**Cloud Storage → Buckets → Create.** Region `australia-southeast1`, uniform
bucket-level access on.

### 5 · The step the Console cannot do

**Cloud Run needs a container image, and the Console cannot build one from the
folder on your laptop.** `gcloud run deploy --source .` does that; there is no
button for it.

Two ways round it, both Console-friendly afterwards:

- **Connect the GitHub repo.** Cloud Run → Create Service → *Continuously deploy
  from a repository* → Cloud Build sets up a trigger on push. Entirely clickable,
  and note what it is: continuous deployment, which is more automation than this
  project asked for.
- **Push an image once from your machine**, then deploy it by tag from the
  Console every time after. Needs `gcloud auth configure-docker` once — one CLI
  command, then never again.

### 6 · Cloud Run service — skip this for now

Only relevant once the project has an HTTP entrypoint. A Service must answer on
`$PORT`; the CLI does not. Go to Jobs.


**Cloud Run → Create Service**, pick the image or repository from step 5, then:

- **Region** `australia-southeast1`
- **Containers → Variables & Secrets** — add `APP_ENV` = `production`; add
  `DATABASE_URL` as a **secret reference** to `claim-loop-db-url`, latest version
- **Containers → Connections** (sometimes *Cloud SQL connections*) — add the
  instance. This is what mounts the socket
- **Revision scaling → Maximum instances** — set it. Instances x `pool_max` must
  stay under the database's `max_connections`

### 7 · Jobs

**Cloud Run → Jobs tab → Create Job.** Same image, same secret, same Cloud SQL
connection. The difference is **Arguments**:

| Job | Arguments |
|---|---|
| `claim-loop-migrate` | `migrate-up` |
| `claim-loop-worker` | `work`, `--once` |

Run the migration job once — **Execute**, and wait for it to finish — before
deploying the service.

### 8 · Schedule the worker

**Cloud Scheduler → Create Job.** Frequency `*/2 * * * *`, target **HTTP**, URL:

```
https://REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT/jobs/claim-loop-worker:run
```

Method POST, Auth header **Add OAuth token**, with a service account that has
Cloud Run Invoker.

### 9 · Budget alert

**Billing → Budgets & alerts → Create Budget.** Scope the project, amount $50.

### 10 · Watching it

- **Cloud Run → your service → Logs**
- **Cloud Run → Jobs → executions** for worker runs
- **SQL → instance → Cloud SQL Studio** for a query editor in the browser
- **SQL → instance → Monitoring** — active connections is the graph to watch when
  you push load and the pool arithmetic breaks

### 11 · Teardown

Delete in this order, each from its own Console page: Cloud Scheduler job →
Cloud Run jobs → Cloud Run service → **SQL instance** → bucket.

The SQL instance is the only one that costs money while idle. Deleting it needs
you to type the instance name to confirm, which is the point.

---

## GCP — operate

A psql shell against Cloud SQL:

```bash
gcloud sql connect $INSTANCE --user=claim --database=claimloop
```

Worker logs:

```bash
gcloud run jobs executions list --job=claim-loop-worker --region=$REGION
```

```bash
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=claim-loop-worker' --limit=50
```

Force a run rather than waiting for the schedule:

```bash
gcloud run jobs execute claim-loop-worker --region=$REGION --wait
```

Prove the connection limit is real — raise `--max-instances` and push load until
it breaks. That failure is the entire reason for deploying at all.

---

## GCP — teardown

Take the corrections first. They are the only data in the system that cannot be
regenerated:

```bash
docker compose exec db pg_dump -U claim -d claimloop --data-only -t field_events > corrections.sql
```

Then delete the thing that bills:

```bash
gcloud sql instances delete $INSTANCE
```

```bash
gcloud run jobs delete claim-loop-worker --region=$REGION
```

```bash
gcloud run jobs delete claim-loop-migrate --region=$REGION
```

```bash
gcloud scheduler jobs delete claim-loop-worker-tick --location=$REGION
```

```bash
gcloud storage rm --recursive gs://$PROJECT-claim-loop-docs
```

Pause instead of deleting, if you are coming back tomorrow. You keep paying for
storage — about 50 cents a week — and nothing else:

```bash
gcloud sql instances patch $INSTANCE --activation-policy NEVER
```

```bash
gcloud sql instances patch $INSTANCE --activation-policy ALWAYS
```
