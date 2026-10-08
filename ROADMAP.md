# Foodies SOP Assistant: Remaining Work

This checklist records what is still needed to take the current local MVP toward
a dependable internal SOP assistant. It intentionally does not include secrets.

## Current state

- FastAPI application with SQLite accounts, department-scoped access, and audit
  logging.
- SOP upload, review, approval, versioning, and extractive answers with citations.
- Admin onboarding by manual entry or reviewed Excel import, one-time activation,
  invitation resend, password reset, and account deletion.
- Local `.env` loading and an ignored local `.env` file.
- Gmail SMTP authentication now succeeds from a fresh local process using `.env`.
  No email was sent during the authentication check; delivery and activation
  still need an end-to-end test. The affected account should remain pending
  activation until its invitation succeeds.
- Local activation URLs are now configured for port 8128. Previously sent
  invitations still contain the old 8127 URL and must be resent after restart.
- No LLM, embeddings, or semantic/vector retrieval is configured; the current
  answer provider is extractive and retrieval is lexical.

## Priority 1 — Get the local setup reliable

- [ ] Fill in and locally verify `FOODIES_JWT_SECRET` in `.env`; keep this value
  stable across restarts and never commit or share it.
- [x] Verify Gmail sender authentication using the local `.env` settings. The
  Gmail SMTP connection and TLS negotiation completed and authentication
  succeeded; no message was sent by this check.
- [ ] Start the app on an available local port and verify `/api/health` responds.
- [ ] Send one test invitation to an address the team controls. Confirm receipt,
  activate the account, sign in with its new password, and confirm the activation
  link and temporary password cannot be reused.
- [ ] Resend the pending invitation for account
  `6e16d1ae-dd3f-418e-92b6-0ff89cfe6360` after mail is working. Do not create a
  duplicate account.

**Done when:** a controlled test account receives its invitation and completes
activation exactly once, and the admin panel reports email as configured.

## Priority 2 — Connect an LLM when the provider is chosen

- [ ] Select the model provider, deployment region, budget, and data-handling
  requirements before adding credentials.
- [ ] Implement the existing `AnswerProvider` interface in
  `backend/answering.py`; keep provider selection/configuration separate from
  retrieval, and load credentials from environment variables or a secret
  manager.
- [ ] Send only the authorized, retrieved SOP sections to the model. Preserve
  backend-owned citations; require answers to use those sources and to say when
  the approved material does not answer the question.
- [ ] Add timeout, bounded retries, provider-error reporting, and safe behavior
  when the provider is unavailable. Never return a fabricated success answer.
- [ ] Add tests for grounded answers, unsupported questions, citations, prompt
  injection in SOP content, provider failures, and department isolation.
- [ ] Compare model answers with a small set of real, approved SOP questions
  before enabling the provider for all staff.

**Done when:** answers are demonstrably grounded in authorized SOP passages,
citations remain correct, and provider failures are visible and safe.

## Priority 3 — Improve SOP retrieval and operational coverage

- [ ] Evaluate lexical search with representative questions from each
  department; record expected source sections and acceptable results.
- [ ] Improve retrieval based on evaluation results. Consider embeddings/vector
  search only if lexical search is insufficient; select storage and embedding
  provider before introducing those dependencies.
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
