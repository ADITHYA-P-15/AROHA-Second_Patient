# Task check-ins (flag `checkins`)

The caretaker holding a task taps **I'm here · check in** in My Day when they arrive. If nobody has checked in shortly after the start, the task is searched for cover. That search uses the reason **NO_CHECKIN** and the same Backup Matcher, and the backup must still accept. An on-time check-in tells nobody (management by exception).

> This feature was rebuilt in this repository during the Phase 3 reconcile. The original commit (`cd70fad`) could not be found locally or on the remote. The design below follows what Phase 3 relies on: the `task_check_ins` table, the `checkins` flag, a validated `CHECKIN_POLICY`, and NO_CHECKIN cover searches. Where nothing specified the design, the defaults below are assumptions.

## Rules (`core/checkin_policy.py`, override with `CHECKIN_POLICY`)

| Setting | Default | Meaning |
|---|---|---|
| `categories` | APPOINTMENT, TRANSPORT, LAB, DAILY_ROUTINE, MOBILITY, POST_APPOINTMENT | Tasks that need a check-in. Medication doses are short and frequent; marking them done is their confirmation |
| `importance` | MEDIUM, HIGH, CRITICAL | Importance levels that need a check-in |
| `opens_before_min` | 60 | Check-in is accepted from this long before the start |
| `grace_min` | 15 | On time up to start + grace; **late** after that (minutes late recorded) |
| `missing_after_min` | 20 | With no check-in by start + this, one NO_CHECKIN cover request is opened |

`CHECKIN_POLICY` is a JSON object merged over the defaults. It is validated at start-up: unknown keys, unknown categories, negative or non-integer minutes, or `missing_after_min` < `grace_min` stop the app with "Invalid CHECKIN_POLICY: …".

## Who can check in

Only the caretaker who holds the task as confirmed primary can check in. Everyone else gets **403**. The task must still be scheduled, and the check-in must fall between `start − opens_before_min` and the end (otherwise **409**). There is one check-in per task (another is **409**). A task the policy doesn't cover returns **422**.

## Missing check-ins

The scheduler's heavy pass, about every 60 s, opens a cover request (reason NO_CHECKIN, the holder as the person being replaced) for each task that is past `start + missing_after_min` with no check-in. Each task and holder gets one, at most: the trigger key `nocheckin:<task>:<assignment>` makes it idempotent across ticks and restarts. If the holder checks in later, the open NO_CHECKIN request is cancelled. The holder keeps the task until a backup accepts, as with every cover request.

## Reliability metric (link to reputation)

For each caretaker over the reputation window, the check-in component of the reliability record counts:

- **expected** = tasks they held (confirmed primary) that needed a check-in and are past the missing point. A task whose NO_CHECKIN search moved it to someone else still counts against the original holder.
- **on time**, **late** = their check-ins on those tasks; **missing** = expected − on time − late.
- **On-time check-in % = on time / expected.** Late and missing both lower it. The late count is shown alongside.
- A caretaker with no expected check-ins shows "Check-ins are not recorded yet", and the component is left out (see [REPUTATION.md](REPUTATION.md)).

## API

| Method and path | Who |
|---|---|
| `POST /api/v1/activities/{id}/check-in` | The confirmed caretaker. Returns `{status: ON_TIME/LATE, minutes_late, checked_in_at}` |
| `GET /api/v1/check-ins?patient_id=&from=&to=` | Care-team members. Check-ins in the window (default ±24 h, at most 31 days) plus the policy the UI shows |

Data: `task_check_ins` (one row per task, migration `0015_task_check_ins`). The same migration adds `NO_CHECKIN` to the cover-request reasons. Downgrading turns any NO_CHECKIN request into MANUAL first.

## Demo data

`seed/checkins.py` writes check-ins once for the fictional population's past tasks that needed one: mostly on time, about one in six late, about one in twelve missing.

## Limitations

- Detection latency is the scheduler's heavy pass (about 60 s).
- There is no location check: "I'm here" is the caretaker's word.
- Notifications are in-app only.
