# CareCircle

## 1. Project name, team details, and a short solution summary

**Project:** CareCircle. **Team:** CodeBlue — Aditya Prasad, Gaspar Anothony Savio Simoes, Pusapati Nikhil, and Shrivas Shetty.

CareCircle coordinates medication doses, appointments, caretaker assignments and replacement cover. Patients, primary contacts, caretakers and healthcare professionals share role-specific views of completed, pending and missed care activities. All demo people are fictional.

## 2. Architecture and technology stack

React and TypeScript provide the UI, with Vite, Tailwind CSS, React Router and TanStack Query. Python/FastAPI handles APIs, authentication and deterministic coordination rules. SQLAlchemy and psycopg connect to PostgreSQL 16; Alembic manages migrations. FastAPI serves the built UI and API together on port 8000. A background worker handles escalation timers, missed activities and cover coordination. See [Architecture](docs/ARCHITECTURE.md) and the current [Product spec](docs/PRODUCT_SPEC.md).

## 3. Supported environments and dependencies

Docker Compose is the supported deployment on Windows with Docker Desktop, or Linux/macOS with Docker and Compose. PowerShell and shell helper scripts are included. Python 3.11+ (3.12 recommended) runs local helpers and the backend fallback; Node.js 20.19+ is needed when building the frontend locally. Backend dependencies are listed in `backend/requirements.txt`, frontend dependencies in `frontend/package.json`. Initial image/dependency downloads need internet; the built application bundles its UI assets and fonts for offline LAN use.

## 4. Installation and run commands

From the repository root, with Docker running:

```powershell
.\scripts\start.ps1
```

The Windows start script creates `.env` with a generated session secret if it does not exist. On Linux/macOS, use `bash scripts/start.sh`. With `.env` already configured, direct Compose commands are:

```sh
docker compose up --build -d
docker compose logs -f app
docker compose down
```

For the local SQLite fallback on Windows, run `.\scripts\run-local.ps1`; this requires local Python and Node.js.

## 5. Deployment method and access instructions

Docker Compose runs separate application and PostgreSQL containers. A named `pgdata` volume persists the database across normal restarts and `docker compose down`. The app listens on `0.0.0.0:8000`; PostgreSQL's published port is restricted to the host's `127.0.0.1:5432`.

- Laptop: [http://localhost:8000](http://localhost:8000).
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs).
- LAN devices: `http://<laptop-LAN-IP>:8000` on the same Wi-Fi/hotspot. Run `python scripts/lan-info.py` to find the URL.
- If Windows blocks LAN access, run `.\scripts\open-firewall.ps1` once from Administrator PowerShell in the project folder. Networks with client isolation may still block access.

**Hosted deployment.** For a public or shared deployment with HTTPS (needed for the microphone off `localhost`), use `docker-compose.prod.yml`, which adds Caddy for TLS, a private database network, health checks and restart policies. `scripts/deploy.sh` backs up, builds, switches, verifies and rolls back automatically. Follow the step-by-step guide and release strategy in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). For a managed public URL, `render.yaml` and [docs/DEPLOY_RENDER.md](docs/DEPLOY_RENDER.md) cover the platform choice (Render recommended; Vercel is not suitable for the backend) and the exact steps.

## 6. Environment variables and safe example configuration

[.env.example](.env.example) contains placeholder/demo values, with no real API keys. Keep the local `.env` untracked. For manual setup, copy `.env.example` to `.env` and replace `SECRET_KEY` with a randomly generated secret before use.

| Variables | Purpose |
|---|---|
| `APP_ENV`, `SECRET_KEY` | Runtime environment and JWT signing secret |
| `DATABASE_URL` | Database connection; Compose supplies its internal PostgreSQL URL |
| `APP_TIMEZONE` | Display/scheduling timezone, default `Asia/Kolkata` |
| `DEMO_MODE`, `SEED_DEMO`, `DEMO_POPULATION`, `DEMO_PASSWORD` | Fictional demo behavior, seeding and account password |
| `AUTO_COORDINATION`, `ESCALATION_TIME_SCALE` | Automatic cover and demo escalation timing |
| `COOKIE_SECURE`, `SESSION_HOURS` | HTTPS-only cookie setting and session lifetime |
| `LOG_LEVEL`, `GIT_SHA` | Logging and build identification |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `GEMMA_MODEL`, `GEMINI_SPEECH_MODEL`, `GROQ_STT_MODEL`, `GROQ_TEXT_MODEL`, `AI_SPEECH_ORDER`, `AI_TEXT_ORDER` | Optional, advisory AI for voice notes (speech to text, translation, urgency suggestion). Empty keys disable it; see [docs/AI.md](docs/AI.md) |
| `PORT`, `FORWARDED_ALLOW_IPS` | Listening port (set by hosting platforms) and whether to trust the platform proxy for client IP and scheme |
| `FEATURES`, `RUN_SCHEDULER` | Staged rollout allow-list of features, and whether this instance runs the scheduler (only one ever does, enforced by a database lock) |
| `AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL` | Unused legacy settings |

The example database credentials and demo password are for fictional local demonstrations. Production deployment requires separate credentials, HTTPS and appropriate secret management.

