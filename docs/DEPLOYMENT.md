# Deployment guide and release strategy

This is the plan for taking CareCircle from "runs on my laptop" to a hosted, repeatable deployment, and for shipping new
features afterwards without breaking what already works. Everything here matches the code in this repository.

> **Want a public URL with the least work?** Use a managed host: see [DEPLOY_RENDER.md](DEPLOY_RENDER.md) (platform comparison and Render steps; `render.yaml` is ready). This document covers the single-server route and the release strategy that applies to every host.

## 1. Where the project stands

**Ready:** a single container serves the API and the built UI, migrations run on start, the build runs the whole test suite,
health and version are exposed, the database holds all state, and the app degrades gracefully when AI is unavailable.

**Not a drop-in for real patients yet:** the project's standing rule is *fictional data only*. A hosted **demo** is safe
today. Handling real patient data needs the compliance gates in section 9 first.

| Stage | What it is | Status |
|---|---|---|
| **A. Laptop / LAN demo** | `docker compose up` on one machine, HTTP, port 8000 | Works today. The microphone only works on `localhost` (browsers require HTTPS elsewhere). |
| **B. Hosted demo (recommended now)** | One small VM, Docker Compose, HTTPS, backups, repeatable deploys | Implemented in this repo: sections 3 to 6. |
| **C. Real-patient production** | Stage B plus the section 9 gates | Planned, not built. |

**Recommendation:** do Stage B now. It is the smallest step that makes every feature work for any visitor (HTTPS enables the
microphone and secure cookies), is cheap to run, and is the same shape Stage C will use.

## 2. The production shape

```
 Internet ──443──▶ Caddy (TLS, gzip, security headers, 6 MB body limit)
                     │  private "web" network
                     ▼
                  app  (FastAPI + built UI, 1 worker, scheduler inside, health-checked)
                     │  private "internal" network (no internet route)
                     ▼
                  db   (Postgres 16, volume `pgdata`, nothing published)
```

Files: `docker-compose.prod.yml`, `deploy/Caddyfile`, `.env.production.example`, `scripts/deploy.sh`, `scripts/backup.sh`,
`scripts/restore.sh`, `scripts/postdeploy_check.py`.

Why one container and one worker: the scheduler (escalation timers, missed doses, reminders, automatic cover) runs inside
the app and keeps a few counters in memory (login rate limits). One worker is correct. A **database lock** now guarantees only
one instance ever runs the scheduler, so an overlapping deploy cannot send alerts twice.

## 3. Before you start

You need:

- A Linux VM (Ubuntu 22.04 or 24.04 LTS is a good default) with **2 vCPU, 4 GB RAM, 20 GB disk** as a starting point. Voice
  notes are stored in the database (about 100 to 500 KB each), so watch disk if usage grows.
- A domain name with an **A record** pointing at the VM (for example `care.example.org`). Ports **80 and 443** open.
- A GitHub (or other git) access path from the VM to this repository.
- Optional: Groq and Google AI keys for voice notes (the app works without them).

## 4. First deployment, step by step

1. **Prepare the server**

   ```bash
   sudo apt-get update && sudo apt-get -y upgrade
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker "$USER" && newgrp docker
   sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
   ```

   Do not open 5432 or 8000: the database is private and the app is reached only through Caddy.

2. **Get the code**

   ```bash
   git clone git@github.com:Manipal-Hackathon-2026/CodeBlue.git carecircle
   cd carecircle
   ```

3. **Create the secrets file** (never committed; `.env.production` is git-ignored)

   ```bash
   cp .env.production.example .env.production
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # paste as SECRET_KEY
   python3 -c "import secrets; print(secrets.token_urlsafe(24))"   # paste as POSTGRES_PASSWORD
   nano .env.production                                            # set DOMAIN, the two secrets, DEMO_PASSWORD, AI keys
   chmod 600 .env.production
   ```

   For a **hosted demo** leave `DEMO_MODE=true`, `SEED_DEMO=true`, `DEMO_POPULATION=true`. The app refuses to start in
   production with a short secret or without `COOKIE_SECURE=true`.

4. **Deploy**

   ```bash
   bash scripts/deploy.sh
   ```

   It backs up (skipped the first time), builds the image (which runs the whole test suite; a failure stops here and
   leaves anything running untouched), starts the app (migrations run on boot), waits for health, starts HTTPS, and
   verifies the result. If a check fails it rolls back by itself.

5. **Verify** (read-only, safe on production; `deploy.sh` already runs it):

   ```bash
   python3 scripts/postdeploy_check.py --base-url https://care.example.org --expect-prod --wait-scheduler
   ```

6. **Smoke test as people** (optional but worth doing once): sign in as the demo patient on a phone, record a voice note,
   confirm the preview, send it, then watch the alert arrive for the family account.

7. **Switch on backups** (daily, 02:30 server time):

   ```bash
   ( crontab -l 2>/dev/null; echo '30 2 * * * cd $HOME/carecircle && bash scripts/backup.sh >> backups/backup.log 2>&1' ) | crontab -
   ```

   Copy `backups/` off the server regularly (object storage or another machine). A backup that lives only on the
   server it protects is not a backup. **Test a restore once** on a spare machine before you need it.

