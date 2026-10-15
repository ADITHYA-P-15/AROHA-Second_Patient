# Caretaker ratings and reputation (flag `ratings`)

Every directory caretaker shows a **composite reputation** built from four sources. Each source is shown and explained on the profile. The backend computes everything with the fixed formulas below. AI never ranks, rates or decides anything here.

The reputation summarises care-coordination records and ratings. It is not a medical or clinical assessment, and the persistent footer stays on every screen.

## The four sources

| Source | What it is | Who provides it |
|---|---|---|
| **Agency rating** | One 1–5 value per caretaker, shown with the agency name | Seeded data. There is no agency login, feed or import endpoint |
| **Doctor ratings** | 1–5 stars plus an optional note (300 characters at most) | A healthcare professional on the care team of a patient this caretaker served (linked to the patient, or completed at least one task for them) |
| **Family reviews** | 1–5 stars plus optional text (500 characters at most) | The primary contact (the main input); optionally the patient, shown separately and counted lower |
| **Reliability record** (metric) | 0–100 from our own records over a rolling window | Computed; nobody enters it |

The reliability record describes the caretaker. It is not the per-task score the Backup Matcher shows when finding cover. The UI labels that score **Fit for this task**.

## Rules for writing ratings

- **Eligibility for reviews:** the reviewer's patient must have had at least `min_completed_tasks` (default **5**) tasks completed by this caretaker, counting tasks they held as confirmed primary that ended COMPLETED. Without that relationship the API answers **403**.
- **Eligibility for doctor ratings:** the professional must be on the team of a patient this caretaker served. Otherwise **403**.
- **One per window:** one review, or one doctor rating, per author per caretaker per `rating_window_days` (default **90**). A second one inside the window is **409**.
- **Editing:** the author can edit for `edit_window_days` (default **7**). After that, **409**. Nobody else can edit, and nobody can delete anyone's review.
- **Reporting:** the review's author, the caretaker it is about, or anyone who can read review text (primary contacts, professionals) can report it for moderation, once per review (**409** on a repeat). A report never hides anything. Only a moderator's `hidden` flag, set at the database or seed level, hides a review. Hidden reviews never count.
- **Abuse limits:** at most `max_ratings_per_day` (default **10**) new reviews plus doctor ratings, and `max_reports_per_day` (default **10**) reports, per person per rolling day. Beyond that the API answers **429**.
- **Notifications:** the caretaker gets one in-app notification per new review or doctor rating, containing the stars only. It never says who wrote it. The notification is filed under the patient it concerns, because every notification belongs to a care circle.

## Who sees what

| Viewer | Reputation breakdown | Review text |
|---|---|---|
| Primary contact, professional | Any caretaker | Yes |
| Patient | Any caretaker | Stars and dates only |
| Caretaker | Their own only (403 for others) | Their own reviews only |

Review responses never include the author's identity, only "Family member" or "Patient".

## Formulas

All star values become 0–100 with **score(s) = (s − 1) / 4 × 100**: 1★ = 0, 3★ = 50, 5★ = 100.

### Shrinkage toward the sector mean

With *n* ratings averaging *m*, and the sector prior *p*:

**adjusted = (n·m + k·p) / (n + k)**, with **k = `shrinkage_k` = 3**

- *p* is the mean, over all caretakers in the same sector, of each caretaker's own average for that source (doctor ratings or family reviews).
- If the sector has none, *p* is the mean over all sectors. If there are none at all, *p* is 3★.
- So one 5★ review with a 3.6★ sector prior counts as (5 + 3·3.6)/4 = **3.95★**. One review cannot put anyone first.

### Doctor ratings

m = mean of the caretaker's doctor ratings; n = their number. The source score is score(adjusted).

### Family reviews

Each primary-contact review has weight 1. Each patient review has weight `patient_review_weight` (default **0.5**).

- **m = Σ(wᵢ·starsᵢ) / Σwᵢ**
- **n = Σwᵢ** (the effective count)
- The source score is score(adjusted).

The profile shows family and patient counts separately.

### Agency rating

The source score is score(rating). It is a single assessment, so it is not shrunk.

### Reliability record (metric)

Over the last `metric_window_days` (default **90**), take the tasks the caretaker held as confirmed primary that ended (COMPLETED or MISSED). Call that number *decided*. The components are:

| Component | Value | Default weight |
|---|---|---|
| Tasks completed on time | on-time completed / decided | 45 |
| Tasks not missed | 1 − missed / decided | 30 |
| On-time check-ins | on-time check-ins / check-ins | 15 |
| Cover offers accepted | accepted / (accepted + declined) cover offers in the window | 10 |

