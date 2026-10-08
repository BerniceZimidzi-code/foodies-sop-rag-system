# Foodies SOP Assistant

An internal FastAPI application for answering staff questions from the current,
approved SOP documents in `data/sops/approved/`. The MVP uses department-scoped
accounts, short-lived JWTs, extractive answers with citations, and a persistent
SQLite audit log.

## MVP capabilities

- Only documents with valid YAML front matter and `status: Approved` are eligible.
- Future-effective documents are excluded; if more than one eligible version of
  an SOP exists, only the latest effective/version is used.
- Staff and managers can search only their own department. Administrators can
  search all departments, provision accounts, and inspect audit events.
- Staff see an approved SOP library scoped to their department; administrators
  can browse all approved procedures and jump into asking about an SOP.
- Answers quote the best-matching approved section and include SOP ID, title,
  section, version, source path, and effective date. If there is no lexical
  match, the app says it could not find the answer in the approved repository.
- Successful and no-match queries are recorded in `data/foodies.sqlite3`.
- SOP source files remain version-controlled in Git.

The current retrieval is lexical and the default answer provider is extractive;
this MVP does not call an LLM, create embeddings, or browse the web. Answer
generation is isolated behind the `AnswerProvider` interface in
`backend/answering.py`. A future model provider can receive only retrieved SOP
sections; citations remain assembled from backend metadata. No model provider
or API credentials are configured until a provider is chosen. Entra ID/SSO,
PostgreSQL with pgvector, automated Git-based reindexing, and a production
deployment pipeline are follow-on integrations rather than configured services.

The web interface uses a Foodies-yellow theme and a temporary text monogram in
place of the official logo. When the brand asset is available, replace the
`.brand-mark` element in `templates/index.html` with the approved logo file;
the UI uses system fonts and does not load third-party web fonts.

## Run locally

Copy the provided environment template to a local `.env` file:

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
notepad .env
```

Set `FOODIES_JWT_SECRET` in `.env` to a random value of at least 32 characters.
PowerShell can generate one with:

```powershell
$bytes = [byte[]]::new(48)
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToBase64String($bytes)
```

Copy the printed value into `FOODIES_JWT_SECRET` in `.env`. Leave the SMTP
username/password blank until configuring a sender account. The app loads `.env`
at startup; existing PowerShell environment variables take precedence.

Create the first administrator. The command securely prompts for a password
(minimum 12 characters):

```powershell
.\.venv\Scripts\python.exe -m backend.cli create-user --email admin@example.com --name "Foodies Admin" --department All --role admin
```

Start the application from the repository root. Activation and other `.env`
settings are read automatically:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --reload --host 127.0.0.1 --port 8127
```

Open <http://127.0.0.1:8127> and sign in. To create more accounts, use the
administration panel or run the CLI again.

Set `FOODIES_DATABASE_PATH` to use a different SQLite database file. Back up the
database as well as the SOP Git repository. The JWT secret must be stable across
restarts and at least 32 characters; store it in a secret manager in deployed
environments, not in source control.

## SOP metadata and lifecycle

Store only currently approved documents under `data/sops/approved/`. A document
must have valid YAML front matter with at least:

```yaml
---
id: SOP-KIT-001
title: Food Storage and Cold Chain Monitoring
department: Kitchen
owner: Head Chef
status: Approved
version: 2.1
effective_date: 2026-10-01
approved_by: Food Safety Manager
approved_date: 2026-10-01
---
```

Use Git branches and reviewed pull requests for changes. Keep drafts and
superseded copies outside the approved directory (for example, under
`data/sops/draft/` or `data/sops/archived/`). A document with missing/invalid
metadata, a non-approved status, or a future effective date is not indexed.
Markdown headings define the cited sections. Changes to approved documents are
picked up on the next request; there is no separate vector-index refresh step in
this MVP.

## API

- `POST /api/auth/login` — exchange email/password for a 30-minute bearer token.
- `GET /api/auth/me` — return the authenticated account.
- `POST /api/query` — retrieve approved sections and write an audit event.
- `GET /api/departments`, `GET /api/sops` — list content visible to the caller.
- `GET/POST /api/admin/users` — list users or create one and email its
  activation invitation.
- `GET /api/admin/email-status` — report whether SMTP settings are present.
- `POST /api/admin/users/preview` — validate an uploaded `.xlsx` workbook.
- `POST /api/admin/users/bulk` — create and invite the reviewed valid rows.
- `POST /api/admin/users/{user_id}/activation` — rotate and resend an unused
  activation invitation.
- `DELETE /api/admin/users/{user_id}` — permanently remove an account; audit
  and SOP-review history is retained.
- `POST /api/admin/users/{user_id}/password-reset` — generate a temporary
  password once; the user's existing sessions are revoked and they must change
  it before use.
- `POST /api/auth/activate` — use the one-time email token and temporary
  password to activate an account and choose its permanent password.
