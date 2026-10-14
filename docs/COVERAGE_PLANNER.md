# Predictive Coverage Planner

**Pain point:** problems are discovered too late, so coordination is reactive.
**Solution:** CareCircle looks at the next **24 hours, 3 days and 7 days**, flags tasks that lack confirmed support or have only one feasible caregiver, and gives each one a **secure-by** deadline and a one-tap next step.

> Example: “Monday's Appointment is covered, but Savitha is the only eligible person. Arrange a backup before Sat 17 Oct, 10:00.”

## What it flags

Every caregiver task starting in the next 7 days is assessed with the Backup Matcher's rules: capability, professional-only tasks, availability windows and recorded absences, overlapping commitments with travel buffers, and daily or weekly limits.

| Kind | Rule | Next step |
|---|---|---|
| `GAP` | No caregiver, or the assigned caregiver cannot do it as recorded (recorded absence, double-booked, lacks the capability, inactive). A confirmed caregiver working outside their *usual* hours is not a gap; they already said yes. | **Find cover** (opens a Backup Matcher request; the server applies the same rule) |
| `UNCONFIRMED` | Assigned but not confirmed | **Request confirmation** / follow up |
| `SINGLE_POINT` | Covered, but the holder is the only eligible person and no backup is ready | **Ask … to stand by**, choosing from people one conversation away (over a limit or outside usual hours; never someone with a clash or a recorded absence). Once asked, the item shows “Waiting for … to confirm”, and the same request cannot be sent twice. |
| OK | Covered, with a ready confirmed backup or at least one eligible alternative | — |

A **confirmed backup** counts as ready even if they would be over their daily limit or outside their usual hours: they agreed to stand by, and standby adds no load until used. A recorded absence, a missing skill or a clash disqualifies them.

## Secure-by deadlines

| Importance | Secure this long before the start |
|---|---:|
| Critical | 72 h |
| High | 48 h |
| Medium | 24 h |
| Low | 12 h |

A deadline that would fall at night (20:00–08:00 local) moves to 20:00 the evening before. Once it has passed, the item says **Secure now**.

Severity: a gap is HIGH within 24 hours or for HIGH/CRITICAL tasks, and MEDIUM otherwise. An unconfirmed task is HIGH when it is soon and important. A single point is MEDIUM for important or soon tasks and LOW otherwise. Items are sorted by severity, then by deadline.

## Capacity by day and N-1

- Each local day is rated **Enough capacity**, **Tight** or **Not enough capacity**. Not enough means a task with no eligible caregiver, or Workload Balancer demand at HIGH. Tight means any open finding, or ELEVATED demand.
- **If someone is away:** for each person, the tasks that would have no alternative if they were unavailable (“If Savitha is unavailable, 2 tasks have no alternative …”).

## Measures

The 60-second scheduler logs **one row per task** (`coverage_findings`) while the task has any finding. The row keeps its latest `kind`, its `worst_kind`, and the secure-by time from when it was first flagged. Opening the screen is read-only. Each patient is processed in isolation, so one failure never rolls back other scheduler work. When the risk ends, the row closes with an outcome:

| Outcome | Meaning |
|---|---|
| `BEFORE_DEADLINE` / `AFTER_DEADLINE` | The risk cleared before the task, before or after its secure-by time |
| `STARTED_UNCOVERED` | A gap or unconfirmed task was still open when it started (unless a confirmation arrived after the planner's last look) |
| `NO_BACKUP_SECURED` | A single point reached its start without a backup (the task itself was covered) |
| `TASK_CLOSED` | The task was cancelled or completed |
| `OUT_OF_SCOPE` | Rescheduled beyond 7 days or no longer needs a caregiver (not counted as prevented) |

`GET /api/v1/patients/{id}/coverage-forecast/metrics?days=30` returns:
- All counts are of **tasks**, not log rows.
- **Future gaps identified before their deadlines:** count and % first flagged before their secure-by time (as set when first flagged), plus median warning time in hours.
- **Preventable uncovered activities:** tasks flagged *before* their deadline that still started uncovered. `started_uncovered` counts all of them. `gaps_prevented_pct` is the share of gap or unconfirmed tasks fixed before they started.
- Resolved before or after the deadline, and backups never secured.

## Access

Primary contacts and administrators can view and act. Family contacts can view only, and assignment IDs are withheld from them. Caretakers, nurses, doctors and patients get `403`.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/patients/{id}/coverage-forecast` | Horizons, findings with secure-by and suggestions, days, N-1 list |
| `GET /api/v1/patients/{id}/coverage-forecast/metrics?days=30` | Early-warning and prevention measures |

Actions reuse existing endpoints:
- Backup Matcher cover requests (with `only_if_uncovered`).
- Assignment `request-confirmation`.
- A `BACKUP` assignment followed by `request-confirmation` for a standby.

## Modules

- `engine/coverage_planner.py`: pure `forecast` and `secure_by`.
- Reuse of the Backup Matcher's `rank_in_context` and the Workload Balancer's `LoadContext`/demand.
- `services/coverage_planner.py`: snapshot, findings log, scheduler tick, metrics.
- `api/coverage_planner.py`.
- Model `CoverageFinding` and migration `0008_coverage_planner`.
- Frontend: `frontend/src/CoverageForecast.tsx`.

## Demo

Sign in as Anita and open **Coverage Forecast**. In the next 24 hours, three tasks are covered but each holder is the only eligible person. Ask the suggested person to stand by and the item clears once they confirm.

Further out:
- Saturday's nurse visit is a gap, because Divya does not work weekends and nobody else is a nurse.
- Saturday is rated **Not enough capacity**.
- “If Savitha is unavailable, 2 tasks have no alternative.”
