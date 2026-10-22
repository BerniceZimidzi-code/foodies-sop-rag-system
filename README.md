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
  section, version, source path, and effective date. PostgreSQL deployments can
  combine pgvector semantic retrieval with lexical retrieval; SQLite and
  repository-managed SOPs continue to use lexical retrieval.
- Successful and no-match queries are recorded in `data/foodies.sqlite3`.
- SOP source files remain version-controlled in Git.

Answer generation uses the provider selected by
`FOODIES_LLM_PROVIDER` (`extractive` by default, `ollama` for a local model, or
`openai` for hosted API use). Both LLM providers receive only the question and
up to three authorized retrieved excerpts, not the full SOP library, account
data, or filesystem paths. The Ollama adapter only permits a loopback HTTP
endpoint, so test prompts and excerpts stay on this computer. Backend-owned
citations are returned separately from the model answer. Entra ID/SSO,
automated Git-based embedding updates, and a production deployment pipeline
are not configured.

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

Open <http://127.0.0.1:8127> and sign in. Use the administration panel to
create staff and manager accounts; each worker receives an invitation link and
sets their own password. The CLI is for bootstrapping administrator accounts.

By default the app uses SQLite at `data/foodies.sqlite3`. Set
`FOODIES_DATABASE_URL` to a PostgreSQL connection URL to use PostgreSQL instead;
the application creates and updates its tables at startup. Leave it blank for
local SQLite development. Existing SQLite data is not copied automatically:
back up the database and plan a separate data and uploaded-file migration before
switching an environment that contains records. The JWT secret must be stable
across restarts and at least 32 characters; store it in a secret manager in
deployed environments, not in source control.

PostgreSQL connections use Psycopg 3. For Neon, use the connection URL provided
by Neon, keep SSL enabled, and store the URL only in the ignored local `.env`
or the hosting provider's secret environment settings. Local and deployed
environments should use separate development and production databases.
PostgreSQL initialization enables the pgvector extension and creates the
embedding table. Semantic retrieval is opt-in: set
`FOODIES_EMBEDDING_PROVIDER=openrouter` and
`FOODIES_OPENROUTER_EMBEDDING_MODEL=nvidia/nemotron-3.5-embed-1b:free`, then
configure `OPENROUTER_API_KEY` in the deployment environment. Embeddings use
`FOODIES_OPENROUTER_EMBEDDING_API_KEY` when set, otherwise they reuse
`OPENROUTER_API_KEY`; only add the separate variable if you want a distinct key.
The application stores vectors only for approved, effective uploaded SOP sections. The
admin approval action automatically indexes that SOP's sections and reports if
indexing could not be completed. The admin-only
`/api/admin/embeddings/reindex` endpoint indexes sections missing for the
configured model, or refreshes all sections after changing the embedding model.
Reindexing is not performed during startup. Existing lexical search remains
available if embeddings are disabled or the embedding provider is unavailable.
Repository-managed SOPs remain lexical-only. OpenRouter receives the approved
section text during indexing and each staff question during semantic search;
review the organization's data policy before enabling this setting. Uploaded
original PDF/DOCX files are not stored in the vector table.

### Bootstrap the first administrator on Render Free

The app can create its first admin at startup when all four
`FOODIES_BOOTSTRAP_ADMIN_*` environment variables are set. It only creates the
account when the database contains no users; it never changes an existing
account's password. Configure these values in the Render service's Environment
settings, not in GitHub:

| Variable | Value |
| --- | --- |
| `FOODIES_BOOTSTRAP_ADMIN_EMAIL` | The admin's sign-in email address |
| `FOODIES_BOOTSTRAP_ADMIN_NAME` | The admin's display name |
| `FOODIES_BOOTSTRAP_ADMIN_DEPARTMENT` | For example, `All` |
| `FOODIES_BOOTSTRAP_ADMIN_PASSWORD` | A unique password of 12-256 characters; treat it as a secret |

