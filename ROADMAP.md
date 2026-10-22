# Foodies SOP Assistant: Remaining Work

This checklist records what is still needed to take the current local MVP toward
a dependable internal SOP assistant. It intentionally does not include secrets.

## Current state

- FastAPI application with SQLite local development and a configurable
  PostgreSQL connection for accounts, department-scoped access, and audit
  logging. Existing SQLite records and uploaded files still need a planned
  migration before production cutover.
- SOP upload, review, approval, versioning, and extractive answers with citations.
- Admin-managed, database-backed document categories and bulk document
  management with category-aware review, version replacement, soft deletion,
  failed-upload recovery, batch-default category/department values with per-file
  overrides, automatic or document-detected SOP IDs, department-scoped access,
  and document audit events.
- Admin onboarding by manual entry or reviewed Excel import, one-time activation,
  invitation resend, self-service password reset by expiring email link, and
  account deletion.
- Local `.env` loading and an ignored local `.env` file.
- Gmail sender authentication, email delivery, and account activation have
  been verified locally.
- Local activation URLs use port 8128; invitations created before that
  configuration was corrected needed to be resent.
- Ollama, OpenAI, and extractive answer providers are supported. PostgreSQL
  deployments can use opt-in OpenRouter embeddings with pgvector alongside
  lexical retrieval; model grounding and retrieval evaluation remain.

## Priority 1 — Get the local setup reliable — COMPLETE

- [x] Fill in and locally verify `FOODIES_JWT_SECRET` in `.env`; keep this value
  stable across restarts and never commit or share it.
- [x] Verify Gmail sender authentication using the local `.env` settings. The
  Gmail SMTP connection and TLS negotiation completed and authentication
  succeeded; no message was sent by this check.
- [x] Start the app on an available local port and verify `/api/health` responds.
- [x] Send one test invitation to an address the team controls. Confirm receipt,
  activate the account, sign in with the password the worker chose, and confirm
  the activation link cannot be reused.
- [x] End-to-end test a forgotten-password request: verify receipt, successful
  reset, expiry, one-time use, generic unknown-email response, and session
  revocation.
- [x] Resend the pending invitation for account
  `6e16d1ae-dd3f-418e-92b6-0ff89cfe6360` after mail is working. Do not create a
  duplicate account.

**Complete:** The local test account received its invitation and activated;
email and password recovery have been validated.

## Priority 2 — Connect an LLM

- [x] Add a local Ollama provider for free local model testing while retaining
  OpenAI as an optional hosted provider.
- [x] Implement the existing `AnswerProvider` interface in
  `backend/answering.py`; keep provider selection/configuration separate from
  retrieval, and load credentials from environment variables or a secret
  manager.
- [x] Send only up to three authorized, retrieved SOP excerpts. Preserve
  backend-owned citations and instruct the model to abstain when evidence is
  insufficient.
- [x] Add timeouts, bounded retry behavior for hosted OpenAI, local Ollama error
  reporting, and safe behavior when a provider is unavailable. Never return a
  fabricated success answer.
- [x] Add tests for bounded inputs, non-model-owned citations, unsupported
  questions, prompt-injection handling, provider failures, and existing
  department isolation.
- [ ] Install Ollama, download `qwen2.5:3b`, and set the local `.env` provider
  configuration; no API key is needed for local tests.
- [ ] Exercise approved SOP questions through Ollama and review grounding,
  citations, response speed, and memory use.
- [ ] Before production deployment, choose the provider based on policy and
  budget; if hosted OpenAI is selected, configure an API project, spending
  controls, and a secret-managed key.

**Done when:** local model evaluation passes grounding and citation checks,
then the production provider is deliberately chosen for cost, reliability, and
data handling.

## Priority 3 — Improve SOP retrieval and operational coverage

- [x] Add an extensible document-management foundation with the initial
  operational categories, admin-only multi-file uploads, required category
  metadata, per-file failure reporting, approval review, version-preserving
  replacements, searchable department-scoped documents, soft deletion and
  restoration, failed-upload recovery, batch-default categories and departments
  with per-file overrides, automatic/detected SOP IDs, and admin audit search.
- [ ] Pilot bulk import with a small representative set from each existing
  category; verify category mapping, metadata quality, extracted text,
  department visibility, downloads, and replacement history before importing
  the full library.
- [x] Implement opt-in OpenRouter embeddings and pgvector-assisted retrieval
  for approved uploaded SOP sections, with lexical fallback and an admin reindex
  endpoint.
- [x] Automatically index newly approved SOP sections, skip sections already
  indexed by the current model during recovery reindex, and report indexing
  status to administrators.
- [ ] Configure the OpenRouter embedding provider and API key in the intended
  deployment, then run the admin-only embedding reindex endpoint.
- [ ] Evaluate hybrid retrieval with representative questions from each
  department; record expected source sections and compare lexical-only and
  vector-assisted results.
- [ ] Evaluate future automated indexing for Git-managed SOPs separately.
- [ ] Test real Markdown, text-based PDF, and DOCX uploads, metadata validation,
  duplicate versions, approval, archive/rejection, and effective-date behavior.
- [ ] Review bulk-import edge cases and invitation failure/retry behavior with
  administrators.
- [ ] Define how approved SOP source files and uploaded originals are backed up,
  retained, reviewed, and removed when obsolete.

**Done when:** representative user questions return the expected approved
sections with correct department boundaries and current-version citations.

## Priority 4 — Prepare for a real internal deployment

- [ ] Choose hosting and deploy behind HTTPS at a stable team-accessible URL;
  set `FOODIES_BASE_URL` to that address so activation links work for recipients.
- [ ] Move SMTP, JWT, and future LLM credentials into the deployment secret
  manager. Do not use the development `.env` file in production.
- [ ] Choose an identity strategy (company SSO or managed accounts) and review
  account lifecycle, administrator access, and password policies.
- [ ] Move from local SQLite to managed PostgreSQL if required for concurrent
  users, backups, availability, or operations.
- [x] Add a PostgreSQL connection path using `FOODIES_DATABASE_URL`; initialize
  application tables at startup while retaining SQLite for local use.
- [ ] Migrate existing SQLite records and uploaded originals to durable
  PostgreSQL and file storage, verify row counts and file access, and only then
  switch the deployed service.
- [ ] Add encrypted backups and restore testing for the database and SOP files.
- [ ] Add rate limits, security headers, dependency updates, monitoring, error
  alerts, audit-retention rules, and a deployment/rollback process.
- [ ] Test onboarding, SOP review, search, account deletion, and recovery from a
  backup in the deployed environment.

**Done when:** a second team member can use the HTTPS application, activation
links work off the developer's computer, and operators can monitor and restore
the service.

## Later polish

- [ ] Replace the temporary text mark with the approved Foodies logo.
- [ ] Conduct an accessibility and responsive-layout pass on login, admin,
  upload/review, and activation flows.
- [ ] Document admin operating procedures and common email/deployment recovery
  steps.
