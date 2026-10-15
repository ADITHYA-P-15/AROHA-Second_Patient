# Putting CareCircle on a public URL

This is the platform choice and the exact steps for a public deployment. The general release strategy, rollback rules and
feature-rollout rules are in [DEPLOYMENT.md](DEPLOYMENT.md); this file is the "which host, and how" part.

## 1. Which platform

What the app needs decides this, not preference:

- **An always-on process.** The scheduler (reminders, missed-dose alerts, escalation timers, automatic cover) runs inside the
  app every 15 to 60 seconds. If the host stops the process when nobody is visiting, those stop too.
- **PostgreSQL.** All state is in the database, including voice audio.
- **One service** that serves both the UI and the API (same origin, so the sign-in cookie and the security policy stay simple).
- Request bodies of a few MB (voice notes) and AI calls of several seconds.

| Option | Fit | Why |
|---|---|---|
| **Render** (web service + managed Postgres) | **Recommended** | Runs the Docker image as it is, always on from the Starter plan, managed Postgres, automatic HTTPS and domains, deploys on every commit (the build runs the tests), one-click rollback. Least to operate. |
| Railway | Good alternative | Same shape (Docker service + Postgres add-on), usage-based pricing. Use the same environment variables. |
| Fly.io | Good alternative | Strong regional options (including Mumbai); more command-line work (`fly.toml`, Postgres, volumes). |
| One VM with Docker Compose | Best control and cost | Already built: `docker-compose.prod.yml`, Caddy, `scripts/deploy.sh` (see [DEPLOYMENT.md](DEPLOYMENT.md)). More chores: patching, backups, monitoring are yours. |
| Google Cloud Run / similar scale-to-zero | Poor fit | Scales to zero between requests, which stops the scheduler. Only works with "minimum one instance, CPU always allocated", at which point it costs like a VM. |
| **Vercel / Netlify** | **Not suitable for the backend** | Serverless functions run per request with a time limit and no background loop, so the scheduler cannot run. They could host a static copy of the UI only, but then the API would be on another origin: cross-site cookies, CORS and the strict `connect-src 'self'` policy would all need rework, for no benefit. |

**Free tiers do not work for this app.** On Render, a free web service sleeps after 15 minutes without traffic (the scheduler
stops, and the first visitor waits about a minute for a cold start), and a free Postgres database expires after 30 days and is
then deleted after a short grace period ([Render free tier](https://render.com/docs/free)). Use the Starter web service and a paid
Postgres plan. Check current prices on Render's pricing page before you commit.

## 2. What was prepared in this repository

| Change | Why a host needs it |
|---|---|
| `render.yaml` (validated against Render's published JSON schema) | One click creates the web service and the database, wires `DATABASE_URL`, generates `SECRET_KEY`, sets the health check path. |
| `postgres://` and `postgresql://` URLs are accepted | Platforms hand out these; the app uses the psycopg 3 driver and previously needed `postgresql+psycopg://`. |
| Listens on `$PORT` | Hosting platforms choose the port. Default stays 8000 for local use. |
| `FORWARDED_ALLOW_IPS=*` | Behind a proxy every request looks like it comes from the proxy; with this the app sees the real client, so login and lookup rate limits are per visitor and not shared by everyone. |
| `RENDER_GIT_COMMIT` shown in `/api/health` | Lets you confirm which commit is live. |
| Rate limit on voice previews (12 per person per 10 minutes) | A public URL invites strangers to burn the AI quota. |
| Production guards | The app refuses to start in production with a short secret or without secure cookies; API docs are hidden. |

These were tested by running the image the way Render does (a `postgresql://` URL, `PORT=10000`, a forwarding proxy, a fresh
database): health, version, production flags, hidden schema, scheduler running, and per-visitor rate limiting all passed.

## 3. Step by step on Render

1. **Get the code on GitHub** with `render.yaml` at the repository root (it is on `main` once this is merged).
2. **Deploys are gated by the build.** `render.yaml` deploys every commit to `main` (`autoDeployTrigger: commit`). The image build
   runs the whole backend and frontend test suites, so a failing commit never replaces the running version.
3. **Create the services.** In Render: New, Blueprint, connect the GitHub repository, branch `main`. Render reads
   `render.yaml` and lists a web service `carecircle` and a database `carecircle-db`. Click Apply.
4. **Enter the two secrets it asks for**: `GEMINI_API_KEY` and `GROQ_API_KEY`. Leave them empty to run without AI (voice notes
   are then routed for a person to listen to).
5. **Wait for the first deploy.** The build runs the full test suite inside the image, so allow several minutes. On first boot the
   app creates the schema and builds the demo data before it opens the port (tens of seconds). Watch the service's Logs.
6. **Open the URL** Render shows (`https://carecircle-xxxx.onrender.com`).
7. **Verify** from your machine (read-only, creates nothing):

   ```bash
   python scripts/postdeploy_check.py --base-url https://carecircle-xxxx.onrender.com --expect-prod --wait-scheduler
   ```

   Then do one human run-through on a phone: sign in as the demo patient, record a voice note, confirm the preview, send it, and
   watch the alert reach the family account (the microphone works because the site is HTTPS).
8. **Custom domain** (optional): the service's Settings, Custom Domains, add your name and create the CNAME record Render shows.
   The certificate is automatic.
9. **Alerting**: add an external uptime monitor on `/api/health` and alert if `scheduler.last_tick_at` is older than five minutes.

## 4. Day-2 operations

| Task | How |
|---|---|
| Ship a change | Merge a pull request. Render builds (running the tests) and deploys. Migrations run on boot (additive only: see DEPLOYMENT.md section 7). |
| Roll back | Render dashboard, the service's Deploys tab, pick the previous deploy, Rollback. Safe because migrations are additive. |
| Turn a feature on or off | Edit `FEATURES` in the service's Environment and save (Render restarts it). Add `voice_notes` to enable, remove it to disable. |
| Rotate a secret | Change it in Environment. Changing `SECRET_KEY` signs everyone out. |
| Backups | Check which backup and recovery features your Postgres plan includes in the database's page. In addition, take your own dump: add your IP to the database's access list, run `pg_dump "<external connection string>" \| gzip > carecircle.sql.gz`, then remove the IP again. Test a restore once. |
| Reset the demo | The sidebar's **Reset demo data** button (demo accounts only). |
| Bigger | Change the instance type. Keep one instance: login rate limits are per process (the scheduler is already protected by a database lock). |

## 5. What a public demo means (read this before sharing the link)

- **Anyone can reach it, sign up, and use the demo accounts.** The demo password is in this repository. That is fine for fictional data
  and a demonstration; it is not acceptable for real people's information (DEPLOYMENT.md section 9 lists what real data needs).
- **AI usage is metered by someone.** Voice notes call Groq and Google. Mitigations in place: a per-person rate limit and a 3 MB size
  cap. If abused, remove `voice_notes` from `FEATURES` or clear the keys.
- **Voice audio is stored in the database** (a few hundred KB each). The demo reset removes the demo patients' notes; others stay.
- **Disclosure:** the footer already states it is a coordination demo, not a diagnostic or emergency service, and all data is fictional.

## 6. If you prefer a single server

Everything for a VM exists: follow [DEPLOYMENT.md](DEPLOYMENT.md) sections 3 to 5 (`docker-compose.prod.yml`, Caddy for HTTPS,
`scripts/deploy.sh`). It is the cheapest and most controllable route; the price is that patches, backups and monitoring are yours.
