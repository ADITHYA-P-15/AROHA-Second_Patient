# Feature log

Cumulative record of features built one at a time on top of the phased roadmap in [ARCHITECTURE.md](ARCHITECTURE.md). Each entry lists what shipped, where it lives, and what later features can reuse. Newest last.

## Baseline before feature work

| Phase | Shipped | Key modules |
|---|---|---|
| 1 | Auth, RBAC, audit history, LAN deploy | `main.py`, `core/` |
| 2 | Patients, caregivers, availability, activities, assignments | `api/domain.py`, `engine/availability.py`, `engine/workload.py` |
| 3 | Escalation engine, patient messaging, incidents, notifications | `engine/escalation_*.py`, `services/escalation.py` |
| 4 | Caregiver Command Center: attention items, daily plan, briefs, handovers | `engine/attention.py`, `services/command_center.py`, `api/command_center.py`, `CommandCenter.tsx` |

## Feature 2 — Workload Balancer

- **Goal:** spread caregiving fairly, prevent overload, reduce dependency on individual caregivers.
- **Shipped:**
  - Per-caregiver load against their own daily and weekly limits, across patients.
  - Demand by day and dependency findings.
  - Delegation classes: general, trained, and professional-only.
  - Greedy, explainable redistribution suggestions with additive scores, alternatives, and exclusion reasons.
  - One-tap apply that is re-validated on the server: request confirmation, or confirm now.
- **Code:**
  - `backend/app/engine/workload_balancer.py`
  - `backend/app/services/workload_balancer.py`
  - `backend/app/api/workload.py`
  - `frontend/src/WorkloadBalancer.tsx`
  - `frontend/src/lib/workload.ts`
- **Tests:**
  - `backend/tests/test_workload_balancer_engine.py`
  - `backend/tests/test_workload_balancer_api.py`
  - `frontend/src/lib/workload.test.ts`
- **Docs:** [WORKLOAD_BALANCER.md](WORKLOAD_BALANCER.md) and the README section "Feature — Workload Balancer".
- **Schema:** none (reads existing tables).
- **Reuse later:**
  - `check_receiver` for backup ranking and N-1/N-2 stress tests.
  - `evaluate_workload` on a modified snapshot for absence simulation.
  - The `demand` and `caregivers` outputs for capacity planning.
- **Not yet:**
  - Travel time between tasks.
  - Multi-task batch apply.
  - A balancer view for caregivers' own load.

## Maintenance — app shell and navigation (after Feature 2)

- The sidebar is scoped to `.sidebar`. Previously the Command Center's `<aside>` rail was pinned over it and hid the menu and logout.
- A visible **Log out** button sits in the top bar. The sidebar menu scrolls with the user block pinned, the current page is highlighted, and the page title shows in the header.
- On phones, a slide-in drawer replaces the icon-only bottom bar.
- Menu items that only led to placeholders are hidden, and each role lands on a working screen. When a later feature ships a screen, add it to `roleNav` in `frontend/src/shell.tsx`.
- Command Center deadline reasons are shown in the app timezone.
- The app is served on port 8000 only. Local previews use the same port.
