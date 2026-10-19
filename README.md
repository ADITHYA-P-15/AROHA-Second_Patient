# AROHA

**Care coordination for patients, families, caretakers and healthcare professionals.**

> *The caregiver is the second patient.*

AROHA puts every medication dose and appointment for a patient in one place, so caretakers no longer have to remember them, and families and hospitals can see what was done, what is due and what was missed.

Built by **Team CodeBlue**: Aditya Prasad, Gaspar Anothony Savio Simoes, Pusapati Nikhil and Shrivas Shetty.

> **Demo only.** AROHA is an operational coordination prototype, not a diagnostic or emergency service. All people and records in the demo are fictional. Do not enter real health or identifying data.

---

## Table of contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Quick start](#quick-start)
- [Deployment](#deployment)
- [Configuration](#configuration)
- [Testing](#testing)
- [Demo accounts](#demo-accounts)
- [API overview](#api-overview)
- [Documentation](#documentation)
- [Known limitations](#known-limitations)
- [Disclosures and licenses](#disclosures-and-licenses)

---

## Features

**Roles**
- **Patient**: requests help, sees their own plan.
- **Primary contact** (a family member): registers the patient and oversees care.
- **Caretaker**: carries out doses, appointments and tasks.
- **Healthcare professional**: finds a registered patient by AROHA ID and birth year, then prescribes medicines and schedules appointments.

**Core care coordination**
- Every dose and appointment is tracked as *pending*, *completed* or *missed*, judged against the clock.
- **Automatic cover:** when a caretaker declines, takes leave or is overloaded, AROHA asks the best eligible caretaker to cover. A task counts as covered only after the replacement accepts.
- **Command Center** for primary contacts, quiet when things are fine, with one-tap next steps when they are not.
- **Task check-ins:** caretakers check in on arrival. A missed check-in triggers a cover search.

**Planning and balancing**
- **Backup Matcher:** ranks caretakers by capability, qualification, availability, overlaps and workload, with a plain-language reason for each.
- **Workload Balancer:** shows caretaker load, high-demand days and single points of dependency, and suggests task moves. Nothing changes until the primary contact approves.
- **Coverage Forecast:** looks 24 hours, 3 days and 7 days ahead to flag gaps, unconfirmed tasks and single points of failure, with a secure-by deadline for each.

**Help requests and escalation**
- Patients send quick replies, text or an SOS with a cancellable countdown, plus direct 108/112 links.
- A deterministic classifier routes requests across levels L0-L5 in English, Hindi, Kannada and Telugu. Unknown text defaults to L2. SOS is always L5.
- Time-boxed escalation advances unacknowledged requests, with configurable per-patient timers and quiet hours.
- **Voice notes** (up to one minute, any language): transcription, translation and a preview before sending. An optional AI assistant may *raise* urgency but can never lower it or decide anything. Without AI keys, notes are routed to a person to listen to.
- Alerts and reminders for every care decision: pop-ups, sound and browser desktop notifications.

**Directory, reputation and hiring**
- Browse caretakers by sector, agency, language, skills, experience and availability.
- Composite reputation from agency rating, doctor ratings, family reviews and a reliability record computed from AROHA's own data. Formulas are fixed and documented; AI is not involved.
- Send hire requests, compare candidates and build a care team. Contact details are revealed only once a caretaker joins the team.

**Insights for professionals**
- Adherence trends, missed and late doses, patients ranked by need for follow-up, CSV export.
- Draft **progress reports** where every figure is computed by the backend. AI only phrases the facts, and the report is never sent automatically.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, React Router, TanStack Query |
| Backend | Python 3.11+, FastAPI, SQLAlchemy, Alembic, psycopg |
| Database | PostgreSQL 16 (SQLite for local fallback and tests) |
| Auth | Cookie-based JWT sessions, Argon2 password hashing, CSRF header enforcement, login throttling |
| Deployment | Docker Compose (Caddy for TLS in production) |
| Optional AI | Groq (Whisper `large-v3`, `gpt-oss`) and Google Gemini/Gemma for voice notes and report phrasing |

FastAPI serves the built UI and the API together on port 8000. A background scheduler handles escalation timers, reminders, missed activities and cover coordination. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

---

## Quick start

**Requirements:** Docker with Compose (Docker Desktop on Windows). Python 3.11+ is needed only for helper scripts and the local fallback.

```powershell
# Windows (creates .env with a generated SECRET_KEY if missing)
.\scripts\start.ps1
```

```sh
# Linux / macOS
bash scripts/start.sh
```

Or run Compose directly once `.env` exists (copy from `.env.example`):

```sh
docker compose up --build -d
docker compose logs -f app
docker compose down
```

The database is created, migrated (`alembic upgrade head`) and seeded with fictional demo data automatically.

| URL | Purpose |
|---|---|
| http://localhost:8000 | Application |
| http://localhost:8000/docs | Interactive API docs |
| http://localhost:8000/api/health | Health check |

**Other devices on the same Wi-Fi:** run `python scripts/lan-info.py` and open the printed `http://<LAN-IP>:8000`. On Windows, run `.\scripts\open-firewall.ps1` once from an Administrator PowerShell if access is blocked. Networks with client isolation may still block connections.

**Without Docker:** `.\scripts\run-local.ps1` builds the frontend and runs FastAPI on SQLite (requires Python and Node.js 20.19+).

**Development:** run the backend with Uvicorn on port 8000, then `npm run dev` in `frontend/` (Vite on port 5173 proxies `/api`).

---

## Deployment

The default Compose setup runs separate app and PostgreSQL containers with a persistent `pgdata` volume. PostgreSQL is published only on `127.0.0.1:5432`.

For a public or shared deployment with HTTPS (required for microphone access off `localhost`), use `docker-compose.prod.yml`, which adds Caddy, a private database network, health checks and restart policies. `scripts/deploy.sh` handles backup, build, switch, verification and automatic rollback.

- Step-by-step guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- Managed hosting on Render (`render.yaml`): [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md)

> Do not run `docker compose down -v` unless you intend to delete the database volume.

---

## Configuration

Copy `.env.example` to `.env`. It contains placeholder values only, with no real keys. Replace `SECRET_KEY` with a random secret, and keep `.env` untracked.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `dev` | Runtime mode (`dev` / `prod`) |
| `SECRET_KEY` | placeholder | JWT signing key. **Change for any real use.** |
| `DATABASE_URL` | Compose PostgreSQL | Database connection |
| `APP_TIMEZONE` | `Asia/Kolkata` | Scheduling and display timezone |
| `DEMO_MODE`, `SEED_DEMO`, `DEMO_POPULATION` | `true` | Demo behavior, seeding and the larger fictional population |
| `DEMO_PASSWORD` | `Demo@1234` | Password for all seeded demo accounts |
| `ESCALATION_TIME_SCALE` | `1.0` | Demo-only timer scale (`0.1` shortens minutes to seconds) |
| `AUTO_COORDINATION` | | Automatic cover behavior |
| `COOKIE_SECURE`, `SESSION_HOURS` | `false`, `12` | HTTPS-only cookies; session lifetime |
| `FEATURES`, `RUN_SCHEDULER` | | Staged feature rollout; whether this instance runs the scheduler (one at a time, enforced by a database lock) |
| `PORT`, `FORWARDED_ALLOW_IPS` | | Listening port and proxy trust for hosting platforms |
| `GEMINI_API_KEY`, `GROQ_API_KEY` and model/order settings | empty | Optional AI for voice notes. Empty keys disable it. See [docs/AI.md](docs/AI.md). |
| `LOG_LEVEL`, `GIT_SHA` | `INFO`, `dev` | Logging and build identification |

Demo credentials are for fictional local use only. Production requires separate credentials, HTTPS and proper secret management.

---

## Testing

```sh
# Backend (repository root)
python -m pytest backend/tests -q

# Frontend (from frontend/)
npm ci
npm run lint
npm run typecheck
npm test
npm run build

# Against a running deployment
python scripts/smoke.py --base-url http://localhost:8000
python scripts/load_check.py --base-url http://localhost:8000 --users 40 --seconds 20
```

The smoke check creates test records. The load check uses seeded demo accounts and expects the default demo password. Backend tests run on SQLite.

> Vite/Vitest can fail to resolve modules if the project path contains `#`. Use a checkout path without that character for frontend testing.

---

## Demo accounts

All accounts are fictional and use `DEMO_PASSWORD`. For a guided walkthrough, see [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

| Role | Email | Notes |
|---|---|---|
| Primary contact | `anita.iyer@secondpatient.demo` | Ramesh Iyer's daughter |
| Primary contact | `karthik.iyer@secondpatient.demo` | Ramesh's son |
| Primary contact | `meera.pai@secondpatient.demo` | Sharada Pai's daughter |
| Patient | `ramesh.iyer@secondpatient.demo` | AROHA ID `CC-RAM354`, born 1954 |
| Caretaker | `savitha@secondpatient.demo` | Ramesh's main caretaker |
| Caretaker | `lakshmi@secondpatient.demo` | Weekdays |
| Caretaker | `suresh.kamath@secondpatient.demo` | Transport and escort, mornings |
| Healthcare professional | `dr.arjun.nair@secondpatient.demo` | Prescribes Ramesh's medicines |
| Healthcare professional | `divya.menon@secondpatient.demo` | Nurse |

A larger fictional population (24 more patients, 12 caretakers, 5 more professionals) is seeded unless `DEMO_POPULATION=false`. See [docs/DEMO_PEOPLE.md](docs/DEMO_PEOPLE.md).

---

## API overview

Interactive documentation is available at `/docs` on a running instance. All state-changing requests require the `X-Requested-With: second-patient` header, which the bundled client sends automatically. Inputs reject unknown fields, and errors use a common envelope with a request ID.

| Area | Representative endpoints |
|---|---|
| Auth | `POST /api/v1/auth/register`, `/login`, `/logout`, `/change-password` |
| Patients and teams | `GET/POST /api/v1/patients`, `/patients/{id}/care-team` |
| Help requests | `POST /api/v1/patients/{id}/messages`, `/sos`, `GET /api/v1/incidents` |
| Voice notes | `POST /api/v1/patients/{id}/voice-notes` |
| Cover | `GET /api/v1/patients/{id}/cover-requests`, `POST /api/v1/cover-requests/{id}/offer` |
| Planning | `GET /api/v1/patients/{id}/workload-balance` |
| Directory | `GET /api/v1/directory/caretakers`, `/directory/agencies` |
| Insights | `GET /api/v1/insights/professional` |
| Notifications | `GET /api/v1/notifications` |

---

## Documentation

| Topic | Document |
|---|---|
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Product spec | [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) |
| Escalation engine | [docs/ESCALATION.md](docs/ESCALATION.md) |
| Backup Matcher | [docs/BACKUP_MATCHER.md](docs/BACKUP_MATCHER.md) |
| Workload Balancer | [docs/WORKLOAD_BALANCER.md](docs/WORKLOAD_BALANCER.md) |
| Coverage Planner | [docs/COVERAGE_PLANNER.md](docs/COVERAGE_PLANNER.md) |
| Directory and reputation | [docs/DIRECTORY.md](docs/DIRECTORY.md), [docs/REPUTATION.md](docs/REPUTATION.md) |
| Check-ins | [docs/CHECKIN.md](docs/CHECKIN.md) |
| Notifications | [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md) |
| AI features | [docs/AI.md](docs/AI.md) |
| Deployment | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md), [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) |
| Demo walkthrough | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |

---

## Known limitations

- Prototype for demonstration. Not a diagnostic or emergency service.
- The default LAN deployment uses HTTP. HTTPS (via the production setup) is available, but professional identity verification, multi-factor authentication and encryption at rest are **not** implemented.
- Notifications are in-app only. Web push, SMS and calls are not implemented, and screens poll for updates.
- AI is optional and advisory. Accuracy for real speakers has not been measured, and the multilingual phrase lexicons are machine-drafted and need native-speaker review before real use.
- The scheduler runs in a single process (guarded by a database lock). Multi-worker serving is not configured, and login throttling is process-local.
- Forecasts cover up to seven days and do not calculate real travel times. Patient location is a city or region, not an address.
- There is no moderator screen for reviews.

---

