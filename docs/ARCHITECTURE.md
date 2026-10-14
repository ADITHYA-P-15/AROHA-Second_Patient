# The Second Patient — Architecture

## Product and stack

Care-continuity coordination for patients and their support networks. The system detects care gaps deterministically, explains consequences, recommends eligible backups, and requires confirmation to resolve support gaps. It is an operational tool, not a clinical or emergency service.

- **Frontend:** React 18, Vite, TypeScript strict, React Router, TanStack Query, Tailwind 3.4, react-hook-form, zod, lucide-react, bundled `@fontsource` fonts. Phase 1 starts with React/Vite/TypeScript and keeps a tokenized style layer.
- **Backend:** Python 3.12 (3.11+), FastAPI, SQLAlchemy 2, Alembic, Pydantic v2/settings, psycopg 3, argon2-cffi, PyJWT, pytest/httpx, ruff.
- **Database:** PostgreSQL 16 official; portable SQLAlchemy UUID/JSON/non-native enums support SQLite tests.
- **Serving:** FastAPI serves `/api/*` and built `frontend/dist` on :8000. SPA fallback is for non-API GETs; unknown API routes remain JSON 404. Vite development server is :5173 and proxies `/api` to :8000.
- **AI (Phase 8):** provider-neutral interface, minimal grounded context, deterministic template fallback; explanations only.

## Repository layout

```text
AGENTS.md, .cursor/rules/second-patient.mdc
docs/ARCHITECTURE.md
Dockerfile, docker-compose.yml, .env.example
scripts/{start,stop,open-firewall,lan-info,smoke,run-local}.*
backend/app/{core,models,schemas,api/v1,services,engine,ai,seed}
backend/alembic, backend/tests
frontend/src/{api,auth,components,layouts,pages,lib,styles}
```

## Conventions and security

- UUID identifiers; persist UTC timestamps with offsets at API boundaries. App timezone defaults to `Asia/Kolkata`. Time access goes through `core/clock.py:now()`; seed dates are relative to that clock.
- API prefix `/api/v1`; JSON errors use `{ "error": { "code", "message", "details", "request_id" } }`; list responses use `{items,total,limit,offset}`. Request models reject extra fields.
- Mutations use services: validate, authorize, write, append activity history; later phases reassess within the same transaction and notify.
- Audit rows include actor, patient/entity, event, summary, outcome, payload, request ID. Never log passwords, tokens, phone numbers, or clinical notes.
- User role is global; patient access is admin or care-team membership. Clinical notes are limited to patient, family coordinators, nurse, doctor, and admin; househelp/neighbour responses omit them.
- Cookie sessions are HttpOnly, SameSite=Lax JWTs; DB user reload ensures deactivation and token-version changes take effect. Mutations require `X-Requested-With: second-patient`.

## Roles and routes

Roles: PATIENT, FAMILY (coordinator/caregiver), HOUSEHELP, NURSE, DOCTOR, ADMIN (operations). Login users and care-network caregivers are separate concepts. Planned route groups: family dashboard/profile/network/plan/risk/graph/assistant/history; patient My Day/plan/help/voice/medicines; househelp tasks/availability/cover; nurse patients/visits/escalations/availability; doctor patients/appointments/instructions/voice; admin operations plus family views.

## Target domain

Phase 1: users, patients, care_team_members, activity_history. Phase 2 adds patient support needs, distinct caregivers, recurring schedules and overrides, activities, dependencies, and primary/backup assignments. Later: idempotent care gaps (types A–J), recommendations, notifications, help requests, visits, instructions, medications, voice notes, AI interactions.

Capabilities: `TRANSPORT`, `MEDICATION_ASSIST`, `PRESCRIPTION_PICKUP`, `DAILY_ASSIST`, `MOBILITY_ASSIST`, `LAB_ESCORT`, `SUPPLIES`, `CLINICAL_VISIT`, `APPOINTMENT_ESCORT`.

## Engine contracts for later phases

- Covered means a CONFIRMED PRIMARY assignment and caregiver capability/availability across the activity and travel buffers. Proposed or awaiting confirmation is not coverage.
- Each deterministic gap rule is idempotent by patient/type/subject key; a reappearing resolved gap becomes REOPENED.
- Reassess after mutations and every 60 seconds; overdue unsupported activities become high-priority operational gaps.
- Workload/conflict checks cross patient boundaries; details of other patients are masked.
- Per-patient advisory locking prevents duplicate concurrent reassessments. Priority uses additive documented points and breakdowns.

## Phase 2 decisions

- A **caregiver is not a login user**. A caregiver may optionally link to a unique `user_id`, and one caregiver may be linked to several patients. Relationship and backup designation belong to each patient link.
- No weekly schedule rows means unavailable. Weekly rows are recurring available windows in `Asia/Kolkata`; times are integer minutes after local midnight. Adjacent windows merge in calculations. Active unavailable overrides subtract time after available overrides are added; cancelled overrides stay in history.
- Required availability includes the activity's before and after buffers. The pure `engine/availability.py` module returns uncovered segments and blocking overrides. `engine/workload.py` counts primary assignments; confirmed and pending work are separate, and backups do not count until promoted. Workload and overlap queries span patients while API responses mask other patient identities and titles.
- `lifecycle_status` (`SCHEDULED`, `COMPLETED`, `CANCELLED`) is separate from stored `coverage_status` (`UNASSESSED` until Phase 3). Phase 2 UI says **Support confirmed / Not confirmed** based only on a confirmed primary assignment and marks it preliminary. It never calls care supported or safe.
- Invalid scheduling data, inactive/unlinked caregivers, cross-patient or cyclic dependencies, and assignments to terminal activities are rejected. Capability, availability, conflicts, workload limits, patient overlap, and near deadlines are warnings that leave an operation possible.
- Coordinator permissions manage one patient's plan and network. Family members share read access and may manage only their own caregiver availability or assignments. Househelp/nurses see their own assignments and associated activities, and may respond to their own assignments. Patients read the plan; doctors read the plan and clinical notes; administrators can manage all data. Patient/activity responses carry `my_permissions` for UI gating.
- Phone numbers are visible only to administrators, coordinators of a linked patient, and the caregiver's own linked user. Shared caregiver conflict details for other patients are reduced to a busy count or generic “busy — other commitment” label.
- Assignment transitions use the explicit state machine in the README. Terminal statuses cannot transition again. Postgres and SQLite both enforce at most one active primary assignment per activity; the service returns a clean conflict if a concurrent insert loses the constraint race.
- The Phase 2 reassessment hook records trigger, affected patient IDs, and context in the transaction session. It deliberately computes no gaps; Phase 3 supplies the real engine.

## Roadmap

- [x] 1 Foundation, auth/RBAC, LAN deploy
- [x] 2 Core domain (patients, caregivers, availability, activities, assignments)
- [ ] 3 Care-gap engine, reassessment, tests
- [ ] 4 Priority scoring, backup candidates, resolution workflow
- [ ] 5 Dashboard, risk/resolution, notifications, live updates, metrics
- [ ] 6 Care plan, care network, profile, dependency graph
- [ ] 7 Role portals
- [ ] 8 AI care assistant with fallback
- [ ] 9 What-if simulation and multilingual patient voice note
- [ ] 10 Hardening, bug-bounty readiness, demo, final docs

Evaluators need independent setup instructions, test accounts, safe self-registration, at least five real API operations, AI disclosure, `.env.example`, and no committed secrets.
