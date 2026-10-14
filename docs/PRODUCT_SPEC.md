# CareCircle — Product spec (pivot, 2026-10-14)

CareCircle puts every **medication dose** and **appointment** for a patient in one place, so that the **caretaker** no longer has to remember them, and the family and the hospital can see what was done, what is due and what was missed.

## Roles (exactly four)

| Role | Who | What they do in CareCircle |
|---|---|---|
| **Patient** | The person receiving care | Limited view: today's doses and appointments, ask for help (messages / SOS), see their own requests. |
| **Primary contact** | A blood relative (son, daughter, father …) | Registers the patient, invites caretakers, oversees everything: Command Center, coverage forecast, workload, cover requests, history. Notified when something is missed or cannot be covered. |
| **Caretaker** | The person who carries out the care activities | My Day (doses and appointments to do, mark them done), take leave / "I can't make it", accept or decline cover offers, availability. |
| **Healthcare professional** | A person from the hospital side (doctor or nurse) | Finds a registered patient, **prescribes medicines and dosages**, **schedules appointments**, follows adherence (missed doses), receives health-related escalations. |

There is no administrator role. Demo data is created by the seed. Doctor and nurse are both *healthcare professional*.

## Core flow

1. **Register.** A primary contact signs up and registers the patient (name, birth year, notes). The patient gets a **CareCircle ID** (for example `CC-7K3M9Q`). Optionally the patient gets their own login.
2. **Connect the hospital.** The primary contact shares the CareCircle ID with the hospital. A healthcare professional **finds the patient by CareCircle ID + birth year** and joins the patient's care team. Sharing the ID is the family's consent, and the primary contact can remove a professional at any time.
3. **Connect caretakers.** The primary contact invites caretakers (existing CareCircle accounts) by email. Each caretaker gets a care profile: capabilities, daily/weekly limits, availability.
4. **Medication data feed.** The professional prescribes a medicine: name, dose, instructions, times of day, start and end dates. CareCircle generates one **dose activity** per due time.
5. **Schedule data feed.** The professional schedules an appointment: title, place, date and time, preparation notes. CareCircle creates an **appointment activity**, which needs a caretaker to escort.
6. **Care activities.** Every dose and appointment has: date and time, a deadline, status, assigned caretaker, who completed it and when, and notes.
7. **Status from the clock.** The scheduler compares each activity's deadline with the current time:
   - `PENDING`: not done and the deadline has not passed.
   - `COMPLETED`: marked done by the caretaker (or recorded by the primary contact). A dose recorded after its deadline is kept as *completed late*.
   - `MISSED`: the deadline passed and it was not done. A dose is missed 60 minutes after its due time; an appointment is missed at its start time.
   - `CANCELLED`: cancelled by the prescriber / scheduler or the primary contact.
8. **Automatic cover.** When a caretaker takes leave, says "I can't make it", or is over their workload limit, CareCircle automatically offers each affected activity to the best eligible caretaker (Backup Matcher ranking). If they decline, it moves to the next. The replacement must accept before the activity counts as covered, and the original caretaker keeps it until then. The primary contact is told only when nobody can take it.
9. **Look ahead.** The coverage forecast (24 h / 3 days / 7 days) flags activities with no confirmed caretaker or only one eligible caretaker, with a secure-by deadline.

## Future (designed for, not built yet)

- **SMS on miss:** when a dose or appointment becomes `MISSED`, send an SMS to the assigned caretaker and the primary contact. Status changes already go through one place (`services/care_status.py`), which will be the hook.

## Kept, mapped to roles

| Capability | Primary contact | Caretaker | Professional | Patient |
|---|:-:|:-:|:-:|:-:|
| Register patient, invite caretakers | ✓ | | | |
| Find patient by CareCircle ID, join care team | | | ✓ | |
| Prescribe medicines, schedule appointments | | | ✓ | |
| My Day (do / mark doses and appointments) | view | ✓ | | today only |
| Care plan (all activities and statuses) | ✓ | own | ✓ | read |
| Leave / "I can't make it" / availability | | ✓ | | |
| Cover offers (accept/decline) | (if also caring) | ✓ | | |
| Cover requests, workload balancer, coverage forecast | ✓ | | | |
| Command Center (exceptions) | ✓ | My Day | | |
| Help / SOS and incidents | receives | receives | receives health escalations | sends |
| History | ✓ | | ✓ | |

## Cut

Admin role and admin demo panel, demo scenario endpoints, the duplicate Dashboard page, morning briefs and handovers, the escalation-policy editor (defaults stay), placeholder screens (AI assistant, risk graph, voice notes), caregivers without app accounts, and the clinical-visit capability (professionals prescribe and schedule; caretakers carry out the work).
