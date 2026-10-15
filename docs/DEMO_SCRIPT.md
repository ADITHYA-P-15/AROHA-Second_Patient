# CareCircle demo script

A 10-minute walkthrough of the whole flow with the fictional demo data. Every account uses the password `Demo@1234` and ends in `@secondpatient.demo`. On the login screen, the **Demo accounts** chips fill in the email for each role.

## Before you start

1. Open `http://<LAN-IP>:8000` (or `http://localhost:8000`).
2. Sign in as any demo account and press **Reset demo data** at the bottom of the menu. This rebuilds the story relative to the current time, so the demo looks the same whenever you run it. Logins stay the same.
3. Use two browser windows (or one normal and one private window) if you want to show two people at once, for example the caretaker and the family.

## The story

**Ramesh Iyer**, 72, lives with a walking aid. His daughter **Anita** registered him and is his primary contact; his son **Karthik** is the second primary contact.

- **Dr. Arjun Nair** prescribed Metformin 500 mg at 08:00 and 20:00, and Amlodipine 5 mg at 09:00.
- Dr. Arjun also booked a **Cardiology follow-up** tomorrow at 10:30 and a **Physiotherapy session** in three days.
- **Savitha** is the main caretaker and does every dose and visit.
- **Lakshmi** is a trained backup, and **Suresh**, a neighbour, can escort to appointments.
- Yesterday every dose was given except the **20:00 Metformin**, which was missed.

The second patient, **Sharada Pai** (primary contact Meera, Dr. Divya Menon), shares Savitha. That's why Savitha's My Day shows two patients.

## Walkthrough

| # | Sign in as | Go to | Show | Point to make |
|---|---|---|---|---|
| 1 | Anita (`anita.iyer`) | **Command Center** | Only one item needs attention: yesterday's missed Metformin. | Management by exception: everything else is on track, so nothing else is shown. |
| 2 | Anita | **Care Plan** | Days grouped as Yesterday / Today / Tomorrow. Each row shows the time, the medicine or appointment, its status and the caretaker. Use the **Needs attention** filter. | One place for every dose and appointment. Status is set by the clock: Pending → Done, or Missed an hour after the due time. |
| 3 | Anita | Care Plan, missed dose | **Record as done (late)** (allowed for 24 hours). | A missed item can be corrected; it is kept as "done late" in adherence. |
| 4 | Dr. Arjun (`dr.arjun.nair`) | **Medicines & Appointments** | Adherence at the top (one missed Metformin dose). Open **+ New prescription**, add e.g. *Vitamin D 1000 IU at 13:00*, then **Prescribe**. | The hospital feeds the plan directly. Each dose appears in the caretaker's day automatically. |
| 5 | Dr. Arjun | **Patients** | Ramesh is on the list. *Optional:* find Sharada with CareCircle ID `CC-SHA746` and birth year `1946` (Dr. Arjun is not yet on her team). | The family shares the CareCircle ID; the professional joins with the ID and birth year. |
| 6 | Savitha (`savitha`) | **My Day** | Today's doses for both patients in one list. Press **Done** on a dose that is due. | The caretaker no longer has to remember anything. |
| 7 | Savitha | **Care Plan** → tomorrow's **Cardiology follow-up** | **I can’t make it** → confirm. The row now says *Finding cover*. | One tap. Savitha keeps the visit until someone accepts, so nothing is dropped. |
| 8 | Lakshmi (`lakshmi`) | **My Day** | *Can you help?* shows the Cardiology follow-up. Press **I can do it**. | The best eligible backup is asked automatically (skills, hours, workload). |
| 9 | Anita | **Care Plan** | The visit now shows **Caretaker: Lakshmi Rao**. **Cover Requests** shows it under recently closed. | The family was not interrupted, because the system solved it. |
| 10 | Ramesh (`ramesh.iyer`) | **Today**, then **Request Help** | Read-only day. Tap **I missed my medicine**. | Limited, simple view for the patient. Messages are routed by rules, not AI. |
| 11 | Savitha | **Help Requests** | The medicine request appears. **I’ve got this** → **Mark handled**. | The caretaker is asked first; it goes to the family if nobody answers in time. |
| 12 | Anita | **Coverage Forecast** and **Workload Balancer** | Nothing to secure, and one suggestion to share Savitha's load with Lakshmi. | Planning ahead: gaps and single points of failure are flagged before they happen. |

Optional extras:
- **Leave:** as Savitha, open **My Day → Take leave** for tomorrow evening. Her evening dose is offered to Lakshmi.
- **Change caretaker:** as Anita, in **Care Plan** press **Change caretaker** on any upcoming item, pick someone, or let CareCircle find someone.
- **Availability:** as Anita, **Caretakers** shows each person's skills, usual hours and limits.

Press **Reset demo data** to run it again.

## Things to say about safety

- Operational tool only. It is not a diagnosis or an emergency service, and the footer says so on every screen.
- All people and data are fictional and labelled as demo data.
- Decisions (status, who covers, what is flagged) are made by deterministic backend rules that can be explained; nothing is decided by AI.
- Planned next: SMS to the caretaker and family when something is missed (hook: `services/care_status._on_missed`).