## 7. Database setup and test instructions

Docker initializes PostgreSQL, waits for database readiness, applies `alembic upgrade head`, and seeds enabled fictional demo data. No manual table creation is needed. The larger population is controlled by `DEMO_POPULATION`; the demo reset preserves it. SQLite is used for local backend tests.

With backend dependencies installed in your Python environment, run from the repository root:

```sh
python -m pytest backend/tests -q
```

From `frontend/`, with dependencies installed using `npm ci`:

```sh
npm run lint
npm run typecheck
npm test
npm run build
```

Against the running deployment, from the repository root:

```sh
python scripts/smoke.py --base-url http://<LAN-IP>:8000
python scripts/load_check.py --base-url http://<LAN-IP>:8000 --users 40 --seconds 20
```

The smoke check creates test records; the load check uses seeded demo accounts and currently expects the default demo password. Do not use `docker compose down -v` unless you intend to delete the persisted database volume.

## 8. Known limitations

- This is an operational coordination demo, not a diagnostic or emergency service; use fictional data only.
- Default LAN deployment uses HTTP. HTTPS, professional identity verification, multi-factor authentication and configured encryption at rest are not implemented by this setup.
- Alerts (pop-ups, sound, desktop notifications, reminders) appear while CareCircle is open in a browser; web push and SMS to a closed phone are not implemented. Screens poll for updates. AI is optional and advisory; accuracy for real speakers has not been measured.
- The scheduler runs in one application process (a database lock keeps a second instance from also running it); multi-worker web serving is not configured. Forecasts cover up to seven days and do not calculate real travel times.
- Vite/Vitest can encounter module-resolution problems when the project path contains `#`, as in `M#`; use a checkout path without that character for local frontend testing.

## Team details

**Team name:** CodeBlue  
**Project:** CareCircle

| Team member | Details listed in the project README |
|---|---|
| Aditya Prasad | Team member |
| Gaspar Anothony Savio Simoes | Team member |
| Pusapati Nikhil | Team member |
| Shrivas Shetty | Team member |

The README does not specify individual contribution areas.

## Current known limitations

CareCircle currently provides the Phase 1/2 foundation and an initial Phase 3 deterministic classifier/message-to-incident path. Time-boxed escalation, complete role portals, absence simulation, and real-time updates are not yet implemented. The reset route clears patient/team/history rows but preserves user accounts. Demo role switching uses pre-seeded accounts. The second-device LAN check is manual; host firewall rules and Wi-Fi client isolation can still prevent access. Login throttling is process-local and resets on restart. Database schema creation includes a create-all safety path alongside the migration baseline. npm audit reports build-only transitive advisories from the requested Tailwind CSS 3.4 toolchain; frontend dependencies are not copied into the runtime image.

## Potential security limitations to assess

These are areas to test, not confirmed vulnerabilities. No security audit has established which, if any, affect this project:

- **Patient access (BOLA/IDOR):** whether a user can access another patient's records by changing a patient, activity, or related resource ID.
- **Role permissions:** whether each role is prevented from performing actions reserved for another role.
- **Sensitive fields:** whether API responses expose private notes, account details, or other fields a user does not need.
- **Input tampering:** whether submitted fields can change record ownership, roles, permissions, or other protected values.
- **Authentication and sessions:** password handling, session-cookie settings, logout, expiry, and account recovery.
- **Patient lookup abuse:** whether CareCircle IDs and birth years can be guessed or enumerated, and whether attempts are rate-limited.
- **Request abuse:** whether login, lookup, voice-note, and other costly endpoints are protected against excessive requests.
- **Input handling and uploads:** validation and safe storage of user text, filenames, and voice recordings.
- **Web protections:** CSRF, CORS, HTTPS, security headers, and cookie configuration.
- **Secrets and deployment settings:** possible exposure of credentials, API keys, demo accounts, or debug details in the repository, logs, or production configuration.
- **Database and backups:** access restrictions for database connections and protection of stored data and backups.
- **Errors and logs:** accidental disclosure of stack traces, secrets, or sensitive patient information.
- **Dependencies and containers:** vulnerable packages, outdated base images, or unsafe build settings.
- **External AI services:** controls around sending voice recordings or patient-related text to external providers.
- **Workflow edge cases:** concurrent or repeated requests causing duplicate assignments, bypassed approvals, or inconsistent care records.

## Demo credentials

The following fictional accounts cover every application role. All listed accounts use the demo password `Demo@1234` in the configured demo environment. These are public demo credentials for synthetic data only; never reuse them for real accounts.

| Role | Demo email(s) | Password |
|---|---|---|
| Primary contact | `anita.iyer@secondpatient.demo` | `Demo@1234` |
| Patient | `ramesh.iyer@secondpatient.demo` | `Demo@1234` |
| Caretaker | `savitha@secondpatient.demo`, `lakshmi@secondpatient.demo` | `Demo@1234` |
| Healthcare professional | `dr.arjun.nair@secondpatient.demo` | `Demo@1234` |

See [docs/DEMO_PEOPLE.md](docs/DEMO_PEOPLE.md) for the larger fictional demo population. All demo people and patient information are synthetic.
