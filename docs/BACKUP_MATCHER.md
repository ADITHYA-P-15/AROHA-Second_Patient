# Capability-Aware Backup Matcher

**Pain point:** finding a replacement means repeated calls and manual delegation.
**Solution:** when a caregiver declines a task or reports an absence, CareCircle opens a **cover request**. It ranks every linked caregiver, explains each one in a sentence, and lets the primary contact ask the best match in one tap. If that person says no, it can ask the next best match automatically. A task counts as covered only after the replacement **accepts** and a **confirmed** primary assignment exists for them.

> Example: “Suresh Kamath can provide transport and is available 09:00–10:00.” · “Busy Bala is already committed at that time.” · “Savitha is available but lacks the transport capability.”

## When a cover request opens

| Trigger | Detected when | `reason` |
|---|---|---|
| A caregiver declines an assignment | The latest primary assignment is `DECLINED` and no active primary remains | `DECLINED` |
| A caregiver reports an absence | A confirmed primary's buffered window is blocked by an active `UNAVAILABLE` override (Care Network, or **I can't make it** in Care Plan) | `ABSENCE` |
| The primary contact asks | **Find cover** in Care Plan or Command Center | `MANUAL` |

- Detection runs inside the existing `reassess` hook, so it shares the transaction that recorded the decline or absence. The 60-second scheduler tick also runs it for upcoming tasks (60 days ahead, matching where **I can't make it** is offered).
- Each trigger has a deterministic `trigger_key` (`decline:<assignment>`, `absence:<override>:<assignment>`), so it opens at most one request, ever. Overrides are read in `(start_at, id)` order, so the key is stable. Closing a manual request records the decline or absence present at that moment, so it does not reopen.
- A partial unique index allows only one open request per task.
- During an absence the absent caregiver keeps the task until someone confirms, so cover is never silently dropped. If the absence is cancelled, the request closes as `CANCELLED` ("available again").

## Ranking (`engine/backup_matcher.py`)

Every caregiver linked to the patient is assessed on the same load model as the Workload Balancer, with other patients' commitments counted but never shown.

| Status | Meaning | Headline example |
|---|---|---|
| `ELIGIBLE` | Passes every check | “Anna can provide transport and is available 10:00–11:00.” |
| `AT_LIMIT` | Would exceed their daily task or weekly hour limit | “… would exceed their daily limit (2/1 tasks).” |
| `COMMITTED` | Overlapping commitment, buffers included | “… is already committed at that time.” |
| `UNAVAILABLE` | Outside recorded availability or on a recorded absence | “… is not available 10:00–11:00 (recorded absence).” |
| `MISSING_CAPABILITY` | Lacks a required support capability | “… is available but lacks the transport capability.” |
| `NOT_QUALIFIED` | Professional-only task; caregiver is not a nurse | “… is not recorded as a healthcare professional; this task needs one.” |
| `DECLINED_REQUEST` | Already said no to this request | “… already said no to this request.” |
| `INACTIVE` / `REPLACED` | Deactivated, or the person being replaced | |

When several checks fail, the headline uses the most fundamental reason (capability before availability before commitments). All the reasons are still listed.

**Travel buffers, where known:** the task's own before/after buffers are part of every overlap check. A commitment within 30 minutes of the buffered window is flagged as a *tight connection* and costs points.

**Score (eligible people only), additive and documented:**

| Factor | Points |
|---|---:|
| Passes every check | +40 |
| Daily headroom with this task | up to +15 |
| Weekly headroom with this task | up to +10 |
| Already the confirmed backup for this task | +25 |
| Has covered this recurring task before (90 days) | +15 |
| Designated backup for this patient | +10 |
| Supported this patient recently (2 per task) | up to +10 |
| Has done this kind of task for this patient | +5 |
| Professional asked to do a general task | −15 |
| Tight connection (< 30 min gap) | −10 |

Eligible people are sorted by score, then name. The rest are grouped by status. The score is an operational ranking, not a clinical measure.

## Lifecycle

```
OPEN ──offer──▶ OFFERED ──accept──▶ COVERED (resolution MATCHER)
  ▲                │
  └──── decline ◀──┘  (auto-advance offers the next best match when enabled)
OPEN/OFFERED ──task confirmed by other means──▶ COVERED (resolution MANUAL)
OPEN/OFFERED ──cancel / task cancelled / absence withdrawn──▶ CANCELLED
OPEN/OFFERED ──task starts uncovered──▶ EXPIRED
```

- **Offer:** the server re-checks the person and refuses with `409` and their headline if they no longer qualify. They get one inbox notification. Only one offer is outstanding at a time.
- **Accept:** done by the offered caregiver in the app, or by the primary contact recording a yes (for example after a phone call). The server re-checks eligibility again. It then supersedes the previous primary (and the person's own backup slot), creates a `CONFIRMED` primary assignment (`confirmed_via` `CAREGIVER` or `COORDINATOR`), and closes the request. The previous caregiver and the primary contacts get one low-severity note.
- **No answer:** an offer times out after min(2 h, half the time left before the task), never under 15 minutes. A timed-out offer is treated as a “no”.
- **No app:** if auto-advance reaches someone without an app account, the primary contacts get one “Please call …” prompt so the offer is never silent.
- **Withdrawn prompts:** when a request closes, or someone else covers it, the person holding an offer gets one “no longer needed” note and their prompt is cleared.
- **The original caregiver confirms after all:** an open request closes as `CANCELLED`, so they are never replaced afterwards.
- **Workload Balancer standby:** a standby backup row (`HANDOFF_STANDBY`) on the task is released when cover is accepted.
- **Decline:** the person is excluded from this request. With **auto-advance** on (the default), the next best eligible person is offered immediately (`AUTO_ADVANCED`). Otherwise the request returns to `OPEN` and the primary contacts get one notification. Every step is in the request's event trail and in History.

## Measures

`GET /api/v1/patients/{id}/cover-requests/metrics?days=30`

- **Time to secure a replacement:** from request opened to replacement confirmed (median and mean minutes over `COVERED` requests).
- **Resolved without manual searching:** requests covered through a matcher offer (`resolution = MATCHER`) as a share of requests that ended covered or expired. Covering a task some other way counts as `MANUAL`.
- Also returned: opened, open, covered, covered via matcher, covered manually, expired, cancelled.

## Access

| Role | Can |
|---|---|
| Primary contact (coordinator), Administrator | View all requests, rankings, metrics; open, offer, record yes/no, close |
| Family contact | View requests and rankings |
| The offered caregiver (any role with a caregiver profile) | See **their own** offer (task, patient, time — no other candidates or reasons), accept or decline |
| Others | `403` |

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/patients/{id}/cover-requests?status=open\|closed\|all` | Requests; open ones include the live ranking |
| `GET /api/v1/patients/{id}/cover-requests/metrics?days=30` | Time to secure and matcher resolution rate |
| `POST /api/v1/activities/{id}/cover-requests` | Primary contact opens a request (idempotent per task) |
| `GET /api/v1/cover-requests/{id}` | Full detail, ranking and event trail (offered caregiver: reduced view) |
| `POST /api/v1/cover-requests/{id}/offer` | `{caregiver_id, auto_advance}` |
| `POST /api/v1/cover-requests/{id}/accept` | Offered caregiver: `{}`; primary contact recording a yes: `{caregiver_id}` |
| `POST /api/v1/cover-requests/{id}/decline` | `{reason}`; triggers auto-advance |
| `POST /api/v1/cover-requests/{id}/cancel` | `{reason}` |
| `GET /api/v1/cover-offers/mine` | Offers waiting for the signed-in caregiver |

## Screens

- **Cover Requests** (`/cover`):
  - offers for you, with **I can do it** / **I can't**;
  - metric chips;
  - open requests with ranked people, one-sentence reasons, **Ask** / **They agreed — confirm** / **Record yes / no**;
  - recently closed requests.
- **Care Plan:** **Find cover** (primary contact), and **I can't make it** on a caregiver's own confirmed task, which records an absence for that window.
- **Command Center:** for primary contacts, action buttons now do what they say. **Find cover** sends `only_if_uncovered`, so a stale card cannot start replacing a caregiver who has since confirmed. The buttons: **Find cover** for unassigned, declined or unavailable tasks, **Rebalance** for over-limit items, **Request confirmation**, **Acknowledge**, or open the right screen.

## Modules and extension points

- Modules: `engine/backup_matcher.py` (pure), `services/backup_matcher.py` (lifecycle, detection, metrics), `api/backup_matcher.py`, `models.CoverRequest` / `CoverRequestEvent`, migration `0007_backup_matcher`, `frontend/src/CoverRequests.tsx`, and `frontend/src/lib/cover.ts`.
- **Absence simulation:** call `rank_candidates` on a snapshot with a caregiver's commitments removed.
- **Resilience (N-1):** rank candidates for every task of one caregiver to find tasks with zero eligible backups.
- **Travel time:** when locations are recorded, add a travel-time term next to the 30-minute gap rule.
- **AI assistant:** may restate headlines; it never offers, accepts, or marks a task covered.

## Demo

1. Sign in as **Karthik** → Care Plan → **I can't make it** on *Lab visit*.
2. Sign in as **Anita** → **Cover Requests**: “2 of 4 people in the network can take this.”
   - Suresh can provide transport; Savitha and Divya lack transport.
   - Tap **Ask Suresh Kamath**, then **Record yes**. The task is covered, and the metrics show the time to secure and 100% resolved via the matcher.
3. In Command Center, **Find cover** on the weekend nurse visit shows an honest “No one in the network can take this right now”. The visit is professional-only and the only nurse is off that day.

## Reputation and preference points (Phase 3, flag `team_builder`)

With the team builder on, eligible people get extra additive points on top of the continuity points above. The weights live in `core/matcher_policy.py` and can be overridden with `MATCHER_POLICY` (JSON, validated at start-up; a whole number from 0 to 40 each).

| Term | Default | Rule | Label in the breakdown |
|---|---|---|---|
| Reputation | +/-10 | round(10 x (composite - 50) / 50). Unrated: **0, labelled neutral**, never a penalty | "Reputation 82/100" / "Reputation: no rating yet (neutral)" |
| Reliability record | +/-8 | round(8 x (metric - 50) / 50). No metric yet: 0 (neutral) | "Reliability record 70/100" |
| Same city | +5 | The caretaker's listed city equals the patient's preferred city | "Lives in Pune, the patient's city" |
| Same region | +2 | Only when the city does not match: same sector | "Lives in the patient's region" |
| Language | +6 | Speaks any preferred language | "Speaks Tamil" |

- **Hard rules do not change.** Availability, overlaps (with buffers), capabilities, limits, professional-only tasks and an earlier "no" still decide eligibility. Reputation only reorders people who already pass them, so no amount of reputation buys a missing skill or a clash.
- Preferences only add points; they never filter anyone out of cover. (Gender is a filter in Find & build team, not a matcher rule; the earlier hard/soft gender setting was removed.)
- Ties keep the existing deterministic order: score, then name, then id.
- The same ranking serves every reason: decline, absence, manual, unassigned and **NO_CHECKIN** (a missing check-in, see [CHECKIN.md](CHECKIN.md)).
- Cover Requests and Care Plan show the same breakdown. The per-task score is labelled **Fit for this task** and is never called reputation.
- **Pool expansion:** when nobody on the care team is eligible, the ranking adds up to three `suggestions`. These are the best listed directory caretakers in the patient's preferred region with the needed skills, each with "Send a request to Priya?". They are never added to the team and never offered the task. Only a primary contact's hire request and the caretaker's acceptance can bring them in.
- With the flag off, the snapshot carries no `extras` and the matcher behaves exactly as before.

### The same logic when building a team

**Find & build team** ranks directory caretakers for a patient with the points above:
- reputation and reliability record (neutral when unrated);
- same city or region;
- language;
- **+4 per support need of the patient** they can help with (`need_covered`), from the patient's support needs plus the must-have skills;
- **-5 "Little free time this week"** (`little_capacity`) when they are already at their limits or have no free hours in the next 7 days.

Must-have skills and the family's minimum reputation are hard rules: people who fail them are not shown. Every directory filter narrows the list first: sector, agency, agency rating, state, city, gender, language, skill, experience and availability on a date. The top matches come first, best first, each with its reasons. Nobody joins without a hire request and their acceptance.