Save the variables and redeploy, then sign in using the email and password you
configured. In the Render logs, confirm startup reports that the initial
administrator account was created; the password is never logged. Keep the four
values configured on Render Free if you want the account to be recreated after
the service's temporary filesystem resets. This is for preview/testing only:
the SQLite database and uploaded files can still be lost, and the bootstrap
password remains a Render secret. Do not use this as a production persistence
or backup solution.

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

## Document management

The administration panel includes data-driven document categories, bulk upload,
document search, review, replacement, soft deletion, failed-upload recovery, and
admin-searchable audit history. Category cards act as folders: opening one filters
the catalogue to documents in that category, where admins can access the
available download and management actions. The initial categories are seeded on
first database initialization; administrators can add, rename, archive, and
restore categories. Category IDs, rather than folder names, are stored with
uploaded documents, so the category list can grow without code changes.

The single-file upload accepts a blank SOP ID; the system detects an ID from the
document or filename when possible and otherwise generates one. Metadata edits
use the catalogue form, and approval refreshes the affected document views.

Bulk upload accepts up to 30 `.md`, selectable-text `.pdf`, or `.docx` files per
batch, with a 15 MB per-file and 100 MB batch limit. Batch-wide category and
department defaults can be selected and overridden per file. Each file requires
a title, category, type, department, owner, version, and effective date.
Comma-separated search tags are optional keywords that help staff find relevant
documents. SOPs are branch-wide, so branch/location metadata is not collected or
used for filtering. SOP IDs are optional: a blank ID is detected from an ID field
in the document or a matching SOP filename when possible, otherwise the system
allocates a stable `FD-SOP-000001`-style ID. An
administrator can enter an ID to override detection; the final ID is shown in
the per-file upload results.
Uploads with invalid metadata, duplicate contents or versions, unsupported
formats, extraction failures, or a batch-size violation are reported for each
file with plain-language guidance. Results distinguish uploaded documents,
duplicates, and files that need attention. Exact duplicate content is not added
to the retry queue; it is identified as already present in the library.
Recoverable failures retain their source file under `data/uploads/failed/` and
are visible to admins for correction and retry. Files rejected before they can
be retained can be retried by selecting a replacement file. Files over the
per-document limit are reported but cannot be retained by the application.
Detailed diagnostics remain in protected server-side records and are not
returned by the failed-upload list API.

All uploaded versions start in `pending_review`. Assign a category before
approval; a pending item without a category cannot be published. Replacing a
document creates a new version and leaves the current approved version available
until the replacement is approved. Admins can edit metadata, archive documents,
soft-delete and restore them, or permanently remove soft-deleted file content
after a two-step confirmation. Audit metadata remains after permanent removal.
In the catalogue, **Edit metadata** changes the document details and search tags;
**Archive** hides an approved document from staff while retaining its history;
**Delete** moves it to the restorable Deleted state; **Replace with new version**
uploads a draft replacement that must be approved before it becomes active.

Staff and managers can search/download only effective, approved documents for
their own department. Admins can search all departments and manage all
documents. Important actions, including upload, failed upload, metadata changes,
category moves, review, archive, download, delete, restore, and purge, are kept
in an admin-searchable audit table with no ordinary-user edit/delete endpoint.
Account invitations, activation, deactivation, restoration, and deletion are
also audited because they change who can access department-scoped documents.
Database backups must include the uploaded originals as well as SQLite; source
documents already under `data/sops/approved/` remain Git-managed and
read-only through the document catalogue.

## API

- `POST /api/auth/login` — exchange email/password for a 30-minute bearer token.
- `GET /api/auth/me` — return the authenticated account.
- `POST /api/query` — retrieve approved sections and write an audit event.
- `GET /api/departments`, `GET /api/sops` — list content visible to the caller.
- `GET /api/document-categories`, `GET /api/documents` — list active categories
  and search effective approved documents within the caller's department.
- `GET /api/documents/{document_id}/download` — download an approved document
  available to the caller; downloads are audited.
- `GET/POST /api/admin/users` — list users or create one and email its
  activation invitation.
