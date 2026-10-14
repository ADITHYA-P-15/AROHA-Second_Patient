# Workload Balancer

The Workload Balancer helps a primary contact spread care tasks fairly, keep each caregiver within their own limits, and reduce reliance on any one person. It reviews the next 7, 14 or 28 days for one patient, explains every finding, and offers one-tap moves. The basis note is always shown: “Based on assignments, recorded availability and each caregiver's configured limits. Recommendations change nothing until a primary contact applies one and the caregiver confirms.”

Load and demand describe **coordination capacity**, never the patient's clinical state. A quiet result says “No moves suggested right now”; it never says that care is safe.

## What it evaluates

| Input | Source |
|---|---|
| Capacity limits | `max_activities_per_day`, `max_hours_per_week` on each caregiver |
| Availability | Recurring weekly windows plus active overrides (`engine/availability.py`) |
| Task duration | Scheduled window including before/after buffers |
| Conflicts | Overlapping active primary commitments across **all** patients |
| Capabilities | `required_support` on the task vs the caregiver's recorded capabilities |
| Qualification | Delegation class (below) vs caregiver kind |

Active primary assignments (proposed, awaiting confirmation, confirmed) count as load; backups do not count until promoted. Other patients' work counts toward a caregiver's load but only appears as an aggregate number, never as titles, names, or patient identities.

## Caregiver status

| Status | Rule |
|---|---|
| `OVERLOADED` | Any day over the daily task limit, any ISO week over the weekly hours limit, or overlapping commitments |
| `NEEDS_REVIEW` | An assigned task falls outside the caregiver's recorded availability |
| `NEAR_LIMIT` | At the daily limit on some day, or at least 80% of weekly hours |
| `BALANCED` | Peak use between 50% and 80% |
| `HAS_CAPACITY` | Peak use under 50% |
| `INACTIVE` | Caregiver is deactivated |

`load_score` is the peak of daily-task and weekly-hour use as a percentage of the caregiver's own limit (133 = one third over). It is an operational ranking, not a health measure.

## Demand by day