8. **Monitoring** (15 minutes of work, large payoff): point an uptime monitor at `https://<domain>/api/health` and alert on
   anything other than HTTP 200. The JSON also carries `git_sha` and the scheduler's `last_tick_at`; alert if
   `last_tick_at` is older than five minutes. Read logs with `docker compose -f docker-compose.prod.yml logs -f app`.

## 5. Deploying an update

```bash
cd ~/carecircle
bash scripts/deploy.sh v2026.10.2        # a tag, branch or commit; omit to deploy what is checked out
```

What it does, and why each step is there:

| Step | Purpose | If it fails |
|---|---|---|
| Backup | A restore point taken before anything changes | Stops. Nothing was touched. |
| Build | Runs the full backend and frontend test suites inside the image build | Stops. The running app is untouched. |
| Switch app | Starts the new image; migrations run on boot | Rolls back to the previous image. |
| Wait for health | The container health check must pass | Rolls back. |
| Post-deploy checks | Version, database, headers, sign-in enforced, docs hidden, scheduler alive | Rolls back. |
| Keep images | The three newest images stay for instant rollback | none |

Expect **10 to 30 seconds** where the app restarts. Browsers reconnect by themselves (screens poll). A true zero-downtime swap
is possible later (section 8) but is not worth the complexity at this stage.

### Rolling back by hand

```bash
GIT_SHA=<previous> APP_TAG=<previous> docker compose -f docker-compose.prod.yml --env-file .env.production up -d --no-deps app
```

This is safe **because migrations are additive** (section 7): the previous code runs fine on the newer database. Only restore
the database (`bash scripts/restore.sh backups/<file>.sql.gz --yes`) if data itself was damaged.

## 6. Configuration reference

| Variable | Production value | Note |
|---|---|---|
| `APP_ENV` | `prod` | Enables the guards (secret length, HTTPS cookie) and hides `/docs` and the API schema. |
| `SECRET_KEY` | 48+ random characters | Rotating it signs everyone out. |
| `COOKIE_SECURE` | `true` | Required by the entrypoint in production. |
| `DOMAIN` | your hostname | Caddy gets and renews the certificate. |
| `DEMO_MODE`, `SEED_DEMO`, `DEMO_POPULATION` | `true` for a hosted demo; `false` for real data | With `DEMO_MODE=false` new patients are not marked synthetic and the reset endpoint is closed. |
| `FEATURES` | `voice_notes,insights,reminders` | Allow-list for staged rollout (section 7). `*` enables everything shipped. |
| `RUN_SCHEDULER` | `true` | `false` on an instance that must only serve web traffic. |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, models | optional | See [AI.md](AI.md). `python scripts/ai_check.py` verifies them. |

## 7. Shipping new features after go-live

The goal: every new feature can be merged early, deployed dark, tested on the real server, switched on for everyone in one
setting, and switched off again in seconds, without a redeploy of old behaviour.

### The path of a change

```
feature branch ─▶ pull request + checks (lint, types, tests, build) ─▶ main ─▶ tag vYYYY.MM.N ─▶ staging ─▶ production
```

