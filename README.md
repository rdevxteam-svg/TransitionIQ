# Transition IQ

Transition IQ demonstrates the internal talent workflow from opportunity creation through readiness and activation on a project. All employee and project data are synthetic.

## Run with Docker

Run `docker compose up --build` from this directory. Open [the React app](http://localhost:5173) or [the FastAPI reference](http://localhost:8000/docs). PostgreSQL persists the workflow and the worker processes preparation and feedback jobs.

## Run locally

Use Python 3.13 or newer and Node 22.12 or newer. Run the following commands in PowerShell.

1. From `backend`, run `python -m venv .venv`, `.venv/Scripts/python -m pip install -r requirements.txt`, then `.venv/Scripts/python app.py init`.
2. From `backend`, start `.venv/Scripts/python -m uvicorn app:app --reload`. In a separate terminal in the same directory, start `.venv/Scripts/python app.py worker`.
3. From `frontend`, run `npm install` and `npm run dev`. Open the local URL Vite prints.

Local development uses SQLite by default. To use PostgreSQL, set `TRANSITION_DATABASE_URL` to a SQLAlchemy psycopg connection URL in both backend terminals.

## Sign in and access

Set a password for each account you want to use. The command prompts for a password of at least 12 characters. Choose a different password for each account. Running it again resets the password and revokes that account's sessions.

- Local development, from `backend`: `.venv/Scripts/python app.py set-password manager`
- Docker, from this directory after Compose starts: `docker compose exec api python app.py set-password manager`

Replace `manager` with the username to configure, then open the app and sign in.

| Username | Role | Access |
| --- | --- | --- |
| `manager`, `devuser` | Engagement Manager (receiving) | Publish opportunities, review candidates, record client interview outcomes, confirm project access, and approve activation |
| `vikram`, `anika`, `leo` | Employee | Review their match, request learning support, apply, interview, and complete their own onboarding and readiness assessment |
| `lnd` | L&D Team | Receive, review, and acknowledge approved learning requests |
| `sme` | Transition Partner | Review interview evidence, request more preparation, and schedule and record senior fit discussions |
| `release` | Engagement Manager (releasing) | Review transitions once they reach releasing review and make releasing decisions |

Sessions expire after eight hours. Sign out before changing accounts. Direct API callers can post credentials to `/api/auth/login`, retain the session cookie, and send `X-Transition-Request: 1` on write requests. For HTTPS deployments that terminate TLS at a proxy, set `TRANSITION_SECURE_COOKIE=1` on the API.

## Demo flow

1. Sign in as the receiving Engagement Manager. Create and publish an opening with a pasted or uploaded text job description, skill criteria, assessment questions, and an optional client interview. When criteria are omitted, recognized skills from the description start at level 3.
2. Sign in as `vikram`. Open **Updates & support** for opportunity notifications, then review the match and learning recommendations. Request L&D support if useful, save a career goal, and apply. The application shows a 48-hour preparation target. Draft and confirm the preparation plan, then answer the interview questions.
3. Sign in as the Transition Partner (`sme`). Review rubric evidence and request more preparation or confirm readiness. Schedule the senior fit discussion and record the outcome. If a client interview is required, the receiving Engagement Manager schedules it and records the decision.
4. Approve the receiving and releasing reviews as the respective Engagement Managers. Once the employee is selected, the receiving Engagement Manager confirms project access to open onboarding.
5. As the employee, complete the knowledge-transfer checklist and the readiness assessment. A Transition Readiness Score of at least 75% sends the transition for final review. The receiving Engagement Manager can activate the employee or request reassessment.

**My Transitions** shows the employee’s joining date, role changes, and project history with technologies recorded in the synthetic employment data. New project activations appear automatically from the workflow. The project card labels opportunity skills when its technology stack has not been recorded.

Employees upload and replace their private resume from **My Transitions**. The first update is due 90 days after joining. Each successful upload resets the due date by 90 days. **Updates & support** shows a reminder in the final 14 days and while overdue. The demo stores only the current PDF or DOCX (up to 5 MB) in the application database.

Employee **Opportunities** ranks all published openings by the fraction of required skills evidenced in the uploaded resume. It compares the manager’s skill criteria and recognized job-description terms using local text extraction and skill aliases. This is an advisory skill-coverage score. Scanned or encrypted PDFs need to be replaced with a text-based PDF or DOCX. Resume data is processed locally.

For a skill gap, **Raise request** opens a draft the employee can edit. Approval creates a ticket without attaching the resume. The `lnd` account has the **L&D Requests** dashboard, which shows new tickets until a team member acknowledges them. Configure this account with the same `set-password` command.

**Updates & support** includes in-app notifications, a knowledge hub, guidance backed by the local knowledge pack, and status counts for the signed-in account. Receiving Engagement Managers can see the local L&D request queue.

The demo uses deterministic skill mapping, a structured interview rubric, and a curated knowledge pack. The 48-hour target is advisory. Interview scheduling, access confirmation, and L&D requests are recorded locally. Calendar invitations, identity and access provisioning, enterprise knowledge, an external L&D system, and model-based assessments require provider integration. Existing active records stay active. In-flight records continue from their saved stage.