- **metric = 100 × Σ(wᵢ·valueᵢ) / Σwᵢ** over the components that have data.
- With fewer than `metric_min_tasks` (default **5**) decided tasks there is no metric score, and the profile says so.
- Late completions count as completed but not on time. Missed tasks are a separate component.
- **Check-ins:** this deployment does not record task check-ins yet (there is no `task_check_ins` table). The component shows "not recorded yet" and is left out, so the other three weights are renormalised. When check-ins are recorded, they are counted in `services/reputation.metric_counts`, and a check-in later than the task start plus `check_in_grace_minutes` (15) counts as late.

### Composite

**composite = Σ(Wₛ·scoreₛ) / ΣWₛ** over the sources that have a score.

- Default weights: **metric 40, doctors 25, customers 20, agency 15**.
- Missing sources are excluded and the remaining weights are renormalised. The profile lists the sources included and each one's share of the total.
- **"Not enough history yet":** shown when there is no composite. It is also shown when there are fewer than `min_ratings_for_history` (default **3**) reviews plus doctor ratings and no metric score. The number is still shown, marked as early.

## The rating prompt (management by exception)

When a caretaker reaches `min_completed_tasks` completed tasks with a patient, the scheduler's heavy pass creates **one** Command Center item for that patient, **Rate &lt;caretaker&gt;**, assigned to the lead primary contact. It also sends **one** in-app notification. The item:

- has one tap per star, with optional text;
- closes when the primary contact reviews the caretaker, or when they tap **Not now**;
- is created at most once per `prompt_repeat_days` (default **90**) per patient and caretaker, whatever happened to the last one, and not at all if they already reviewed in the window.

Patients get an optional, quiet prompt in their own Today view. It sends no notification.

## Snapshots

The same heavy pass writes one `reputation_snapshots` row per caretaker per local day, with the metric score, the composite and the full breakdown. A unique (caregiver, day) constraint and a check for today's rows make it idempotent across ticks and restarts. Profiles always compute live; snapshots keep the history.

## Policy: `core/reputation_policy.py`

All defaults live in `DEFAULT_POLICY`. Override any of them with the `REPUTATION_POLICY` environment variable, a JSON object. The `weights` and `metric_components` tables merge key by key. For example:

```
REPUTATION_POLICY={"weights": {"agency": 10}, "patient_review_weight": 0.4}
```

The policy is validated when the app starts. An invalid value stops start-up with "Invalid REPUTATION_POLICY: …". These are invalid:

- unknown keys;
- negative or non-numeric weights, or all-zero weights;
- `patient_review_weight` outside 0–1;
- non-integer windows and limits;
- an edit window longer than the rating window.

## API (all under `/api/v1`, flag `ratings`)

| Method and path | Who |
|---|---|
| `GET /caretakers/{id}/reputation` | Browse roles; a caretaker for themselves |
| `GET /caretakers/{id}/reviews?limit=&offset=` | As above. Text rules in "Who sees what" |
| `POST /caretakers/{id}/reviews` `{rating, text?, patient_id?}` | Primary contact, patient (eligible) |
| `PATCH /reviews/{id}` `{rating?, text?}` | Author, within 7 days |
| `POST /reviews/{id}/report` `{reason?}` | Author, the caretaker, primary contacts, professionals |
| `POST /caretakers/{id}/doctor-ratings` `{rating, note?, patient_id?}` | Professional (eligible) |
| `PATCH /doctor-ratings/{id}` | Author, within 7 days |
| `GET /patients/{id}/rateable-caretakers` | The patient's primary contacts, the patient, professionals |
| `GET /reputation/prompts` | The patient's quiet prompt |

When the flag is on, directory result cards and profiles carry a `reputation` summary.

## Data (migration `0017_reputation`)

The migration adds the tables `agency_ratings`, `doctor_ratings`, `reviews`, `review_reports` and `reputation_snapshots`. It is additive and guarded, and tested up, down and up again.

## Demo data

`seed/reputation.py` adds:

- an agency rating (2.5–5.0) for every agency caretaker;
- once the fictional population exists, about 300 fictional reviews and doctor ratings written by population families, patients and professionals. They range from none at all, to a single review, to well-reviewed and weak records. One review is moderator-hidden.

About half the population families reviewed their main caretaker recently. The rest get a **Rate** prompt. Everything is marked synthetic, and review text ends in "(fictional review)".

## Code

- `backend/app/core/reputation_policy.py`
- `backend/app/services/reputation.py`: pure functions first, then the database layer, eligibility, prompts and snapshots
- `backend/app/api/reputation.py`
- `backend/app/seed/reputation.py`
- `alembic/versions/0017_reputation.py`
- `frontend/src/Reputation.tsx`: the profile block, star picker, rating cards, quick rate and the patient prompt
- `frontend/src/lib/reputation.ts`
- Tests: `backend/tests/test_reputation.py`, `frontend/src/lib/reputation.test.ts`
