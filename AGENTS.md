# Project instructions

Follow the standing rules below for every phase. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for architecture, domain contracts, and roadmap. Run backend tests with `python -m pytest backend/tests -q`; frontend checks with `npm run lint`, `npm run typecheck`, `npm test`, and `npm run build` from `frontend/`. Start with `docker compose up --build -d`; stop with `docker compose down`.

## Standing rules

1. Single-port LAN deployment: API and built React UI served on port 8000 bound to `0.0.0.0`. After each phase, Docker Compose and `python scripts/smoke.py --base-url http://<LAN-IP>:8000` should work.
2. README is cumulative: preserve earlier phase sections; append new phase documentation. Keep the opening overview, team placeholder, quick start, access URLs, and required submission sections current.
3. Backend is the source of truth. Gap detection, scoring, backup filtering are deterministic backend logic; AI may explain but never decide or confirm.
4. Persistent footer: “Operational care-coordination tool — not a diagnostic or emergency service. Demo data is fictional.” Never present operational scores as medical risk or diagnosis.
5. Fictional data only; seeded people are synthetic and explicitly labelled.
6. Security: authorize every endpoint, validate server-side, avoid leaking stack traces/secrets, keep `.env` ignored and `.env.example` safe, and do not use CDNs.
7. Work on `main`, make meaningful commits at milestones, never force-push or rewrite history. Do not create `bugbounty` or `fixing` before Phase 10. Push `main` after the final commit when possible.
8. Implement only the current phase and retain extension points. Run the full available suite before finishing.
9. LAN operation must work offline; bundle frontend dependencies and fonts.
10. Every feature must reduce caregiver coordination burden, improve explainable coverage, or support resource planning. Prefer one-tap decisions and management-by-exception over more notifications.

