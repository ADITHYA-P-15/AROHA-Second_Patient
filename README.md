Overview
Caregiving involves more than remembering appointments or checking off
medication doses. It means coordinating people, availability,
responsibilities, and last-minute changes---often while one caregiver is
already stretched thin.

AROHA is a care-coordination platform designed to make that work more
manageable. It brings care activities, caregiver availability,
workload, backup coverage, and help requests into one place. Rather than
only reacting after a task is missed, AROHA helps identify coverage
gaps, suggest feasible alternatives, and keep the care team informed.

The platform is built around a simple principle: care should not
depend on one person always being available.
✨ Key Features
Care coordination
- Organize medication schedules, appointments, and other care
  activities in one shared plan.
- Track activities as pending, completed, completed late, or missed.
- Give patients, primary contacts, caretakers, and healthcare
  professionals role-specific views.
Caregiver workload balancing
- Review caregiver workload over upcoming days and weeks.
- Identify overloaded schedules, conflicting commitments, and
  dependencies on a single caregiver.
- Present explained recommendations for moving tasks while respecting
  eligibility and availability constraints.
Backup matching and coverage planning
- Find eligible replacement caretakers when someone reports an
  absence, declines a task, or cannot provide cover.
- Consider capabilities, availability, overlapping commitments,
  workload limits, and continuity.
- Explain why a candidate may or may not be suitable.
- Treat a task as covered only after the proposed replacement accepts.
Coverage forecasting
- Surface unassigned activities, unconfirmed assignments, and tasks
  with only one eligible caregiver.
- Help primary contacts address gaps before care activities are due.
- Provide actionable next steps, such as finding cover or requesting
  confirmation.
Help requests and escalation
- Route patient help requests to the appropriate people in the care
  team.
- Track acknowledgement, escalation, and resolution.
- Support urgent SOS flows and visible status updates.
Voice notes and optional AI assistance
- Let patients submit voice notes when typing is difficult.
- Support transcription and translation through configured AI
  providers.
- Use AI only as an advisory layer: it may suggest raising urgency,
  but it cannot lower the rule-based urgency level.
- Keep core coordination flows available when optional AI providers
  are not configured or unavailable.
Care team directory and insights
- Browse caretaker listings using filters such as skills, language,
  location, availability, and reputation.
- Compare potential matches and manage hire requests.
- Give healthcare professionals an overview of adherence patterns,
  appointments, and care requests for patients on their care team.
AROHA's recommendations are coordination support---not medical
diagnoses or a substitute for professional judgement.

🔄 How It Works
1. Set up the care network. A primary contact registers a patient
   and coordinates the care team.
2. Build the care plan. Healthcare professionals can add
   prescriptions and appointments; scheduled care activities appear in
   the plan.
3. Coordinate daily work. Caretakers view their assigned
   activities, record completion, manage availability, and respond to
   cover requests.
4. Detect coverage issues. AROHA checks assignments, skills,
   availability, and workload to identify potential gaps.
5. Find and confirm cover. Suitable alternatives are suggested, and
   a replacement is confirmed only after acceptance.
6. Escalate and follow up. Help requests are routed to the relevant
   care team, with acknowledgement and resolution tracked in the
   application.
👥 User Roles
  Role                                Main responsibilities
  Primary contact                 Registers the patient, coordinates
                                      the care network, reviews coverage,
                                      and approves care-plan changes.

  Caretaker                       Views daily activities, records
                                      completion, manages availability,
                                      and accepts or declines cover
                                      offers.

  Healthcare professional         Joins a patient's care team,
                                      manages prescriptions and
                                      appointments, and reviews relevant
                                      care information.

  Patient                         Views their care plan and can
                                  submit help requests or SOS alerts.
🧱 Technology Stack
  Layer                      Technologies
  Frontend                   React, TypeScript, Vite, Tailwind CSS
  Routing and data           React Router, TanStack Query
  Backend API                Python, FastAPI
  Data access                SQLAlchemy, psycopg
  Database                   PostgreSQL 16
  Migrations                 Alembic
  Local fallback and tests   SQLite
  Deployment                 Docker, Docker Compose
  Optional AI                Configurable transcription and text-model providers
🏗️ Architecture
AROHA uses a web frontend backed by a FastAPI application. The backend
owns authentication, permissions, care-plan state, coverage rules,
workload calculations, and escalation workflows. The frontend presents
those decisions and lets authorized users take action.
┌──────────────────────────────────────────────────────┐
│                   React + TypeScript                 │
│     Role-based views · Care plan · Coverage tools    │
└──────────────────────────┬───────────────────────────┘
                           │ HTTP / JSON
┌──────────────────────────▼───────────────────────────┐
│                     FastAPI Backend                  │
│ Authentication · Permissions · Care coordination    │
│ Workload balancing · Backup matching · Escalations  │
└──────────────────────────┬───────────────────────────┘
                           │ SQLAlchemy / psycopg