- `GET /api/admin/email-status` — report whether SMTP settings are present.
- `GET/POST/PATCH /api/admin/document-categories` — list, add, or rename
  categories; category archive/restore actions are admin-only.
- `POST /api/admin/documents/bulk-upload` — upload up to 30 files and receive
  per-file uploaded, duplicate, unsupported, or failed outcomes; SOP IDs may be
  omitted to use document detection or automatic ID generation, and selected
  default category/department values can be overridden for individual files.
- `GET /api/admin/sops` — search/filter document versions and, for admins, view
  soft-deleted versions with `include_deleted=true`.
- `PATCH/DELETE /api/admin/documents/{document_id}` — edit metadata or
  soft-delete a version; restore and separately confirmed permanent removal are
  available through the corresponding admin endpoints.
- `POST /api/admin/documents/{document_id}/replace` — upload a replacement as
  a new version for review; the current approved version remains available
  until approval.
- `GET /api/admin/document-upload-failures` — inspect failed batches; retry
  recoverable files after correcting metadata, select a replacement file when
  the original cannot be retried, or dismiss the attempt.
- `POST /api/admin/document-upload-failures/{attempt_id}/replace` — use a new
  supported file and corrected metadata to recover a failed upload.
- `GET /api/admin/document-audit` — search document-management audit records.
- `POST /api/admin/users/preview` — validate an uploaded `.xlsx` workbook.
- `POST /api/admin/users/bulk` — create and invite the reviewed valid rows.
- `POST /api/admin/users/{user_id}/activation` — rotate and resend an unused
  activation invitation.
- `DELETE /api/admin/users/{user_id}` — permanently remove an account; audit
  and SOP-review history is retained.
- `POST /api/admin/users/{user_id}/password-reset` — send a password-reset link
  to an active user's registered email address; no password is returned to the
  administrator.
- `POST /api/auth/password-reset` — request a reset link. The response is
  identical whether an active account exists or not.
- `POST /api/auth/password-reset/confirm` — consume a one-time reset token and
  set a new password.
- `POST /api/auth/activate` — use the one-time invitation token to activate an
  account and choose its password.
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
activation. The app emails a one-time invitation link that expires after 24
hours; the worker chooses their own password on the activation page. The
activation token is stored only as a hash, is passed in the URL fragment (not
sent in HTTP requests or normal access logs), and is cleared after successful
activation. Failed email delivery leaves the account inactive and available for
an administrator to resend the invitation. No temporary password is sent or
shown to administrators.

Workers can request a password reset from the sign-in page. For active accounts,
the app emails a one-time link that expires after 30 minutes; only the link's
token hash is stored, and successful use changes the password, consumes the
token, and invalidates existing sessions. Requests are throttled per account,
and the response does not disclose whether an email belongs to an account.
Administrators can trigger a reset email from the team account list but cannot
view or set the worker's password. If reset email delivery fails, the failed
token is cleared and the event is recorded in server logs.

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

### Configure OpenAI answer generation

The default remains extractive until explicitly changed. Create an API key in
the OpenAI API platform (a ChatGPT subscription is separate from API billing),
then set these values in the ignored local `.env` file:

```dotenv
FOODIES_LLM_PROVIDER=openai
OPENAI_API_KEY=your-api-key
FOODIES_OPENAI_MODEL=gpt-4.1-mini
```

`gpt-4.1-mini` is the initial low-cost default for short, grounded SOP answers;
the model name is configurable. Check current model availability and pricing in
the [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini)
before enabling billing. Set an API project budget/usage alert, never commit or
share the key, and restart Uvicorn after changing `.env`. Only the worker's
question and at most three retrieved sections are sent to the API. Review
OpenAI's current data controls and your organization's policy before sending
internal SOP content to any external service. If the provider fails, the app
returns a service-unavailable error rather than substituting an ungrounded
answer.

### Use OpenRouter free models

