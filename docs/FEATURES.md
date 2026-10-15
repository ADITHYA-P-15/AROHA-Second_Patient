# Feature log

Cumulative record of features built one at a time on top of the phased roadmap in [ARCHITECTURE.md](ARCHITECTURE.md). Each entry lists what shipped, where it lives, and what later features can reuse. Newest last.

## Baseline before feature work

| Phase | Shipped | Key modules |
|---|---|---|
| 1 | Auth, RBAC, audit history, LAN deploy | `main.py`, `core/` |
| 2 | Patients, caregivers, availability, activities, assignments | `api/domain.py`, `engine/availability.py`, `engine/workload.py` |
| 3 | Escalation engine, patient messaging, incidents, notifications | `engine/escalation_*.py`, `services/escalation.py` |
| 4 | Caregiver Command Center: attention items, daily plan, briefs, handovers | `engine/attention.py`, `services/command_center.py`, `api/command_center.py`, `CommandCenter.tsx` |

## Feature 2 — Workload Balancer

- **Goal:** spread caregiving fairly, prevent overload, reduce dependency on individual caregivers.
- **Shipped:**
  - Per-caregiver load against their own daily and weekly limits, across patients.
  - Demand by day and dependency findings.
  - Delegation classes: general, trained, and professional-only.
  - Greedy, explainable redistribution suggestions with additive scores, alternatives, and exclusion reasons.
  - One-tap apply that is re-validated on the server: request confirmation, or confirm now.
- **Code:**
  - `backend/app/engine/workload_balancer.py`
  - `backend/app/services/workload_balancer.py`
  - `backend/app/api/workload.py`
  - `frontend/src/WorkloadBalancer.tsx`
  - `frontend/src/lib/workload.ts`
- **Tests:**
  - `backend/tests/test_workload_balancer_engine.py`
  - `backend/tests/test_workload_balancer_api.py`
  - `frontend/src/lib/workload.test.ts`
- **Docs:** [WORKLOAD_BALANCER.md](WORKLOAD_BALANCER.md) and the README section "Feature — Workload Balancer".
- **Schema:** none (reads existing tables).
- **Reuse later:**
  - `check_receiver` for backup ranking and N-1/N-2 stress tests.
  - `evaluate_workload` on a modified snapshot for absence simulation.
  - The `demand` and `caregivers` outputs for capacity planning.
- **Not yet:**
  - Travel time between tasks.
  - Multi-task batch apply.
  - A balancer view for caregivers' own load.

## Maintenance — app shell and navigation (after Feature 2)

- The sidebar is scoped to `.sidebar`. Previously the Command Center's `<aside>` rail was pinned over it and hid the menu and logout.
- A visible **Log out** button sits in the top bar. The sidebar menu scrolls with the user block pinned, the current page is highlighted, and the page title shows in the header.
- On phones, a slide-in drawer replaces the icon-only bottom bar.
- Menu items that only led to placeholders are hidden, and each role lands on a working screen. When a later feature ships a screen, add it to `roleNav` in `frontend/src/shell.tsx`.
- Command Center deadline reasons are shown in the app timezone.
- The app is served on port 8000 only. Local previews use the same port.

## Feature 3 — Capability-Aware Backup Matcher

- **Goal:** replace repeated calls and manual delegation when someone declines or is absent.
- **Shipped:**
  - Automatic cover requests on decline or absence, plus manual **Find cover**.
  - Ranking by capability, qualification, availability window, commitments with travel buffers, and workload, then by suitability and continuity.
  - One-sentence reasons for every person.
  - One-tap offer with auto-advance on "no".
  - Acceptance plus confirmation required before a task counts as covered.
  - Metrics: time to secure, and % resolved without manual search.
  - Care Plan **I can't make it**.
  - Command Center buttons wired to real flows.
- **Code:**
  - `backend/app/engine/backup_matcher.py`
  - `backend/app/services/backup_matcher.py`
  - `backend/app/api/backup_matcher.py`
  - `models.CoverRequest` / `CoverRequestEvent`
  - `alembic/versions/0007_backup_matcher.py`
  - `frontend/src/CoverRequests.tsx`
  - `frontend/src/lib/cover.ts`
