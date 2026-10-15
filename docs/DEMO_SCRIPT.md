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

### Part 2 — the bigger picture (about 5 minutes)

The app also ships with a practical-size population: 24 more patients with families, 12 caretakers, 5 more hospital staff and a month of dose history. See [DEMO_PEOPLE.md](DEMO_PEOPLE.md) for every account.

| # | Sign in as | Go to | Show | Point to make |
|---|---|---|---|---|
| 13 | Dr. Kavita Rao (`kavita.rao@carecircle.demo`) | **Insights** | Doses given, missed doses, follow-up suggested, a daily chart, and a ranked patient list. Switch between 7, 14 and 30 days. | A professional with many patients sees who needs a phone call first, instead of opening each chart. |
| 14 | Dr. Kavita Rao | Insights → **Follow-up suggested** | Select the band; read why each patient is flagged ("9 doses not recorded as given in the last 7 days"). Open **Medicines** from a row. | Flags are plain, deterministic rules (3+ missed doses in a week, or under 75% given). They are about coordination, not diagnosis. |
| 15 | Dr. Kavita Rao | **Insights** → **Export CSV**; then **Patients** → search | A spreadsheet-ready list; search by name or CareCircle ID. | Practical for clinic review meetings. |
| 16 | Vikram Krishnan (`vikram.krishnan@carecircle.demo`) | **Command Center** | A different family sees only their own patient, with only what needs them. | Many families on one system, nothing shared between them. |
| 17 | Anjali Verma (`anjali.verma@carecircle.demo`) | **My Day** | Her own patients' doses in one list. | Each caretaker sees only their own work. |

### Part 3 — voice notes and the ambulance button (about 3 minutes, needs the AI keys in `.env`)

| # | Sign in as | Go to | Show | Point to make |
|---|---|---|---|---|
| 18 | Ramesh (`ramesh.iyer`) | **Request Help** → **Record a voice note** | Speak a sentence in Hindi, Kannada, Telugu or English, then stop. | No typing and no phone call, in his own language. |
| 19 | Ramesh | The preview | The words he said, the **English**, and **Who will be told**. Correct a word and press **Check again**. | He verifies before anything is sent. A mis-heard word is fixable, and the English re-check can raise urgency. |
| 20 | Ramesh | **Yes, this is right. Send it** | Sent. | Only now is the care team told. |
| 21 | Anita (`anita.iyer`) | **Help Requests** | The request with player, spoken text, English and the assistant's reason, and **Call ambulance · 108**. | The assistant can only raise urgency; the rules and a person decide. |
| 22 | Anita, then Savitha | Press **Call ambulance**, then Savitha's bell | Savitha is told "Ambulance being called". | The family acts in one tap, and nobody calls twice. |

Run **Reset demo data** afterwards: test voice notes create real requests.

Dr. Arjun Nair (`dr.arjun.nair`) also has Insights: Ramesh plus several of the larger population's patients.

Optional extras:
- **Leave:** as Savitha, open **My Day → Take leave** for tomorrow evening. Her evening dose is offered to Lakshmi.
- **Change caretaker:** as Anita, in **Care Plan** press **Change caretaker** on any upcoming item, pick someone, or let CareCircle find someone.
- **Availability:** as Anita, **Caretakers** shows each person's skills, usual hours and limits.

Press **Reset demo data** to run it again. It rebuilds Ramesh and Sharada only; the larger population is never touched.

## Things to say about safety

- Operational tool only. It is not a diagnosis or an emergency service, and the footer says so on every screen.
- All people and data are fictional and labelled as demo data.
- Decisions (status, who covers, what is flagged) are made by deterministic backend rules that can be explained; nothing is decided by AI.
- Planned next: SMS to the caretaker and family when something is missed (hook: `services/care_status._on_missed`).

## Directory phase 3 in 3 minutes: build a team, hire, and a reputation-ranked backup

Before you start, for a live demo of the missed check-in, run with a shorter allowance:

```
CHECKIN_POLICY={"grace_min": 0, "missing_after_min": 0}
```

The scheduler checks about once a minute.

1. **Set preferences (30 s).** Sign in as `anita.iyer@secondpatient.demo` and open **Build care team**. Set Kannada as the language, Bengaluru as the city, a minimum reputation of 60, and Transport as a must-have skill. Save. The matches re-rank, and each "why" line names the points it earned. Tick three and show **Compare**.
2. **Send a hire request (20 s).** Pick a Bengaluru caretaker, choose **Backup pool**, add a short note and send. Point out the status line ("Waiting ... in the app") and that no phone number is shown anywhere yet.
3. **The caretaker accepts and the phone appears (40 s).** In another browser, sign in as that caretaker with password `Demo@1234`; the email is in Find caretakers or [DEMO_PEOPLE.md](DEMO_PEOPLE.md). Open **Hire requests** and tap **Accept**. Back as Anita, open **Care Team** and **Caretakers**: the new backup is listed with their (fictional) phone. Find caretakers shows "On your care team".
4. **A caretaker misses a check-in (40 s).** As Anita, add an appointment starting now in Care Plan and assign it to Savitha (confirm now). Savitha does not tap **I'm here**. Within about a minute, **Cover Requests** shows the task with the reason **No check-in**.
5. **A reputation-ranked backup accepts (50 s).** Open the request's **Why**. The new backup ranks above others thanks to "Reputation .../100", "Lives in Bengaluru, the patient's city" and "Speaks Kannada", next to the usual availability and continuity points. With automatic coordination on, the best match is offered automatically (otherwise tap Offer). As the backup, accept in Cover Requests. The task is covered only after that acceptance.

Close by saying the ranking is computed from records and ratings, never by AI, and is not a medical judgement. Also say what is not built: no SMS, check-ins are detected about once a minute, and there is no moderator screen.
