# Caretaker directory (flag `directory`)

A primary contact can browse caretakers grouped by **sector** (North, South, East, West) and **agency**, filter them, and open a profile. Caretakers keep their own listing up to date. Adding someone from the directory to a care team comes in a later phase; until then families invite caretakers by email in **Care Team**, exactly as before.

Everyone in the directory is fictional demo data.

## Who can do what

| Role | Directory access |
|---|---|
| Primary contact | Browse, filter, open profiles (UI: **Find caretakers**) |
| Patient, healthcare professional | Browse and open profiles through the API (no screen yet) |
| Caretaker | Read and edit **only their own** listing (UI: **My profile**); cannot browse others |

Every endpoint needs a signed-in session; everything else is a 401 or 403. With the flag off, every directory endpoint returns 404 and the menu items disappear.

## Data model (migration `0016_directory`)

| Table | Purpose |
|---|---|
| `sectors` | The four sectors: `NORTH`, `SOUTH`, `EAST`, `WEST` |
| `sector_states` | Which sector each state belongs to. Configuration, seeded from `backend/app/seed/sector_states.json` |
| `agencies` | Name, sector, city, `is_synthetic`, `is_active` |
| `caretaker_profiles` | One per caregiver (`caregiver_id` unique): agency (optional), gender, origin and current state/city, current district, `sector_id` (derived from the current state), languages, years of experience, bio (500 characters at most), `listed`, `is_synthetic` |

Capabilities, daily and weekly limits, the weekly schedule and leave stay on the existing `caregivers` row and its schedule and override tables. The directory reads them, so it can never disagree with the care engines.

The migration is additive and guarded: it skips tables that exist, writes the sectors and state map once, and its downgrade drops only the four directory tables. It is tested up, down and up again on SQLite and on Postgres. The app also writes the sectors and state map at start-up, so a database created without migrations (local SQLite) has them too.

To move a state to another sector, or add one, edit `sector_states.json`. New states are added at the next start-up. Existing rows are not moved.

## API

All endpoints are under `/api/v1/directory`.