- **Tests:**
  - `backend/tests/test_backup_matcher_engine.py`
  - `backend/tests/test_backup_matcher_api.py`
  - `frontend/src/lib/cover.test.ts`
- **Docs:** [BACKUP_MATCHER.md](BACKUP_MATCHER.md) and the README section "Feature — Capability-Aware Backup Matcher".
- **Schema:** migration `0007_backup_matcher`.
- **Reuse later:**
  - `rank_candidates` for absence simulation and N-1 resilience (tasks with zero eligible backups).
  - The cover-request event trail for historical analytics.
- **Not yet:**
  - Real travel time (needs locations).
  - SMS/WhatsApp offers for people without the app.
  - Offer timeouts before the task starts.

## Maintenance — earlier review gaps (before Feature 4)

- Patient help messages now work on plain-HTTP LAN phones: there is a `getRandomValues` fallback for `crypto.randomUUID`, and one idempotency key is kept per draft.
- Level-3 escalations without a nurse route to the primary contact.
- Help summaries use the app timezone.
- Nurses and doctors can resolve only incidents they can see.
- History rejects negative offsets.

## Feature 4 — Predictive Coverage Planner

- **Goal:** find coverage problems before they happen instead of reacting.
- **Shipped:**
  - A 24 h / 3 d / 7 d forecast of gaps, unconfirmed tasks and single points of failure, each with a secure-by deadline and a one-tap next step.
  - Capacity rating per day.
  - An N-1 "if someone is away" list.
  - A findings log for the measures: identified before deadline, median warning time, preventable uncovered, and gaps prevented.
- **Code:**
  - `backend/app/engine/coverage_planner.py`
  - `backend/app/services/coverage_planner.py`
  - `backend/app/api/coverage_planner.py`
  - `models.CoverageFinding`
  - `alembic/versions/0008_coverage_planner.py`
  - `frontend/src/CoverageForecast.tsx`
  - `frontend/src/lib/forecast.ts`
  - `engine/backup_matcher.rank_in_context`: the ranking refactored to share one load context.
- **Tests:**
  - `backend/tests/test_coverage_planner_engine.py`
  - `backend/tests/test_coverage_planner_api.py`
  - `frontend/src/lib/forecast.test.ts`
