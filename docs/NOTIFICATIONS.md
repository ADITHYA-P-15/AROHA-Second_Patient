# Notifications and reminders

Every decision and every timed reminder reaches the people it concerns **as an alert**, not just a line in a list.

## How people are alerted

| Where | What happens |
|---|---|
| **Pop-up** | A card slides in at the top right within about five seconds. Urgent ones stay until dismissed; the rest fade after nine seconds. Tap one to open the right screen. |
| **Sound** | A short chime (softer for updates, a triple tone for urgent). Can be turned off. |
| **Desktop alert** | When the tab is in the background and permission is granted, the browser shows its own notification. |
| **Tab title** | `(3) CareCircle` shows the unread count. |
| **Bell** | The full list, newest first, with "Mark all read". |

Each person chooses how much pops up under the bell, **Alert settings**: every update, or important only (medium and high severity, or anything that needs an answer). The choice is stored in the browser.

## Who is told about what

| Event | Who is told | Severity |
|---|---|---|
| Medicine prescribed, changed or stopped | Family, patient, main caretaker | Medium |
| Appointment booked or cancelled | Family, patient, escort | Medium |
| You are given a task, or asked to confirm one | The caretaker | Medium |
| A caretaker confirms or declines a task | Family | Low / medium |
| A dose or visit is marked done | Family | Low |
| A caretaker takes leave or is marked unavailable | Family (and the caretaker if someone else did it) | Medium |
| A cover offer, accepted or declined | Family, the caretaker, the person offered | Medium |
| Workload move applied | The caretakers involved | Low |
| Main caretaker changed, someone added to or removed from the care team, CareCircle ID changed | The person, and the family | Low / medium |
| Patient sends a request or voice note | Whoever the level routes to (caretaker, family, healthcare team, everyone) | Level based |
| Patient says "I'm fine" or took a medicine | Family | Low |
| Someone acknowledges a request | The patient ("Someone is on it") and the other recipients | Medium |
| A request is resolved | The patient | Low |
| A dose is missed | Family and the assigned caretaker | High |
| An ambulance is being called | The whole care team and the patient | High |
| The same request tapped again | The same recipients, once per repeat ("Asked again") | Medium |

The person who made the decision is never told about their own action.

## Timed reminders (sent once per person)

| Reminder | When | To |
|---|---|---|
| Dose due | 15 minutes before | The caretaker holding it |
| Appointment | Within a day, and again within two hours | Escort, family, patient |
| Nobody confirmed yet | Doses 3 hours before, visits 24 hours before | Family |
| Cover offer unanswered | After 30 minutes | The caretaker it was offered to |

The scheduler runs every minute, so reminders arrive within about a minute of their time. A reminder is stored once per person (`dedupe_key`), however often the scheduler runs.

## Limits

- Alerts arrive while CareCircle is open in a browser tab (a background tab is fine). If the browser is closed, nothing can be shown until it is opened again.
- Reaching a closed phone needs web push (a service worker and push keys) or SMS. SMS has a hook in `care_status._on_missed` and is planned.
- Pop-ups poll every five seconds. That is simple and works through any network; it can be replaced by a live stream later.
