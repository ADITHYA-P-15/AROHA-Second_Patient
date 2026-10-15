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

`sector`, `agency` (id), `state`, `city` (case-insensitive exact match), `gender` (`FEMALE`, `MALE`, `NON_BINARY`, `UNDISCLOSED`), `language`, `capability` (a support code such as `MEDICATION_ASSIST`), `min_experience` (0–60), `available_on` (a date), `sort` (`name` or `experience`), `limit` (1–50, default 20) and `offset`. Filters combine with AND. The response is `{items, total, limit, offset}`.

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

## Next (later phases)

- Add a caretaker from the directory to a care team (Phase 3); the profile's `id` is the caregiver id that flow will use.
- Agency management, verification of listings, a search index if the directory grows past a few thousand people.
