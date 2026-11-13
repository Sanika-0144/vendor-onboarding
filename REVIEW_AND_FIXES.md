# VendorFlow ZIP review and fixes

## Applied in this revision

1. Replaced deprecated FastAPI `@app.on_event("startup")` initialization with an application lifespan handler.
2. Updated `.gitignore` to exclude local encryption keys, environment files, SQLite databases, uploaded vendor documents, Python environments, Node dependencies, and build outputs.
3. Removed the bundled development Fernet key, local SQLite database, private uploaded documents, and stale `main_copy.py` backup from this clean source package. Runtime directories are retained with `.gitkeep` files.
4. Kept the document-delete endpoint and frontend delete interaction from the supplied project.

## Verification performed

- Backend test command: `python -m pytest tests/test_core.py -q`
- Result after the lifespan change: **51 passed, no deprecation warnings**.
- Frontend dependency installation (`npm ci`) was attempted but timed out in this environment. Therefore frontend production build and lint are **not verified** here.

## Known issues not silently represented as fixed

- `frontend/src/App.jsx` still points to the fixed demo application reference `VND-F5DD4962`. This means the current UI is tied to the seeded demo application rather than a general multi-application creation/selection workflow.
- Reviewer role selection/header handling is demo-only and is not real authentication or authorization. Do not expose this build publicly with sensitive vendor data.
- OCR, malware scanning, live bank verification, government registry verification, sanctions-provider integration, and email delivery remain unconnected or synthetic/stubbed.
- SQLite and local filesystem uploads are suitable for local development only; production needs managed persistence, private object storage, backups, and access controls.

## Local verification

Backend:

```bash
cd backend
python -m pip install -r requirements.txt
python -m pytest tests/test_core.py -q
uvicorn app.main:app --reload
```

Frontend (in another terminal):

```bash
cd frontend
npm ci
npm run build
npm run lint
npm run dev
```

The frontend build/lint commands must be run locally because dependency installation could not be completed in the review environment.

## Security note

Never restore the removed `.dev_fernet_key`, database, or private uploads from the original ZIP into a public repository. The backend creates a local development key when needed. For deployment, set a securely generated `VENDOR_FERNET_KEY` as a secret environment variable and keep it stable for the lifetime of encrypted records.