1. **Branch** from `main`; keep branches short (days, not weeks).
2. **The checks must pass** before merge: `python -m pytest backend/tests -q`, and from `frontend/`: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`. The Docker build runs the same commands, so a failing change cannot be deployed. There is no CI workflow committed; if you add one later, require it on `main` together with one review.
3. **Tag** a release (`git tag v2026.10.2 && git push origin v2026.10.2`). Deploy tags, not whatever happens to be on a branch.
4. **Staging first.** Run a second copy of the stack on another hostname (a second `.env.production` with its own `DOMAIN`,
   `POSTGRES_*`, `DEMO_MODE=true`). Deploy the tag there, run the demo script, then promote the *same tag* to production.
5. **Deploy to production** with `scripts/deploy.sh <tag>`.

### Rules that keep deploys safe

- **Migrations are additive and backward compatible.** Add tables, columns (nullable or with a default) and indexes. Never
  rename or drop a column in the same release that stops using it. Use *expand, then contract*: release N adds the new column
  and writes both; release N+1 reads the new one; release N+2 removes the old. This is what makes rollback safe.
- **Never edit a shipped migration**; add a new one. Every migration here guards itself so it can run on a database created
  by `create_all` as well as an upgraded one. Keep doing that.
- **Ship dark behind a flag.** New user-facing features check `settings.feature("name")` on the server (use
  `Depends(feature_required("name"))` on a router) and the UI reads `features` from `/api/v1/meta`. Merge and deploy with the
  flag off, enable in staging, then production by adding the name to `FEATURES` and restarting the app. Remove the flag once
  the feature has been stable for a release or two. Today's flags: `voice_notes`, `insights`, `reminders`.
- **Frontend and backend ship in one image**, so they never disagree. During the 10 to 30 seconds of a deploy, a browser tab
  still running old JavaScript may call the new API: keep responses backward compatible for one release (add fields, do not
  remove or rename them).
- **New configuration is documented the same day**: add it to `.env.production.example` and the table in section 6.
- **New background work must be safe to run twice.** Use a `dedupe_key` (see `services/notify.py`) or an idempotent
  check; the scheduler lock prevents overlap, but a crash mid-tick can repeat work.
- **Every external dependency needs a fallback or a switch** (the AI chain is the model: timeouts, circuit breaker, the app
  works without it).

### Definition of done for a feature

- [ ] Unit and API tests; frontend test for any new logic; all checks pass
- [ ] Migration is additive; tested on an upgraded copy of production data (restore a backup to staging)
- [ ] Behind a feature flag if it is user-visible and not trivial
- [ ] Alerts for the decisions it introduces (`services/notify.py`) and an entry in `docs/NOTIFICATIONS.md`
- [ ] Docs: README section, `docs/FEATURES.md`, config table if new variables
- [ ] Post-deploy check extended if the feature adds something that can break silently
- [ ] Rollback understood: flag off, or previous image

## 8. When you outgrow one server

Do these in order, only when a real signal says so.

| Signal | Step |
|---|---|
| Deploy downtime matters | Blue/green: start the new image next to the old behind Caddy, switch upstream when healthy. Safe now because of the scheduler lock. |
| Database is the bottleneck or you want fewer chores | Move Postgres to a managed service (point `DATABASE_URL` at it, drop the `db` service). Gain: backups, point-in-time recovery, upgrades. |
| Web traffic outgrows one worker | Run a second app instance with `RUN_SCHEDULER=false`. First move the in-memory login and lookup rate limits to the database or Redis. |
| Voice audio grows | Move audio to object storage (S3-compatible) and keep only the key in the database; add a retention job. |
| You want alerts on closed browsers | Web push (service worker and VAPID keys) and/or SMS from `care_status._on_missed`. |
| Several people deploy | Build images in a pipeline, push to a registry (GHCR), and have the server `pull` instead of `build`. |

## 9. Gates before real patient data (Stage C)

None of these are built. They are the honest list of what stands between this demo and handling real people's health data.

- **Law and consent:** a lawful basis and explicit consent flows (India's DPDP Act 2023 applies to digital personal data;
  take legal advice for your jurisdiction), a privacy notice, and a way to export and delete a person's data.
- **Data processors:** written terms with every service that receives patient data. Voice audio and transcripts go to Groq and
  Google when AI keys are set; either obtain suitable terms and choose regions, or run speech and text models yourself.
- **Access:** multi-factor sign-in, professional identity verification, session and password policies, an access review.
- **Protection:** encryption at rest for the database volume and backups, restricted backup access, secret management beyond a
  file on disk, a documented retention period (including voice audio).
- **Operations:** central log retention and audit review, an incident-response plan, tested restores, an uptime and
  alerting service with a named on-call.
- **Clinical safety:** this is a coordination tool, not a diagnostic or emergency service. Keep that framing in the product,
  and have a clinician review the escalation rules, the routing wording and the AI prompts.

## 10. Known risks and how they are handled

| Risk | Handling |
|---|---|
| Two instances run the scheduler and double-alert | Postgres advisory lock; the loser skips the tick and reports `leader: false` in `/api/health`. |
| Bad deploy takes the app down | Health-gated switch with automatic rollback to the previous image; backup taken first. |
| Migration breaks the data | Additive-only rule; backup before every deploy; restore script. |
| Microphone does not work | Browsers require HTTPS off `localhost`: Caddy provides it. `Permissions-Policy` allows the microphone for the site. |
| AI provider down or slow | Per-provider circuit breaker, fallback chain, text-task timeout of 8 s; the app routes by rules without AI. |
| Demo data or reset endpoint on real data | `DEMO_MODE=false` closes the reset endpoint and marks new records non-synthetic; entrypoint refuses unsafe production settings. |
| Secrets leaked | Never in git (`.env.production` ignored), `chmod 600`, rotate on exposure. |
| Database tests differ from production | The test suite runs on SQLite. **Gap:** add a Postgres-backed test run so migrations and locks are tested on the real engine. |
| Disk fills (audio, logs, images) | Image pruning in `deploy.sh`, backup rotation (14), alert on disk usage. Move audio out of the database when volume grows. |
| Time zones | All times are stored UTC and shown in `APP_TIMEZONE`; keep the server clock synced (NTP). |

## 11. Command cheat sheet

```bash
COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
$COMPOSE ps                                  # what is running, and health
$COMPOSE logs -f app                         # follow the app log
curl -s https://<domain>/api/health          # version, database, scheduler
bash scripts/deploy.sh <tag>                 # deploy (with backup, verification, auto rollback)
bash scripts/backup.sh                       # manual backup
bash scripts/restore.sh backups/<file> --yes # restore (replaces the database)
python3 scripts/ai_check.py                  # verify AI keys (run where .env.production is loaded)
$COMPOSE exec db psql -U carecircle carecircle   # database shell
```
