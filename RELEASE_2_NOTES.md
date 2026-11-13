# VendorFlow Release 2 — Reviewer Workflow

## Included
- Replaces the legacy `X-Demo-Role` reviewer header with the authenticated bearer-token roles already used by the application. Only reviewer/admin accounts can access internal routes.
- Reviewer queue includes state, version, timestamps and comment count.
- Reviewer application detail includes a masked submission, latest automated evaluation, latest validation result and reviewer comments.
- Reviewer actions: approve, reject, request corrections. Rejection and correction requests require a reason. Approved/rejected applications are final and cannot be actioned again.
- Reviewer comments and state transitions are persisted.
- Audit trail records actor, role, action, previous state, new state, note and timestamp.
- Reviewer UI supports queue selection, application detail, validation/evaluation review, comments, actions and audit history.
- Existing vendor login, registration, application selection and vendor portal remain in place.

## Apply
Use this as a full source release. Back up the current project first. Replace the `backend` and `frontend` source folders with the corresponding folders in this archive. Keep existing `backend/data` and `backend/private_uploads` directories. SQLite creates the new `reviewer_comments` and `audit_logs` tables automatically on startup.

## Run
Backend:
```powershell
cd backend
python -m pytest -q
uvicorn app.main:app --reload
```
Frontend:
```powershell
cd frontend
npm ci
npm run dev
```

## Reviewer account
Create a reviewer/admin account through `POST /api/auth/bootstrap-reviewer` using the configured `VENDORFLOW_REVIEWER_SETUP_KEY`. On Render, the key is generated from the `render.yaml` environment variable; retrieve it from the service environment settings. Keep it secret. There is no public reviewer registration form.

## Security and scope notes
- Reviewer routes require a valid authenticated reviewer/admin bearer token. The former demo role header is no longer accepted.
- PAN, CIN, GSTIN and bank account values remain masked in reviewer detail responses where the existing serializer masks them.
- Approval/rejection are workflow decisions recorded by the app; they are not legal certification or external registry/bank verification.
- This release does not add email notifications, SSO/MFA, multi-reviewer assignment, or legally binding e-signatures.
