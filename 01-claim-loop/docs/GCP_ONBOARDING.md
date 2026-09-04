# GCP onboarding

Everything needed to stand up the database for this project from a fresh Google
Cloud account. Written for the Console, because the one CLI command that appears
is genuinely the safer option and is called out where it happens.

Budget about twenty minutes, most of it waiting for the instance to build.

---

## What you are creating

| Resource | Purpose | Cost |
|---|---|---|
| A project | A container for everything below | free |
| Cloud SQL instance, PostgreSQL 18 | The database | **the only thing that bills** |
| A database inside it | This project's tables | free |
| A database user | What the application connects as | free |
| A budget alert | So nothing surprises you | free |

At the smallest tier, roughly **$0.50 a day**. Nothing else here costs anything.

---

## 1 · Project and billing

Go to **console.cloud.google.com**.

Use the project dropdown in the blue bar to **create a new project**, or select
an existing one. One project can host every learning project you build; see
*Reusing this setup* at the end.

**Billing → Link a billing account.** Cloud SQL will not create without one, even
on free trial credit.

> If you sit under a company organisation, project creation may be restricted.
> One shared project works fine.

## 2 · Enable the API

**Hamburger menu → APIs & Services → Library.** Search **Cloud SQL Admin API**
and click **ENABLE**.

The Cloud SQL page will also offer to enable it when you first visit; either is
fine.

## 3 · Create the instance

**Hamburger menu → Databases → SQL → CREATE INSTANCE → Choose PostgreSQL.**

| Field | Value | Why |
|---|---|---|
| Instance ID | your choice | lower case, hyphens |
| Password | for the `postgres` admin user | **save it**, this is not the account the app uses |
| Database version | **PostgreSQL 18** | must match `docker-compose.yml`'s local profile |
| Cloud SQL edition | **Enterprise** | not Enterprise Plus |
| Preset | **Sandbox** | the cheapest configuration |
| Region | the cheapest one **near you** | see below |
| Zonal availability | **Single zone** | "Multiple zones" is high availability: it doubles the bill and teaches nothing here |

Expand **SHOW CONFIGURATION OPTIONS**:

- **Storage**: SSD, 10 GB. Leave automatic increases on.
- **Connections**: **Public IP** ticked. That does not mean open to the world:
  nothing connects without credentials, and you control who can reach it.

**CREATE INSTANCE**, then wait **five to ten minutes**.

### Choosing a region

US regions (`us-central1`, `us-east1`) are cheapest and carry the always-free
tiers. Everywhere else costs 10–35% more.

But at this size the whole spread is **about a dollar a week**, while latency is
paid on every single query, a dozen round trips per command. **Pick the
cheapest region near you, not the cheapest region.** From South Asia that is
`asia-south1`; from Southeast Asia, `asia-southeast1`; from Australia,
`australia-southeast1`.

Whatever you choose, put everything in the same one. Cross-region traffic is a
silent egress charge and an extra hop.

## 4 · Note the connection name

On the instance overview, find **Connection name**:

```
your-project-id:your-region:your-instance-id
```

There is a copy icon. You need it if you use the proxy.

## 5 · Create the database

Inside the instance → **Databases → CREATE DATABASE**.

Name it `claimloop`. Leave character set and collation alone.

## 6 · Create the application's user

**Users → ADD USER ACCOUNT → Built-in authentication.**

Pick a username and password, and save both.

Keep this separate from `postgres`. The application has no business holding
admin rights on the instance.

> **Avoid `@ : / ? # [ ]` in the password.** They are reserved characters in a
> connection URL and have to be percent-encoded. Letters, digits, `-` and `_`
> save you a debugging session. See *Troubleshooting*.

## 7 · Choose how you connect

Two options. Neither needs a service account key, and many organisations enforce
`iam.disableServiceAccountKeyCreation`, and that policy is correct: downloaded
keys never expire and are a common cause of breaches. **Do not ask an
administrator to disable it.**

### Option A: Authorised networks. No CLI.

Find your public IP (search "what is my IP").

**Connections → Networking → ADD A NETWORK** → name it, enter `YOUR.IP/32` →
**DONE → SAVE**.