- **Docs:** [COVERAGE_PLANNER.md](COVERAGE_PLANNER.md) and the README section "Feature — Predictive Coverage Planner".
- **Reuse later:**
  - The forecast and findings log for absence simulation (re-run `forecast` without one caregiver's commitments).
  - The 14-day forecast and capacity analytics in the dashboards phase.
- **Not yet:**
  - Travel time.
  - Predicting recurring patterns beyond 7 days.
  - A daily digest notification (deliberately left out to avoid adding alerts).

## Pivot — four roles, hospital data feeds, care status, automatic cover

- **Why:** the product is now centred on the caretaker's burden of remembering doses and appointments (see [PRODUCT_SPEC.md](PRODUCT_SPEC.md)).
- **Roles:** exactly patient, primary contact, caretaker and healthcare professional. Admin was removed, and doctor and nurse merged.
- **Registration:** the primary contact registers the patient, who gets a CareCircle ID. Professionals find and join by ID + birth year. Caretakers are invited by email and get a care profile automatically.
- **Feeds:**
  - Prescriptions expand into dose activities (rolling 14 days); appointments need an escort.
  - New feed activities go to the main caretaker when eligible.
  - Routine doses use time, not daily task slots.
- **Status:** PENDING → COMPLETED (on time / late) or MISSED, set by the scheduler at each deadline (dose: due + 60 min; appointment: end + 60 min). `_on_missed` notifies for recent misses only, and is the SMS hook. Adherence is reported per medicine.
- **Automatic cover:** leave, declines and unassigned activities (72 h) are offered to the best match without a tap. Overload is relieved one move per run, with a standby. The primary contact hears only when nobody can take it.
- **Cut:**
  - Admin panel and demo scenarios.
  - Briefs and handovers (tables dropped).
  - The escalation-policy editor and the dashboard.
  - Account-less caregivers and the clinical-visit capability.
- **Code:**
  - `services/care_team.py`
  - `services/care_feeds.py`
  - `services/care_status.py`
  - `services/auto_cover.py`
  - `api/care_feeds.py`
  - `services/workload_balancer.apply_move` (shared with the scheduler)
  - Migrations `0009_four_roles` and `0010_care_feeds`
  - Frontend: `CareTeam.tsx`, `ProfessionalPatients.tsx`, `MedicinesAppointments.tsx`, `MyDay.tsx`
- **Tests:**
  - `tests/helpers.py`: accounts in the four roles.
  - Rewritten `test_phase1.py`.
  - `test_care_feeds.py`
  - `test_auto_cover.py`
- **Next:**
  - SMS on a miss through `_on_missed`.
  - Verifying professionals.
  - Per-patient switch for automatic coordination.

## Stabilisation (after the pivot)

- **Why:** the demo data had drifted. Evening doses had no caretaker, so cover offers, alerts and "needs now" items fired constantly, and the screens showed raw states. The app felt random.
- **Demo story:** `services/demo.py` builds one coherent, clock-relative scenario. **Reset demo data** and `POST /api/v1/demo/reset` rebuild it (demo accounts only). It is rebuilt automatically once per scenario version.
- **Screens:**
  - New `CarePlan.tsx`, grouped by day, with a one-line "who is doing it" and only the relevant actions.
  - My Day across all of a caretaker's patients.
  - Help Requests rewritten.
  - Grouped navigation.
  - The patient choice persists between pages.
  - Human labels for hours and skills.
- **Quieter attention:** no "no backup" items. Confirmed doses and appointments are not flagged until they are late or missed. "On track" counts covered tasks.
- **Routing:** "I missed my medicine" goes to the caretaker (L1); twice goes to L4. Request titles are in words.
- **Code:**
  - `services/demo.py`
  - `seed/phase2.py` (now a thin wrapper)
  - `engine/attention.py`
  - `api/domain.py` (`cover` on activities)
  - `api/command_center.py`
  - `frontend/src/CarePlan.tsx`, `MyDay.tsx`, `PatientPick.tsx`, `lib/plan.ts`
- **Tests:**
  - `test_demo.py`
  - The updated attention test (quiet when on track)
  - The missed-medicine routing test
  - `lib/plan.test.ts`
- **Walkthrough:** [DEMO_SCRIPT.md](DEMO_SCRIPT.md).

## Scale-up (practical-size usage)

- **Why:** the demo had two patients and one doctor, which hides how the app behaves with real numbers and gives a professional nothing to analyse.
- **Population:** `services/population.py` builds 24 patients with families, 12 caretakers, 5 professionals and 30 days of history (about 2,000 doses, 70 appointments). It is deterministic, built once per version, and separate from the core story and its reset. People: [DEMO_PEOPLE.md](DEMO_PEOPLE.md).
- **Analytics:** `services/insights.py` and `api/insights.py` give a professional adherence, daily trend, follow-up flags, escort gaps and request response times over their own patients. **Insights** screen, CSV export, patient search.
- **Multi-user:**
  - Caretaker activity paging is filtered in SQL.
  - Larger connection pool.
  - Stable patient order.
  - `scripts/load_check.py`.
- **Code:**
  - `services/population.py`
  - `seed/population.py`
  - `services/insights.py`
  - `api/insights.py`
  - `frontend/src/Insights.tsx`
  - `lib/insights.ts`
  - `ProfessionalPatients.tsx`
- **Tests:**
  - `test_population.py`
  - `lib/insights.test.ts`
- **Next:**
  - Per-professional notification digests.
  - Trend alerts delivered to the professional (SMS hook in `care_status._on_missed`).

## AI assist: voice notes

- **Why:** voice notes are always reachable when a call is not, and need no typing. Hospitals and families get a record they can replay.
- **Flow:** record, upload, transcribe (Groq Whisper, Gemini fallback), classify by the rules, optional raise-only suggestion, route as a normal request with `voice_note` attached.
- **Principles:** AI advises, rules decide, a person confirms. Works without AI. The audio is always kept.
- **Code:**
  - `services/ai.py`
  - `api/voice.py`
  - `models.VoiceNote`
  - Migration `0011`
  - `frontend/src/VoiceNote.tsx`
  - `lib/voice.ts`
  - `scripts/ai_check.py`
- **Tests:**
  - `test_ai_providers.py`
  - `test_voice_notes.py`
  - `lib/voice.test.ts`
- **Docs:** [AI.md](AI.md).
- **Next:**
  - Progress reports for professionals.
  - Caretaker voice handover.
  - A per-language accuracy test set.

### Update: preview before sending, and the ambulance button

- **Preview, then send.** After recording, the sender sees what was heard in the spoken language, its English translation and who will be told. They can correct the words and re-check. Nothing is sent until they confirm.
- **Routing from the transcript.** The rules read the spoken text and the English translation; the assistant may only raise the level. Level 1 goes to the caretaker, 2 to family, 3 and 4 to the healthcare team, 5 to everyone.
- **Call ambulance.** A primary contact sees a **Call ambulance 108** button on requests that reach them. The phone dials; CareCircle records it and tells the rest of the care team.
- New endpoints are listed in [docs/AI.md](docs/AI.md). Migration `0012_voice_note_preview`.

### Update: alerts and reminders for every decision

- **Real alerts, not just a list.** Pop-up cards, a chime, browser desktop alerts when the tab is hidden, and the unread count in the tab title. Each person can choose "every update" or "important only".
- **Every decision tells the right people:** prescriptions, appointments, doses done, leave, task assignments, declines, team and main-caretaker changes, patient updates and "someone is on it".
- **Timely reminders from the scheduler, once per person:** dose in 15 minutes, appointment within a day and two hours, nobody confirmed yet, unanswered cover offers.
- **Quick requests confirm themselves.** The Request Help page now says what was sent, who was told and the live status, and a repeated tap merges into the open request ("asked again") instead of flooding the care team.
- Details: [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md). Migration `0013_notification_links`.

## Deployment readiness

- **Why:** to host the project beyond a laptop and keep shipping features without breaking what works.
- **Added:**
  - `docker-compose.prod.yml`, `deploy/Caddyfile`, `.env.production.example`: HTTPS, private database network, health checks.
  - `scripts/deploy.sh`, `backup.sh`, `restore.sh`, `postdeploy_check.py`: a backup-first, health-gated deploy with automatic rollback and a read-only verification.
  - A database lock so only one instance runs the scheduler, `/api/health` with version and scheduler state, feature flags (`FEATURES`) enforced on the server and respected by the UI, API docs hidden in production, production guards in the entrypoint.
- **Docs:** [DEPLOYMENT.md](DEPLOYMENT.md): the step-by-step guide, release strategy, feature-rollout rules, risks and the gates before real patient data.
- **Open:** a Postgres-backed test run, a registry-based deploy, web push, moving audio to object storage.

## Public-URL readiness (Render)

- `render.yaml` (validated against Render's published schema): Docker web service plus managed Postgres in Singapore, health check, deploy on commit (the build runs the tests), generated secret, AI keys entered in the dashboard.
- Host compatibility: `postgres://` URLs accepted, `$PORT` honoured, forwarded client IPs trusted when configured, commit shown in `/api/health`.
- Abuse guard for a public demo: per-person rate limit on voice previews.
- Docs: [DEPLOY_RENDER.md](DEPLOY_RENDER.md): platform comparison (why not Vercel), steps, day-2 operations, public-demo risks.


## AI progress report for professionals

- Draft report per patient from recorded facts only (treatment course, adherence and its change, missed/late doses, appointments, help requests and response time, check-ins, monitoring); the model phrases and every sentence is verified against cited facts; falls back to plain fact sentences; never sent automatically.
- Optional wellbeing check-in (pain 0-10, mood 1-5, note) by the patient or family/caretaker; migration 0014; behind the `progress_report` flag; included in demo reset.
- Docs: [AI.md](AI.md).

## Directory phase 1 — sector, agency and caretaker directory

- **Goal:** let a family find a suitable caretaker by region, agency, language, skills and availability, without exposing anyone's contact details.
- **Shipped:**
  - Sectors (with a configurable state map), agencies and caretaker listings.
  - **Find caretakers** for primary contacts: sector tabs, a filter bar, result cards and a profile drawer.
  - **My profile** for caretakers. A caretaker is unlisted until they opt in.
  - Privacy: phone, notes and district are shown only to care teams that already include the caretaker. Unlisted caretakers are hidden. Caretakers cannot browse.
  - Flag `directory`, default on.
- **Code:** `models.Sector` / `SectorState` / `Agency` / `CaretakerProfile`, `alembic/versions/0016_directory.py`, `services/directory.py`, `api/directory.py`, `seed/directory.py`, `seed/sector_states.json`, `frontend/src/FindCaretakers.tsx`, `MyDirectoryProfile.tsx`, `lib/directory.ts`.
- **Tests:** `backend/tests/test_directory.py` (migration up/down on SQLite and, with `TEST_POSTGRES_URL`, Postgres; each filter and combined; privacy; roles; pagination; seed idempotency), the population listing test in `test_population.py`, `frontend/src/lib/directory.test.ts`. `scripts/smoke.py` checks the directory when the flag is on.
- **Docs:** [DIRECTORY.md](DIRECTORY.md) and the README section "Directory phase 1".
- **Schema:** migration `0016_directory` (additive, guarded).
- **Reuse later:** the caregiver id on each listing for adding someone to a care team (Phase 3); `services.directory.search` for matching across agencies.
- **Not yet:** adding from the directory, agency administration, listing verification.

## Directory phase 2 — ratings and reputation

- **Goal:** let families choose caretakers on evidence: four visible, explained sources combined deterministically, with management-by-exception prompting.
- **Shipped:**
  - Agency ratings (seeded data), doctor ratings, family and patient reviews (the patient's review counts half), and a reliability metric from our own records.
  - A composite with sector-mean shrinkage and renormalised weights, plus "not enough history yet".
  - One rating prompt per caretaker threshold (Command Center item and notification). A quiet prompt for patients.
  - Reports for moderation, edit window, daily limits, and review-text privacy.
  - Daily snapshots written in the scheduler heavy pass.
  - The Backup Matcher score is relabelled **Fit for this task**.
- **Code:** `core/reputation_policy.py`, `services/reputation.py`, `api/reputation.py`, `seed/reputation.py`, `models.AgencyRating` / `DoctorRating` / `Review` / `ReviewReport` / `ReputationSnapshot`, `alembic/versions/0017_reputation.py`, `frontend/src/Reputation.tsx`, `lib/reputation.ts`, and wiring in `FindCaretakers.tsx`, `MyDirectoryProfile.tsx`, `CareTeam.tsx`, `ProfessionalPatients.tsx`, `CommandCenter.tsx`, `MyDay.tsx`.
- **Tests:** `backend/tests/test_reputation.py` covers formulas, shrinkage, missing sources, policy validation (including start-up), eligibility (403/409, edit window), the lower patient weight, privacy, reports and hiding, abuse limits, prompts (once, dismissed, 90-day return), snapshot idempotency and migration up/down. Frontend: `frontend/src/lib/reputation.test.ts`.
- **Docs:** [REPUTATION.md](REPUTATION.md) and the README section "Directory phase 2".
- **Schema:** migration `0017_reputation` (additive, guarded).
- **Open:** task check-ins are not recorded in this repository, so the on-time check-in component is left out until they are (hook in `services/reputation.metric_counts`). There is no moderator screen; hiding is a database flag.

## Task check-ins (rebuilt in the Phase 3 reconcile)

- **Why:** the original check-in commit (`cd70fad`) was not available, so it was rebuilt here to give the reliability metric and NO_CHECKIN cover real data.
- **Shipped:**
  - Check-in by the confirmed caretaker, on time or late with minutes recorded.
  - One NO_CHECKIN cover search per task with a missing check-in, cancelled if they check in.
  - The policy module `CHECKIN_POLICY`, validated at start-up.
  - The `checkins` flag (on by default).
  - Demo check-in history.
  - Reputation's on-time check-in component now uses real data.
- **Code:** `core/checkin_policy.py`, `services/checkins.py`, `api/checkins.py`, `seed/checkins.py`, `models.TaskCheckIn`, `alembic/versions/0015_task_check_ins.py`, `frontend/src/lib/checkin.ts` and the My Day button.
- **Migrations:** the chain is now 0014 → 0015_task_check_ins → 0016_directory → 0017_reputation, with one head.
- **Tests:** `backend/tests/test_checkins.py` (policy, permissions and window, on time vs late, NO_CHECKIN once and cancelled, metric with on-time, late and missing check-ins and with no data, snapshot idempotency, migration chain on SQLite and Postgres), `frontend/src/lib/checkin.test.ts`.
- **Docs:** [CHECKIN.md](CHECKIN.md).

## Directory phase 3 — hire requests, care-team builder, reputation-aware backups

- **Goal:** let a family build a care team from the directory with one-tap requests and consent-based contact sharing. Backup choices also account for reputation and the patient's preferences, while staying explainable and accept-only.
- **Shipped:**
  - Care preferences (migration 0018).
  - Hire requests (migration 0019): a compare-and-set state machine, 7-day expiry, Idempotency-Key, rate limit, capacity notes, and team join on accept.
  - The Build care team and Hire requests screens.
  - Matcher points and the `PREFERENCE` filter, policy in `MATCHER_POLICY`.
  - Directory suggestions when no one on the team is eligible.
  - Cover opened for a removed member's tasks.
  - Command Center items `BACKUP_BELOW_MIN_RATING` and `HIRE_REQUESTS_OPEN`.
  - Team reputation per patient in Insights.
- **Code:** `core/matcher_policy.py`, `services/team_builder.py`, `api/team_builder.py`, `engine/backup_matcher.extra_points` (plus `extras` in the snapshot), `services/backup_matcher` (extras and suggestions), `services/care_team.unlink_care_profile` (cover first), `services/command_center` (extra items), `services/insights` (`team_reputation`), `models.PatientCarePreference` / `HireRequest`, `frontend/src/BuildTeam.tsx`, `lib/teambuilder.ts`, and wiring in `CoverRequests.tsx`, `Insights.tsx` and `shell.tsx`.
- **Tests:** `backend/tests/test_team_builder.py` covers privacy before and after acceptance, every transition and the illegal ones, expiry, duplicates, Idempotency-Key, rate limit, the accept/withdraw/expire race, capacity notes, the matcher (reputation reorders but never overrides a hard rule, hard vs soft, neutral unrated, deterministic ties, explained terms, live cover ranking), suggestions never acted on, removal without stranded tasks, the Command Center warning appearing and clearing, the quiet request item, preferences permissions and Insights. Frontend: `lib/teambuilder.test.ts`. Migration chain tests are in `test_checkins.py`.
- **Not yet:** SMS or push; preference-aware N-1 in the Coverage Planner; a moderator screen.
- **Follow-up:** a minimum **agency rating** filter in Find caretakers and Build care team (`min_agency_rating`), the agency's rating shown on cards, matches and the compare view, and the gender setting renamed "Is this gender a must?" with a line explaining Preferred vs Required. See [DIRECTORY.md](DIRECTORY.md).

## Follow-up: one Find & build team screen, gender is a filter only

- **Merged screen:** Find caretakers and Build care team are now one screen, **Find & build team**, with every directory filter. It shows the top matches ranked with the backup logic (ratings, skills for the patient's needs, place, language, free time) and a reason for each.
- **Gender strictness removed:** the hard/soft gender preference, the matcher's `PREFERENCE` status and the soft-gender points are gone. Gender is a filter only. The preference columns are left unused, with no migration. `MATCHER_POLICY` adds `need_covered` and `little_capacity`, and drops `soft_gender`.
- **Tests:** `test_team_builder.py` (the merged list with filters and ranking; preferences never filter; gender rejected in preferences) and `lib/teambuilder.test.ts` (the query builder).