Create an API key in your [OpenRouter account](https://openrouter.ai/), then
select OpenRouter in the ignored local `.env` file:

```dotenv
FOODIES_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your-openrouter-api-key
FOODIES_OPENROUTER_MODEL=openrouter/free
```

The app uses OpenRouter's OpenAI-compatible chat completions API. The
`openrouter/free` model router selects an available free model; the particular
model can change, and free models may be slower, unavailable, or have usage
limits. Check OpenRouter's current [free model limits](https://openrouter.ai/docs/faq#how-are-rate-limits-calculated)
and [model catalog](https://openrouter.ai/models?max_price=0) before testing.
Do not commit or share the key. Restart Uvicorn after changing `.env`. As with
any hosted provider, review your organization's data policy before sending
internal SOP excerpts; only the question and up to three retrieved excerpts are
sent. Citations remain generated by the app.

#### Enable semantic retrieval with OpenRouter embeddings

For a PostgreSQL deployment, set these Render environment variables:

```dotenv
FOODIES_EMBEDDING_PROVIDER=openrouter
FOODIES_OPENROUTER_EMBEDDING_MODEL=nvidia/nemotron-3.5-embed-1b:free
FOODIES_OPENROUTER_EMBEDDING_API_KEY=your-embedding-api-key
```

Keep `OPENROUTER_API_KEY` for Gemma answer generation. Set the optional
`FOODIES_OPENROUTER_EMBEDDING_API_KEY` to your separate embedding key; if left
blank or unset, embeddings reuse `OPENROUTER_API_KEY`.
The model is free when listed as free by OpenRouter; availability and rate
limits can change. After deploying, use PowerShell to sign in as an admin and
run the indexing request:

```powershell
$baseUrl = "https://YOUR-SERVICE.onrender.com"
$credentials = Get-Credential -UserName "admin@example.com"
$loginBody = @{
    email = $credentials.UserName
    password = $credentials.GetNetworkCredential().Password
} | ConvertTo-Json
$login = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/auth/login" `
    -ContentType "application/json" -Body $loginBody
Invoke-RestMethod -Method Post -Uri "$baseUrl/api/admin/embeddings/reindex" `
    -Headers @{ Authorization = "Bearer $($login.access_token)" }
```

The response reports the number of sections indexed. Newly approved uploaded
SOPs are indexed automatically. Use the reindex request to recover from
provider outages or rebuild after changing the embedding model; sections
already indexed with the current model are skipped. Queries are
department-filtered in PostgreSQL before results are returned. Search uses
exact cosine-distance ordering with an initial minimum cosine similarity of
0.45, so no approximate vector index is needed for the initial document
library. Evaluate and tune this model-specific threshold against representative
SOP questions before relying on vector-only matches. If OpenRouter is
unavailable, retrieval falls back to lexical search.

### Run a local free model with Ollama

Install Ollama for Windows from [ollama.com/download/windows](https://ollama.com/download/windows),
then open a new PowerShell terminal and download the small Qwen 2.5 3B model:

```powershell
ollama pull qwen2.5:3b
```

Ollama runs its local API at `http://127.0.0.1:11434` by default. In the ignored
`.env` file set:

```dotenv
FOODIES_LLM_PROVIDER=ollama
FOODIES_OLLAMA_BASE_URL=http://127.0.0.1:11434
FOODIES_OLLAMA_MODEL=qwen2.5:3b
```

Restart Uvicorn and ask a question covered by an approved SOP. The model runs on
the local machine; no OpenAI key or hosted inference charge is needed. Hardware
affects response speed and memory use. If the model is too slow, use a smaller
tag/model supported by Ollama or continue with the extractive provider. Keep
the Ollama endpoint on loopback; the application rejects non-local Ollama
URLs. Ollama and the selected model have their own licenses; review those terms
before redistribution or production use. For production, change the provider
deliberately after reviewing data handling, reliability, and cost.

Before production deployment, integrate the company's SSO/identity provider,
use managed PostgreSQL and encrypted backups, set HTTPS and ingress rate limits,
define audit retention/access policies, and add monitoring and operational
alerts. SQLite and local passwords are intended for a controlled MVP, not a
multi-instance production deployment. Query and answer audit records may
contain sensitive operational information and must be protected accordingly.