For each local day the engine counts the patient's caregiver tasks and the network's **open task slots** (each available caregiver's daily limit minus their other-patient tasks that day).

- `HIGH`: no open slots, a professional-only task with no qualified professional available that day, or tasks use at least 80% of open slots.
- `ELEVATED`: at least 60% of slots, or at least three tasks and double the median day in view.
- `NORMAL`: otherwise.

## Delegation classes

| Class | Required support | Who may take it |
|---|---|---|
| `PROFESSIONAL` | `CLINICAL_VISIT` | A caregiver recorded as a nurse **and** holding the capability |
| `TRAINED` | `MEDICATION_ASSIST`, `MOBILITY_ASSIST` | Any caregiver whose recorded capabilities include it |
| `GENERAL` | All other support codes | Any available caregiver with the capability |

The mapping lives in `engine/workload_balancer.py` (`PROFESSIONAL_SUPPORT`, `TRAINED_SUPPORT`, `PROFESSIONAL_KINDS`) and is returned to the UI as `delegation_rules`. It reflects recorded configuration only; the tool does not judge clinical competence.

## Dependency findings

- `CONCENTRATED_LOAD`: one caregiver holds at least 60% (and at least three) of the patient's assigned tasks in view.
- `SINGLE_QUALIFIED_CAREGIVER`: only one active linked caregiver can cover a support code the plan needs.
- `NO_QUALIFIED_CAREGIVER`: nobody linked can cover it.

## Recommendations

1. **Overload pass.** For each overloaded caregiver, the engine picks this patient's tasks that cause the overload (double-booked first, then over-limit days, then over-limit weeks). It prefers general over trained over professional tasks, lower importance, unlinked tasks, and earlier start times. Tasks starting within two hours are not moved; arrange those directly.
2. **Hard checks** for each receiver: active and linked to the patient, qualification for the delegation class, every required capability, available for the full buffered window, no overlapping commitment, and still within daily and weekly limits after the move.
3. **Additive score** ranks the people who pass:

   | Factor | Points |
   |---|---:|
   | Passed every check | +40 |
   | Daily headroom after the move | up to +25 |
   | Weekly headroom after the move | up to +15 |
   | Already the confirmed backup for this task | +15 |
   | Designated backup for this patient | +10 |
   | Spreads the patient's tasks across more people | +5 |
   | Professional asked to do a general task | −15 |

4. Moves are applied to a working copy so later suggestions account for earlier ones (greedy, deterministic, stable tie-breaks by name and ID).
5. **Dependency pass** (LOW priority). For a concentrated caregiver, up to two LOW/MEDIUM general tasks are suggested for sharing.
6. When nobody qualifies, one `NO_ELIGIBLE_RECEIVER` card per overloaded day, week or double-booking lists every excluded person with the reasons and the other affected tasks (`unresolved_tasks`). Unresolvable work does not produce one card per task.

Each recommendation carries `reasons`, `score_breakdown`, up to three `alternatives`, `excluded`, and the before/after `effect` on both people's task counts. At most 20 suggestions are returned.

## Applying a move

`POST /api/v1/patients/{id}/workload-balance/apply` with `{activity_id, from_caregiver_id, to_caregiver_id, mode}`:

- The server re-validates everything against current data. The task must still be held by `from_caregiver_id` and the receiver must still pass every hard check; otherwise it returns `409` with the reasons. A stale screen cannot apply an outdated suggestion.
- Tasks starting within two hours are refused (`409`) even if a stale screen offers them; arrange those directly.
- The receiver's caregiver row is locked during the check, so two moves to the same person cannot together exceed their limits.
- The old primary assignment becomes `SUPERSEDED`; a receiver's backup slot on the same task is superseded as it is promoted.
- `REQUEST_CONFIRMATION` (default) creates an `AWAITING_CONFIRMATION` primary assignment and sends the receiver one inbox notification. **Confirmed cover is never dropped on a request:** if the previous primary was confirmed, they stay on the task as a confirmed **standby backup** (`confirmed_via = HANDOFF_STANDBY`). When the receiver confirms, the standby is released automatically. If the receiver declines, the previous caregiver is still the confirmed backup and the Command Center raises the declined assignment. Until confirmation, the plan shows **Not confirmed** for the primary.
- `CONFIRM_NOW` records a coordinator-confirmed assignment for a caregiver who has already agreed.
- The previous caregiver gets one low-severity inbox note, unless they made the change themselves. History records `workload.rebalanced` with both caregiver IDs, mode, and note. The existing `reassess` hook refreshes Command Center items in the same transaction.

## Access

| Role | Access |
|---|---|
| Primary contact (coordinator), Administrator | View and apply |
| Family contact | View only; assignment IDs are withheld |
| Personal caretaker, healthcare professional, doctor, patient | `403` (they use My Day and Care Plan) |

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/patients/{id}/workload-balance?days=7` | Loads, demand, dependency, recommendations, and delegation rules (`days` 1–28) |
| `POST /api/v1/patients/{id}/workload-balance/apply` | Coordinator applies a move after server re-validation |

## Modules

- `engine/workload_balancer.py`: pure, deterministic evaluation (`evaluate_workload`, `check_receiver`, `delegation_class`).
- `services/workload_balancer.py`: read-only snapshot builder (linked caregivers, schedules, overrides, the patient's tasks, and cross-patient commitments for the ISO weeks touched).
- `api/workload.py`: role scoping, apply transaction, notifications, and history.
- `frontend/src/WorkloadBalancer.tsx`: screen at `/workload`; `frontend/src/lib/workload.ts`: label helpers.

## Extension points

- **Resilience engine:** reuse `check_receiver` for N-1/N-2 stress tests and backup ranking.
- **Absence simulation:** run `evaluate_workload` on a snapshot with an absent caregiver's commitments removed.
- **Capacity planning:** aggregate the `demand` and `caregivers` outputs over history.
- **AI assistant:** may restate `reasons`; the engine decides eligibility and the coordinator applies changes.

## Demo

Sign in as Anita and open **Workload Balancer**. The seed gives her four tasks tomorrow against a daily limit of three, so the balancer suggests moving a transport task to Karthik. It also flags Divya's Saturday nurse visit as outside her weekday availability, and lists single-qualified dependencies. Tap **Ask Karthik Iyer to confirm**: the overload clears, and the task waits for Karthik's confirmation in Care Plan.
