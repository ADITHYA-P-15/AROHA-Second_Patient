# The Second Patient

A caregiver-aware care-continuity platform for families coordinating transport, medication help, appointments, and daily support. When a caregiver becomes unavailable or overloaded, care can break even when the medical plan has not changed. The Second Patient is designed to deterministically surface operational care gaps, explain them clearly, suggest valid backups, and require human confirmation to resolve them.

**Team:** TODO: team name/members

## Quick start

Requirements: Docker Desktop with Compose and Python 3.11+ (3.12 recommended). From the repository root:

```powershell
Copy-Item .env.example .env # optional; scripts/start.ps1 creates it and generates SECRET_KEY
.\scripts\start.ps1
```

Or run `docker compose up --build -d` after creating `.env` from `.env.example`. The Compose app serves the API and bundled React UI from port 8000. Stop with `docker compose down` or `.\scripts\stop.ps1`. Demo accounts use `DEMO_PASSWORD` (default `Demo@1234`).

### Access URLs

- This laptop: [http://localhost:8000](http://localhost:8000)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health: [http://localhost:8000/api/health](http://localhost:8000/api/health)
- Other LAN devices: run `python scripts/lan-info.py` and open the printed `http://<LAN-IP>:8000` URL. On Windows, run PowerShell as Administrator and use `.\scripts\open-firewall.ps1` if other devices cannot connect. The inbound rule covers Public as well as Private profiles because phone hotspots often appear as Public. All devices must share the laptop's Wi-Fi/hotspot; use the laptop's hotspot-facing address when it hosts the hotspot.

For emergency use without Docker, `.\scripts\run-local.ps1` builds the frontend and runs FastAPI with local SQLite. Docker + PostgreSQL is the supported deployment. Development: run backend Uvicorn on :8000, then `npm run dev` from `frontend/` (Vite :5173 proxies `/api`).

## Phase 1 — Foundation, Auth & LAN Deployment

### Built

- FastAPI backend with SQLAlchemy models and initial Alembic migration for users, patients, patient care teams, and audit history; PostgreSQL deployment and SQLite local/test path.
- Cookie-based JWT sessions, Argon2 passwords, family-only self-registration, role reload on each request, session versioning, logout and password change, CSRF header enforcement, and login throttling.
- Patient and care-team endpoints with membership authorization, coordinator restrictions, role compatibility checks, last-coordinator protection, and filtered clinical notes.
- Synthetic demo users (`users.is_synthetic`) and two synthetic patients (`patients.is_synthetic`) with shared househelp on both care teams. `DEMO_PASSWORD` can be changed from the default.
- Responsive family dashboard, role badge and demo sign-in chips, patient/care-team/history/system status loaded from the API, tokenized CSS, bundled Inter fonts, and operational disclaimer.
- Docker Compose on port 8000, LAN address helper, start/stop scripts, Windows firewall helper, no-Docker fallback, smoke script, project rules, and architecture/roadmap documentation.

### API endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | API and database liveness |
| `GET /api/v1/meta` | Version, phase, demo mode, timezone, server time |
| `POST /api/v1/auth/register` | Create FAMILY account and sign in |
| `POST /api/v1/auth/login` | Sign in; rate limited |
| `POST /api/v1/auth/logout` | Clear session cookie |
| `GET /api/v1/auth/me` | Current DB-backed user |
| `POST /api/v1/auth/change-password` | Change password and invalidate prior sessions |
| `GET/POST /api/v1/patients` | List accessible patients / create patient |
| `GET/PATCH /api/v1/patients/{id}` | Read/update patient profile |
| `GET/POST /api/v1/patients/{id}/care-team` | List/add existing account to team |
| `DELETE /api/v1/patients/{id}/care-team/{member_id}` | Remove member subject to coordinator rule |
| `GET /api/v1/patients/{id}/history` | Paginated audit history |
| `POST /api/v1/admin/demo/reset` | Admin-only reset while demo mode is enabled |

All state-changing requests require `X-Requested-With: second-patient`. The browser API client sends it automatically. Unauthorized patient lookups return 403; unknown IDs return 404. Inputs reject unknown fields. Error responses use the common `error` envelope and request ID. The dashboard is live for family/admin demo accounts; remaining portal routes are marked for later phases.

### Security and design decisions

- Demo accounts are isolated examples; newly registered users always receive FAMILY role. Roles are never accepted by the registration schema.
- Sessions live in an HttpOnly, SameSite=Lax cookie. `COOKIE_SECURE=false` supports plain HTTP LAN demos; use HTTPS and enable it when deployed behind TLS.
- User records are reloaded on each authenticated request; inactive accounts and changed token versions invalidate sessions.
- Patient data is scoped through care-team membership. Clinical notes are omitted for househelp. Audit history records patient/profile and team changes.
- The starting local database is SQLite; PostgreSQL 16 is the Compose path. An ordered idempotent seed registry holds phase data. `Base.metadata.create_all` is also kept available for test/local initialization; Alembic tracks schema revisions.
- Phase 1 has no AI features (`ai_enabled=false`). Decision engine, care-gap scoring, backup filtering, and confirmation workflow are later phases and will be deterministic backend code.

### Test and LAN verification

```powershell
python -m pytest backend/tests -q
python scripts/smoke.py --base-url http://localhost:8000
cd frontend; npm run lint; npm run typecheck; npm test; npm run build
```

For a second device, start the app, run `python scripts/lan-info.py`, ensure both devices share the same Wi-Fi/hotspot, run the Windows firewall helper if needed, then open the printed LAN URL in that device's browser. A second-device check requires a real second device and is not claimed as verified by repository tests.

## Architecture & Stack

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full stack, security contracts, target domain, and phase roadmap. Phase 1 uses FastAPI, SQLAlchemy, Alembic, PostgreSQL 16 (SQLite for tests/local fallback), React 18, Vite, TypeScript, TanStack Query, and bundled Inter font assets.

## Supported Environments

Docker Compose on Windows, macOS, or Linux with Docker Desktop/Engine; same-network modern browsers including phones. Development requires Node 20 and Python 3.11+ (recommended 3.12). LAN use over plain HTTP is intended for trusted demo networks.

## Environment Variables

Copy `.env.example` to `.env`; `scripts/start.*` makes a local copy and generates a random secret if none exists.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `dev` | Runtime mode (`dev` / `prod`) |
| `SECRET_KEY` | safe placeholder | JWT signing key; change for production |
| `DATABASE_URL` | PostgreSQL Compose URL | SQLAlchemy database connection |
| `APP_TIMEZONE` | `Asia/Kolkata` | Display/application timezone |
| `DEMO_MODE` | `true` | Enables synthetic demo and guarded reset |
| `SEED_DEMO` | `true` | Seed demo accounts and patients at startup |
| `DEMO_PASSWORD` | `Demo@1234` | Password for every seeded account |
| `COOKIE_SECURE` | `false` | Set true when served over HTTPS |
| `SESSION_HOURS` | `12` | Session duration |
| `LOG_LEVEL` | `INFO` | Server logging level |
| `AI_PROVIDER` | `none` | Reserved for Phase 8 |
| `AI_API_KEY` | empty | Reserved for Phase 8; unused now |
| `AI_MODEL` | empty | Reserved for Phase 8; unused now |
| `GIT_SHA` | `dev` | Build identifier surfaced in metadata |

## Database Setup

Compose starts PostgreSQL 16 with a named `pgdata` volume. The database port is bound to `127.0.0.1`; the web app is exposed on all host interfaces at 8000. Alembic runs on container start. `docker compose down` retains data; `docker compose down -v` deletes the database volume. The local fallback uses `./second_patient.db` SQLite.

## Test Instructions

Backend: `python -m pytest backend/tests -q` (set `PYTHONPATH=backend` if your pytest environment does not read `backend/pyproject.toml`). Frontend: run `npm ci`/`npm install`, then `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` from `frontend/`. Deployment smoke: `python scripts/smoke.py --base-url http://localhost:8000`; run the same command with the server laptop LAN URL for network verification. Smoke creates a random test account and patient.

## Test Accounts

All accounts below are synthetic; all use the configured `DEMO_PASSWORD`.

| Role | Email |
|---|---|
| ADMIN | `admin@secondpatient.demo` |
| FAMILY coordinator | `anita.iyer@secondpatient.demo` |
| FAMILY member | `karthik.iyer@secondpatient.demo` |
| FAMILY coordinator | `meera.pai@secondpatient.demo` |
| PATIENT | `ramesh.iyer@secondpatient.demo` |
| HOUSEHELP | `savitha@secondpatient.demo` |
| NURSE | `divya.menon@secondpatient.demo` |
| DOCTOR | `dr.arjun.nair@secondpatient.demo` |

## AI Tools Disclosure

Codex was used for code generation and planning. Update this disclosure if Cursor or Claude is used later.

## Third-Party Resources & Licenses

React and React DOM (MIT), Vite (MIT), TypeScript (Apache-2.0), React Router (MIT), TanStack Query (MIT), Lucide (ISC), Inter fonts from @fontsource (SIL Open Font License 1.1), FastAPI (MIT), SQLAlchemy (MIT), Alembic (MIT), Pydantic (MIT), Argon2 bindings (MIT), PyJWT (MIT), psycopg (LGPL-3.0-or-later). PostgreSQL uses the PostgreSQL License; container images retain their upstream licenses. No external CDN assets are loaded. See package metadata and upstream license files for complete terms.

## Synthetic Data Disclosure

All supplied people, care notes, and clinical-looking notes are fictional demonstration data, not real patient records. Seeded user and patient rows set `is_synthetic=true`; self-registered accounts are not marked synthetic. Do not enter real health or identifying data into this demo.

## Known Limitations

Phase 1 provides account and patient/team foundation only. The reset route clears patient/team/history rows but preserves user accounts. Remaining role portals are placeholders, and no gap detection, activity assignments, recommendations, notifications, AI, or real-time updates exist yet. Demo role switching uses pre-seeded accounts. The second-device LAN check is manual; host firewall rules and Wi-Fi client isolation can still prevent access. Login throttling is process-local and resets on restart. Database schema creation includes a create-all safety path alongside the migration baseline. npm audit reports build-only transitive advisories from the requested Tailwind CSS 3.4 toolchain; frontend dependencies are not copied into the runtime image.

---

## Existing Repository Event Guidelines

### Branch Rules
- Each team maintains `main`, `bugbounty`, and `fixing` branches. `main` is ongoing development; `bugbounty` is deployment/peer-testing; `fixing` is bug fixes.
- Keep `main` and `bugbounty` in sync until the Attack Phase. Never delete `bugbounty` or `fixing`.

### Attack Phase
- `bugbounty` freezes at the start of the Attack Phase. Only `bugbounty` is deployed for peer testing. Development may continue on `main`.
- Test only assigned projects and follow event testing rules.

### Fixing Phase
- Create `fixing` directly from `bugbounty` at the beginning of Fixing. Commit fixes only there; keep `bugbounty` frozen.
- Stop fixing commits at 3:30 AM. Merge validated fixes into `main` only after the phase ends. Update `bugbounty` only after organizers announce evaluation is complete.

### Bug Reporting and Safety
- Maximum 10 bug reports overall and 4 per target team. Report critical vulnerabilities or exposed data privately to organizers.
- Do not modify frozen branches, bypass repository restrictions, or perform destructive testing, denial of service, phishing, malware deployment, or tests against unrelated systems.
