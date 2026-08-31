# Run

Every command for this project, in one place. Local first, GCP at the bottom.

> `gcloud` flags drift between releases. The shapes here are correct as written,
> but check `gcloud <group> <command> --help` before pasting anything that
> creates a billable resource.

---

## Local — Docker

The default. Postgres and the worker both in containers.

Start the database:

```bash
docker compose up -d db
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

Every recorded event for one claim — the model's answer and the human's:

```bash
docker compose run --rm app history <claim-id>
```

A psql shell:

```bash
docker compose exec db psql -U claim -d claimloop
```

Stop, keeping the data:

```bash
docker compose down
```

Stop and **destroy the database volume**:

```bash
docker compose down -v
```

Rebuild after a code change:

```bash
docker compose build app
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
echo 'DATABASE_URL=postgresql:///claimloop' >> .env
```

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

Increment 10. Scoped as a one-week run and then deleted; see `ESTIMATE.md`.

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

`--max-instances` caps the connection arithmetic: instances x `DB_POOL_MAX` must
stay under the database's `max_connections`, which is roughly 25-50 on this tier.

```bash
gcloud run deploy claim-loop-api --source . --region=$REGION --max-instances=10 --set-cloudsql-instances=$PROJECT:$REGION:$INSTANCE --set-secrets=DATABASE_URL=claim-loop-db-url:latest --set-env-vars=DB_POOL_MAX=2
```

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
it breaks. That failure is the entire reason this increment exists.

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
gcloud run services delete claim-loop-api --region=$REGION
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