| Method and path | Who | Notes |
|---|---|---|
| `GET /sectors` | Any signed-in role | Sectors with their states (the caretaker's form needs the state list) |
| `GET /agencies?sector=` | Browse roles | Active agencies, optionally for one sector |
| `GET /caretakers` | Browse roles | Filters and paging, below |
| `GET /caretakers/{caregiver_id}` | Browse roles | Profile |
| `GET /me`, `PATCH /me` | Caretaker | Own listing. PATCH accepts `name`, `gender`, `origin_state`, `origin_city`, `current_state`, `current_city`, `current_district`, `languages`, `bio`, `listed`; other fields are rejected |

### Filters on `GET /caretakers`

`sector`, `agency` (id), `state`, `city` (case-insensitive exact match), `gender` (`FEMALE`, `MALE`, `NON_BINARY`, `UNDISCLOSED`), `language`, `capability` (a support code such as `MEDICATION_ASSIST`), `min_experience` (0–60), `min_agency_rating` (1–5: the agency's own rating of the caretaker, a reputation source; caretakers without one are left out once it is set), `available_on` (a date), `sort` (`name` or `experience`), `limit` (1–50, default 20) and `offset`. Filters combine with AND. The response is `{items, total, limit, offset}`.

`available_on` is answered by `engine/availability.effective_windows` for that day in the app timezone. A caretaker counts as available if their weekly schedule, minus approved leave, leaves any time on that day.

Sorting is deterministic: by name, or by experience (most first) and then name.

### Privacy

- Result cards hold only the public listing: name, gender, origin, current city and state, sector, agency, languages, capabilities, experience.
- A profile adds the bio and the daily and weekly limits. Phone, caregiver notes and the district are returned under `private` only when the viewer is on a care team that already includes this caretaker (as a team member or a linked care profile). Otherwise `private` is `null`.
- Unlisted caretakers do not appear in results. Their profile is a 404, except for care teams they already work with.
- A caretaker who has never saved their listing is **unlisted** until they tick "List me in the caretaker directory".
- Profile edits are recorded in the activity history (`directory.profile_updated`).

## Demo data

`backend/app/seed/directory.py` builds the demo data once per `DIRECTORY_VERSION`:

- 12 fictional agencies, three per sector.
- 60 fictional caretakers (`@directory.carecircle.demo`, demo password), 15 per sector, with varied gender, home state, languages, capabilities, schedules and experience. Two of them are unlisted.
- Listings for the 12 population caretakers (Anjali Verma … Jayesh Patel), placed under the three southern agencies once the background population exists.

All of these are marked `is_synthetic`. Phone numbers end in "(fictional)" and are not valid numbers. Districts are marked "(fictional)". Re-running the seed creates nothing new.

The core demo caretakers (Savitha, Lakshmi, Suresh) have no listing. **Reset demo data** does not touch the directory.

## Code

- `backend/app/models.py`: `Sector`, `SectorState`, `Agency`, `CaretakerProfile`
- `backend/alembic/versions/0016_directory.py`
- `backend/app/services/directory.py`: search, privacy shaping, own profile
- `backend/app/api/directory.py`
- `backend/app/seed/directory.py`, `backend/app/seed/sector_states.json`
- `frontend/src/FindCaretakers.tsx`, `frontend/src/MyDirectoryProfile.tsx`, `frontend/src/lib/directory.ts`
- Tests: `backend/tests/test_directory.py`, the population listing test in `backend/tests/test_population.py`, and `frontend/src/lib/directory.test.ts`. Set `TEST_POSTGRES_URL` to an empty Postgres database to run the Postgres migration test.

## Request to hire (Phase 3, flag `team_builder`)

A primary contact sends a **hire request** to one listed caretaker for one patient, as main caretaker or backup, with an optional message of up to 300 characters. The request goes through these states:

- **PENDING:** the caretaker gets one in-app notification and sees the request under **Hire requests**.
- **ACCEPTED:** in the same transaction the caretaker joins the care team through the existing invite mechanics (`CareTeamMember` plus `ensure_care_profile`), and the main-caretaker or backup flag is set as requested. Only now do the existing Care Team payloads show their phone and email to that team's primary contacts.
- **DECLINED, WITHDRAWN, EXPIRED** (after 7 days, in the scheduler heavy pass): nothing is revealed.

Rules:

- Every transition is a compare-and-set from PENDING, so when accept, withdraw and expiry race, exactly one wins and there is one care-team row.
- There is one open request per patient and caretaker, enforced by a partial unique index.
- Each primary contact can send 20 requests a day.
- `Idempotency-Key` replays return the original request; the same key for a different caretaker returns 422.
- If the caretaker is at their daily or weekly limits, or has no available hours in the next 7 days, the request says so.
- Request responses never include phone, email or notes. Other primary contacts never see them.
- Delivery is in-app only; there is no SMS, push or phone call.

## Next (later phases)

- Add a caretaker from the directory to a care team (Phase 3); the profile's `id` is the caregiver id that flow will use.
- Agency management, verification of listings, a search index if the directory grows past a few thousand people.

## Agency rating filter and "Is this gender a must?" (after Phase 3)

- **Agency rating filter.** **Find caretakers** and **Build care team** both have a minimum **Agency rating** filter (any, 3★, 3.5★, 4★, 4.5★ and up). It uses the agency's own 1–5 rating of each caretaker, one of the four reputation sources. Independent caretakers, and those their agency has not rated, are left out once a minimum is chosen. Cards and matches show the agency's rating next to the agency name, and the compare view has an "Agency rating" row.
  - API: `GET /api/v1/directory/caretakers?min_agency_rating=4` and `GET /api/v1/patients/{id}/team-matches?min_agency_rating=4`. Values outside 1–5 return 422.
- **"Is this gender a must?"** (formerly "How strict") belongs to the patient's gender preference in Build care team.
  - **Preferred:** caretakers of that gender get +6 points in matches and in the Backup Matcher. Everyone else is still shown and can still be offered cover, just lower.
  - **Required:** caretakers of other genders, or with no gender recorded, are left out of matches. In cover they appear under "Everyone else" with the reason "Family preference", and they are never offered the task.