- `POST /api/auth/change-password` — complete a required password change.
- `PATCH /api/admin/users/{user_id}/active` — activate/deactivate an account.
- `GET /api/admin/audit-logs?limit=100` — administrator-only audit export view.
- `POST /api/admin/sops/upload` — upload an SOP file and metadata; new versions are
  stored as `pending_review` and are not searchable.
- `GET /api/admin/sops` — administrator view of uploaded SOP versions and status.
- `GET /api/admin/sops/{version_id}` — review metadata and extracted sections
  before approval (original filesystem paths are not exposed).
- `POST /api/admin/sops/{version_id}/review` — approve or reject a pending version,
  or archive an approved version. Approval archives any previously approved
  uploaded version for that SOP ID.
- `GET /api/admin/sops/{version_id}/events` — administrator-only SOP review history.
- `GET /api/health` — basic health and approved section count.

The upload accepts Markdown (`.md`), text-based PDF (`.pdf`), and Word (`.docx`)
files up to 15 MB. Metadata is submitted as multipart form fields. Approval makes
the extracted sections eligible for department-scoped retrieval; drafts,
rejected/archived versions, and future-effective versions are excluded. This
upload workflow stores versions and review events in SQLite and the originals
under `data/uploads/`. It does not currently create embeddings or call an LLM;
answers remain extractive until an LLM provider is configured.

## Security and deployment notes

Passwords are stored as salted PBKDF2 hashes. API access requires a signed JWT;
the user record is checked on every request so deactivated accounts and sessions
invalidated by a password reset lose access immediately. The app has no public
registration route.

Accounts created in the admin panel or bulk import remain inactive until
activation. The app emails a random temporary password and a 24-hour activation
link. The activation token is stored only as a hash, is passed in the URL
fragment (not sent in HTTP requests or normal access logs), and is cleared after
successful activation. Activation replaces the temporary password, so neither
the link nor temporary password can be reused. Failed email delivery leaves the
account inactive and available for an administrator to resend the invitation.

Administrators may upload an Excel `.xlsx` file with a header row containing
`name`, `email`, `department`, and `role` columns (case-insensitive). The preview
validates each row and identifies duplicates; only reviewed valid rows can be
submitted. Workbooks are limited to 5 MB and 500 users.

Permanent account deletion removes the login account and immediately revokes
sessions. Existing audit and SOP-review records keep the former user's identity
for historical compliance; deletion does not erase those records.

### Configure real activation email

The backend uses standard SMTP, so it works with a company SMTP relay, Microsoft
365, Gmail, or a transactional email provider that offers SMTP. Configure these
environment variables in the same environment that starts Uvicorn:

| Variable | Purpose |
| --- | --- |
| `FOODIES_SMTP_HOST` | SMTP hostname |
| `FOODIES_SMTP_PORT` | SMTP port; commonly `587` for STARTTLS or `465` for SSL |
| `FOODIES_SMTP_SECURITY` | `starttls` (default), `ssl`, or `none` for a trusted private relay only |
| `FOODIES_SMTP_USERNAME` | SMTP login; optional if the relay does not require authentication |
| `FOODIES_SMTP_PASSWORD` | SMTP password/app password; set together with the username |
| `FOODIES_EMAIL_FROM` | Verified sender address, for example `sop-assistant@foodies.example` |
| `FOODIES_BASE_URL` | User-facing app URL; HTTPS is required except on localhost |

For Gmail SMTP, use the following settings in `.env`:

```dotenv
FOODIES_SMTP_HOST=smtp.gmail.com
FOODIES_SMTP_PORT=587
FOODIES_SMTP_SECURITY=starttls
FOODIES_SMTP_USERNAME=your-sender@gmail.com
FOODIES_SMTP_PASSWORD=your-sender-app-password
FOODIES_EMAIL_FROM=your-sender@gmail.com
FOODIES_BASE_URL=http://127.0.0.1:8127
```

The recipient can be any ordinary Gmail address and does **not** need an App
Password or Google account setup. Gmail SMTP authentication is for the sending
account: Google generally does not allow using its regular account password for
SMTP. For a Gmail sender, enable 2-Step Verification and create an App Password
for that sender account, or use an approved email provider/relay. Never put a
recipient's password in this configuration. For production set
`FOODIES_BASE_URL` to the deployed HTTPS address, configure SPF/DKIM/DMARC for
the sender domain, and store SMTP credentials in a secret manager. Do not commit
credentials or send them in chat. Restart Uvicorn after changing `.env`; the
admin panel shows whether the minimum SMTP settings are present.
For local development, `FOODIES_BASE_URL` must use the same port as Uvicorn.
For example, if Uvicorn uses `--port 8128`, set it to
`http://127.0.0.1:8128`, restart the app, and resend any invitation created
with the old URL.

Before production deployment, integrate the company's SSO/identity provider,
use managed PostgreSQL and encrypted backups, set HTTPS and ingress rate limits,
define audit retention/access policies, and add monitoring and operational
alerts. SQLite and local passwords are intended for a controlled MVP, not a
multi-instance production deployment. Query and answer audit records may
contain sensitive operational information and must be protected accordingly.
