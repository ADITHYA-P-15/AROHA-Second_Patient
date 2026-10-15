# Caregiver Command Center

The Command Center puts today's coordination work on one screen. It reports operational activity only. The basis text is always shown: “Based on confirmed assignments, availability and logged updates. This does not check on the patient's wellbeing.” An empty queue says “Nothing needs your attention right now”; it never says that the patient is safe.

## Starting rules

- Attention is deterministic and built from a server-side snapshot. Each item has a stable kind, severity, reason, affected activity IDs, and optional action suggestions.
- Routine work is collapsed only when it belongs to a series or an eligible routine category, is LOW/MEDIUM importance, has a confirmed primary, has no attention item, and is not overdue. The children remain available in the daily plan.
- A derived item is upserted by patient and dedupe key. When its condition clears, it becomes `AUTO_RESOLVED` with `CONDITION_CLEARED`; if it persists through a dismissal suppression window, it reopens and increments `reopened_count`. Snoozed items wake on the scheduler and are omitted from the open queue while snoozed. Manual reminders persist until a user marks them done.
- PostgreSQL reconciliation uses a transaction-scoped patient advisory lock. Writes and reconciliation share the caller's transaction. The existing single worker catches up daily briefs after restart and checks time-driven state every minute (the worker wakes every 15 seconds).
- Morning briefs are template generated and idempotent per date. Handover drafts are editable and publishable; a scheduled draft that remains unpublished is labelled “Auto-generated draft — not reviewed” when automatically published. Handover text is capped near 2,000 characters and HTML escapes notes.
- The frontend polls the existing API every 15 seconds; there is no SSE stream or event publisher in the repository.

## Exception taxonomy

| Kind | Trigger | Default severity | Current suggestion |
|---|---|---:|---|
| `UNASSIGNED_REQUIRED` | Required activity has no active primary | Activity importance | Assign a caregiver (coordinator flow) |
| `ASSIGNMENT_UNCONFIRMED` | Proposed / awaiting assignment starts within 12 hours or is pending over 4 hours | Activity importance | Request or confirm assignment |
| `ASSIGNMENT_DECLINED` | A caregiver declined and no primary is confirmed | Activity importance | Review replacement |
| `CAREGIVER_UNAVAILABLE` | Confirmed primary is unavailable in the buffered window | Activity importance | Pick a backup |
| `CAPABILITY_MISMATCH` | Confirmed primary lacks required support capability | Activity importance | Review assignment |
| `OVERLAP_CONFLICT` | Confirmed primary has an overlapping commitment | Activity importance | Review assignment |
| `OVER_LIMIT` | Configured daily or weekly workload limit is exceeded | Activity importance | Review workload |
| `DEADLINE_APPROACHING` | Deadline within 24 hours and no confirmed caretaker | Activity importance | Review due time |
| `TASK_OVERDUE` | Deadline passed while the task remains scheduled (doses and appointments within their grace time are not overdue) | HIGH | Mark complete or review |
| `TASK_UNACKNOWLEDGED` | Confirmed home task (not a dose or appointment) starts within 30 minutes without acknowledgement | Activity importance | Acknowledge task |
| `INCIDENT_OPEN` | Phase 3 incident remains open | Incident level mapping | Acknowledge / open incident |
| `INCIDENT_UNACKED_EMERGENCY` | L5 incident is not acknowledged | CRITICAL | Acknowledge incident |

Management by exception: a dose or appointment with a confirmed caretaker raises nothing until it is actually late or missed. Single points of failure belong to the Coverage Forecast, not to this list.

“Severity” and “at risk” describe coordination priority, not a clinical state or diagnosis. The current basic provider does not calculate resilience, travel time, true cross-patient candidate rankings, or N-1/N-2 coverage. Phase 5 will supply those through the provider boundary.

## Daily plan and actions

Day parts use the application timezone. Default boundaries are early 06:00, morning 08:00, afternoon 12:00, evening 17:00, and night 21:00; night spans 21:00–06:00. Same-assignee routine tasks in one part merge when the gap is at most 30 minutes. Overdue tasks break out as exceptions. The returned load is a patient-plan view in this phase; caregiver-specific largest-free-window calculations and candidate ranking are planned for the resilience work.

Action item mutations are authenticated and patient scoped. Derived HIGH/CRITICAL items cannot be dismissed. Dismissal requires a reason and a suppression period. Action routes recheck authorization and invoke existing assignment, task, incident, or acknowledgement routes when that integration is implemented. Unsupported multi-step options return a clear 422 rather than silently succeeding.

## Brief schemas

Morning `content` has `headline`, `if_you_only_do_three_things`, `key_times_today`, `on_duty`, `routine_plan`, `decisions_waiting`, `at_risk_next_48h`, `incidents_last_24h`, and `carry_overs`. The end-of-day schema has `done_today`, `carry_over`, `incidents`, `pending_actions`, `tomorrow`, `overnight_coverage`, `medication_support_completed`, and `notes`. Templates set `ai_enhanced=false`; no AI decision or clinical interpretation is involved.

The handover record supports recipient, acknowledgement, and per-item dispositions. Phase 4's screen provides draft, publish, and acknowledge paths. The finer editor controls and complete activity attribution can be extended for Phase 6 absence handovers.

## Role views and privacy

- Coordinator and administrator see the patient-level Command Center and authorized patient overview.
- A family contact receives a read-only, reduced view and may acknowledge a handover addressed to them.
- Househelp and nurses receive only their linked patient's My Day subset and addressed handovers. Patient and doctor roles receive 403 for this route.
- The payload does not include clinical notes or phone numbers. Handover free text is length limited, control characters are stripped, and HTML output is escaped.

## Extension points

- **Phase 5:** replace `evaluate_attention`'s basic provider with full coverage, eligible backup ranking, strain, and resilience providers while preserving `AttentionItem` and the API contract.
- **Phase 6:** reuse handover content and item disposition records for absence simulation and approved replacement plans.
- **Phase 7:** reuse the patient overview and daily plan contracts for forecasts, analytics, and capacity planning.
- **Phase 9:** optionally polish template wording. Structured facts remain backend generated; AI cannot confirm assignments, decide coverage, or clear an action item.

## Demo

Sign in as Anita or Admin using the configured demo password. Open **Command Center**. The admin demo panel offers **Command Center · messy day** to add synthetic same-day uncovered and unconfirmed tasks, and **Clear Command Center demo day** to cancel those scenario tasks. Add a reminder, reload, generate a morning summary, and create/publish a handover. Sign in as the addressed synthetic caregiver to acknowledge it.