Then `DATABASE_URL` points at the instance's **Public IP address** from the
overview page:

```
DATABASE_URL=postgresql://USER:PASSWORD@34.87.x.x:5432/claimloop
```

No proxy, nothing installed. The trade-off is that your IP changes and you will
come back to update it.

### Option B: Cloud SQL Auth Proxy. One command, recommended.

```bash
gcloud auth application-default login
```

A browser opens and you sign in **as yourself**. No service account key is
created, so the org policy is satisfied. This is the alternative Google's own
error message points at.

Your account needs the **Cloud SQL Client** role. If it does not have it:
**IAM & Admin → IAM → GRANT ACCESS →** your email → role **Cloud SQL Client**.

Then:

```bash
docker compose --profile proxy up -d cloudsql-proxy
```

Works from any network, with no IP list to maintain.

## 8 · Configure the project

```bash
cp .env.example .env
```

Fill in:

```
CLOUDSQL_INSTANCE=your-project:your-region:your-instance   # Option B only
DATABASE_URL=postgresql://USER:PASSWORD@cloudsql-proxy:5432/claimloop
LLM_API_KEY=your-key
```

For Option A, replace `cloudsql-proxy:5432` with the public IP and port.

`.env` is gitignored and must stay that way. Parameters (thresholds, model
names, pool sizes) belong in `config.yml`, which is committed.

## 9 · Verify before involving the application

**SQL → your instance → Cloud SQL Studio.** Sign in as the user from step 6,
database `claimloop`, and run:

```sql
SELECT version();
```

If that returns, the instance, database, user and password are all correct, so
anything that fails next is the proxy or the application, not Cloud SQL. Ten
seconds well spent.

Then:

```bash
docker compose run --rm app migrate-up
```

## 10 · A budget alert

**Billing → Budgets & alerts → CREATE BUDGET.** Scope it to the project, set an
amount, done. Two minutes, and it catches whatever you did not think of.

---

## Cost control

The instance bills whether or not you use it. Nothing else here does.

**Stop it between sessions**: SQL → instance → **STOP** at the top. Storage
still bills, roughly 50 cents a week; compute does not. **START** brings it back
in about a minute.

**Delete it when the project is finished**: **DELETE INSTANCE**. It asks you to
type the instance name, which is the point. Take a dump of anything
irreplaceable first:

```bash
docker compose exec db pg_dump ... --data-only -t field_events > corrections.sql
```

For this project that is the human corrections, and nothing else. Everything
in the database was computed from files in the repository.

---

## Troubleshooting

**`password authentication failed`, and the password is definitely right.**
It probably contains a reserved character. `@ : / ? # [ ]` all mean something
in a URL. Percent-encode it, so `@` becomes `%40`, or change the password to
letters, digits, `-` and `_`.

**The proxy cannot find credentials.**
`gcloud auth application-default login` writes to `~/.config/gcloud/` *unless*
`CLOUDSDK_CONFIG` is set, in which case it goes there instead. Find the real
path:

```bash
find ~ -name application_default_credentials.json 2>/dev/null
```

and point `GCP_CREDENTIALS_FILE` in `.env` at it.

**`connection refused` on the public IP.** Your IP is not in the authorised
networks list, or it changed. Re-check step 7A.

**`could not connect to server: No such file or directory`.** You are using a
`/cloudsql/...` socket path without the Cloud SQL connection attached. That is a
Cloud Run problem, not a local one. The instance has to be added under the
service's **Connections** tab, separately from the environment variables.

**The version differs between local and cloud.** Check the version dropdown you
picked against `docker-compose.yml`'s local profile. A mismatch is the classic
works-here-breaks-there, and it is free to avoid.

---

## Reusing this setup for another project

You do not need a second instance. **The instance bills; databases inside it are
free.**

**SQL → your instance → Databases → CREATE DATABASE** for the next project, add
a user for it, and point that project's `DATABASE_URL` at the new database.

Prefix resource names so they stay distinct, and label resources
`project=<name>` so Billing can break costs down per project.

The caveats (a shared connection limit, and one project's load affecting
another) are real, and irrelevant at this scale. In production, separate
instances are the point.
