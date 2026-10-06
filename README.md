# Foodies SOP RAG System

A controlled internal AI assistant for Foodies staff to ask approved SOP questions in natural language and receive answers strictly grounded in the authorised SOP repository.

## What this MVP does

- Searches only approved SOP documents in `data/sops/approved/`
- Filters by department when needed
- Retrieves relevant SOP sections
- Returns a grounded answer with citations to the SOP ID, title, section, version, and file
- Keeps all SOP updates version-controlled and auditable through Git
- Provides a simple internal web UI for staff

## Project structure

- `app.py` - FastAPI backend and internal UI
- `data/sops/approved/` - approved SOP repository
- `templates/index.html` - chat interface
- `static/styles.css` - styling
- `static/app.js` - frontend logic
- `README.md` - setup and operating guide

## Quick start

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:
   ```bash
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

4. Open the app in a browser:
   ```text
   http://localhost:8000
   ```

## Example questions

- What must a cashier do when a customer disputes a bill?
- How often should kitchen staff record cold storage temperatures?
- What is the process for handling a guest complaint in the restaurant?
- Which SOP covers food storage and cold chain monitoring?

## Governance model

This system is intentionally restrictive:

- Only approved SOPs are indexed
- Draft or archived SOPs are excluded
- Answers are based only on the retrieved SOP content
- Every answer includes citations to the source SOP and section
- If the repository does not contain an answer, the assistant says so clearly

## Updating SOPs

To update a SOP:

1. Edit the document in `data/sops/approved/`
2. Update the front matter metadata if necessary
3. Commit changes to Git
4. Re-run the app or refresh the index if the repository is auto indexed

This approach keeps the document lifecycle versioned and reviewable.

## Recommended production enhancements

- Add SSO/role-based access
- Add a review approval workflow before SOP documents become active
- Index documents automatically on git push
- Store audit logs for staff queries and responses
- Add PDF import and OCR support for legacy SOPs

## MVP status

This is a working internal assistant prototype designed for Foodies staff to query approved SOPs in a controlled, traceable way.
