# CareCircle escalation and patient messaging

CareCircle routes a message to the right people. It does not diagnose or provide emergency care. In immediate danger, call **108 / 112**. Do not wait for an in-app response.

## Safety principles

- Route and record; do not diagnose. A level is a coordination route, not medical triage.
- Deterministic rules classify first and retain rule IDs and plain-language reasons. Unknown text goes to L2 for human review, never to the informational digest.
- Ambiguous or unrecognised text is not silently treated as informational. A later urgency advisor may only raise a level.
- Emergency reports use the L5 path and are recorded independently of routine care coordination. The SOS shortcut always sets L5.
- Audit and notification content contains a deterministic safe summary, never the patient's message text.
- Messages are capped at 1,000 characters, control characters are removed, and frontend rendering uses React text escaping.
- Role access is checked through patient membership before messages or incidents are created, listed, acknowledged, or resolved.

## Routing levels

| Level | Meaning | Intended route |
|---|---|---|
| L0 | Explicit positive update | Informational item; no interruption |
| L1 | Daily help | Personal caretaker |
| L2 | Logistics, support failure, or unclassified text | Primary contact decision |
| L3 | Health concern requiring review | Healthcare professional |
| L4 | Doctor-relevant concern | Doctor |
| L5 | Emergency report or SOS | All care-team roles at once; call 108/112 |

The API stores the level and creates in-app notifications for matched care-team members. A single-worker background tick runs every 15 seconds, applies persisted acknowledgement and resolution deadlines, and records transitions. Acknowledging stops the acknowledgement deadline and starts a resolution deadline. No in-app notification guarantees a response.

## Time boxes

At scale 1.0, acknowledgement deadlines are L1 10 minutes, L2 15, L3 30, L4 60, and L5 2. Resolution deadlines after acknowledgement are 30, 60, 90, 120, and 30 minutes respectively. HIGH severity halves a timer; LOW doubles it. `ESCALATION_TIME_SCALE` is honored only in demo mode, and the admin demo endpoint can change it at runtime. L1/L2/L3 advance one level when due; routine categories cap at L3 (L4 for critical linked activity), health/medication cap at L4. L4 re-notifies and alerts primary contacts without further automatic level progression. L5 notifies care-team roles together, repeats on its emergency cadence, and records an unacknowledged emergency after five scaled minutes.

The worker stores deadlines in the database and uses row locking with `SKIP LOCKED` for competing ticks. Docker explicitly runs one Uvicorn worker. Per-patient policy reads, bounded updates, reset, and the seeded system default are available. Quiet-hour settings are stored, but quiet-hour delivery suppression is not yet enforced.

## Classifier and lexicons

`backend/app/engine/escalation_classifier.py` is pure Python and has no database or web imports. It normalises Unicode NFC, lowercases text, collapses whitespace, and scans all configured phrase lists regardless of the language hint. Highest matching level wins, with deterministic modifiers for intensity, persistence, repeat context, mobility and SOS. Three-token negation near a red-flag phrase routes to L3 for human review. Third-person reports remain emergencies.

Phrase lists are in `backend/app/engine/lexicons/`. They cover English and selected Hindi, Kannada and Telugu phrases, including romanised variants. **These machine-drafted phrases need native-speaker review before real use.** Phrase matching is intentionally conservative and does not understand full linguistic context; it can miss paraphrases and can match a phrase in an unintended context.

`UrgencyAdvisor` and `NullAdvisor` provide an interface seam. There is no AI provider. Any advisor output must be bounded to levels 0–5 and can only raise the deterministic result.

## Privacy and roles

| Role | Current access |
|---|---|
| Patient | Create own message/SOS and see patient-safe incident status and redacted timeline |
| Personal caretaker / family contact | Submit on behalf of an accessible patient; read incident summaries only when notified |
| Primary contact | Read all incidents for coordinated patients and take coordination actions |
| Healthcare professional | Read L3+ incidents for team patients |
| Doctor | Read L4+ incidents for team patients |
| Administrator | Read all incidents and use permitted patient-scoped actions |

Incident responses expose the generated safe summary, not message text. Patient timelines omit internal notes and metadata. Notifications use safe summaries. Recipient filtering is coarse and based on care-team role plus notification records; there is no doctor summary or clinical instruction API yet.

## Operational limits

- Delivery is in-app only. There is no SMS or phone integration.
- Users need the application open to see current notifications; SSE and polling are not implemented.
- Quiet-hour delivery suppression, daily digest generation, rate limiting, and duplicate message merging are not implemented yet. The tick catches up ordinary level transitions in deadline order; clustered outage and multi-worker behavior has not been verified.
- Docker uses the project's current single Uvicorn process. No multi-worker scheduler lock exists.
- Classifier phrases need native-speaker review. Routing is not triage and cannot replace emergency services.
- The patient Help page, cancellable SOS countdown, call buttons, and Incident Center are implemented. The escalation policy page and demo speed/scenario panel are implemented. The full-screen alert modal, sound-unlock flow, offline queue, and language switch are not.