┌──────────────────────────▼───────────────────────────┐
│                    PostgreSQL 16                    │
│       Care records · Assignments · Event history     │
└──────────────────────────────────────────────────────┘
The backend uses deterministic rules for core coordination decisions.
Optional AI assistance is kept separate from essential scheduling and
coverage logic.
🚀 Getting Started
Prerequisites
- Docker Desktop or Docker Engine with Docker Compose
- Git, to clone the repository
- Internet access for the initial image and dependency downloads
Python 3.11+ and Node.js 20.19+ are also useful for local development
and running the test suites.
1. Clone the repository
git clone <YOUR_REPOSITORY_URL>
cd AROHA
Replace <YOUR_REPOSITORY_URL> with the URL of your AROHA repository.
If the checked-out directory has a different name, use that directory
name in the cd command.
2. Start the application
macOS / Linux
bash scripts/start.sh
Windows PowerShell
.\scripts\start.ps1
The startup script prepares a local .env if one does not exist,
including a generated session secret, and starts the Docker Compose
application.

If you prefer to configure it manually:
cp .env.example .env
Then ensure the local configuration has a unique SECRET_KEY before
starting the application.
3. Open AROHA
Once the containers are running, open:
  Resource                            URL
  Application                         http://localhost:8000

  API documentation                   http://localhost:8000/docs
  Health check                        http://localhost:8000/api/health
To inspect application logs:
docker compose logs -f app
To stop the application:
docker compose down
Docker Compose uses a persistent database volume. Avoid
docker compose down -v unless you intend to delete the database volume
and its stored data.
🧪 Development and Tests
Backend tests
From the repository root, with backend dependencies installed:
python -m pytest backend/tests -q
Frontend checks
From the frontend/ directory:
npm ci
npm run lint
npm run typecheck
npm test
npm run build
Deployment smoke check
With the application running:
python scripts/smoke.py --base-url http://localhost:8000
For load checks against a running demo deployment:
python scripts/load_check.py --base-url http://localhost:8000 --users 40 --seconds 20
The smoke check creates test records. Use fictional data in development
and testing environments.
⚙️ Configuration
The .env.example file documents the available configuration. Common
settings include:
  Variable                            Purpose
  APP_ENV                           Selects the application runtime
                                      mode.

  SECRET_KEY                        Secret used for signing application
                                      sessions or tokens. Set a unique
                                      value.

  DATABASE_URL                      Database connection string. Docker
                                      Compose provides its internal
                                      PostgreSQL connection.

  APP_TIMEZONE                      Timezone used for scheduling and
                                      display; defaults to
                                      Asia/Kolkata.

  DEMO_MODE                         Enables demo-specific behavior and
                                      controls.

  SEED_DEMO                         Controls whether fictional
                                      demonstration data is seeded.

  DEMO_PASSWORD                     Password configured for seeded
                                      demonstration accounts.

  AUTO_COORDINATION                 Enables or disables automatic
                                      coordination workflows.

  COOKIE_SECURE                     Enables secure-cookie behavior when
                                      deployed behind HTTPS.

  GEMINI_API_KEY, GROQ_API_KEY    Optional credentials for supported
                                  AI-assisted voice-note workflows.
Keep .env out of version control. Never commit real credentials, API
keys, signing secrets, or personal health information. Use the
repository's .env.example for the current list of supported settings.
📚 Documentation
More detailed project documentation is available in the repository:
- [Architecture](docs/ARCHITECTURE.md) --- system structure and design
  decisions
- [Product specification](docs/PRODUCT_SPEC.md) --- product scope and
  behavior
- [Demo walkthrough](docs/DEMO_SCRIPT.md) --- suggested demonstration
  flow
- [Deployment guide](docs/DEPLOYMENT.md) --- deployment approach and
  operational guidance
- [Render deployment](docs/DEPLOY_RENDER.md) --- managed hosting setup
- [AI assistance](docs/AI.md) --- voice notes, transcription, and AI
  behavior
- [Backup Matcher](docs/BACKUP_MATCHER.md) --- replacement eligibility
  and matching rules
- [Coverage Planner](docs/COVERAGE_PLANNER.md) --- coverage findings
  and forecast behavior
- [Workload Balancer](docs/WORKLOAD_BALANCER.md) --- workload analysis
  and suggested task moves
- [Directory](docs/DIRECTORY.md) --- caretaker directory and care-team
  building
🔐 Privacy, Safety, and Limitations
- AROHA is a care-coordination demonstration, not a diagnostic or
  emergency-response service.
- Seeded people and patient records are fictional. Do not use real
  patient information in demo environments.
- Professional identity verification and production-grade deployment
  controls must be configured before real-world use.
- A local or LAN deployment may use plain HTTP. Use HTTPS and
  appropriate secret management for hosted deployments.
- Notifications and AI integrations depend on the features and
  providers configured in the deployment. Do not assume that an in-app
  alert contacts emergency services.
- AI-generated transcription, translation, and urgency suggestions may
  be inaccurate and must be reviewed by a person.
- Use the appropriate local emergency service directly in a real
  emergency.
🗺️ Roadmap Direction
AROHA is designed around improving continuity of care through:
- Earlier identification of care-coverage gaps
- More resilient caregiver schedules and backup plans
- Clear, explainable replacement recommendations
- Better handovers and coordination across care roles
- Useful operational insights for families and healthcare
  professionals
