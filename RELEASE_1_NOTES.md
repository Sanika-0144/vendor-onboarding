# VendorFlow — Release 1: Intelligent Validation Engine

## Included

- Deterministic PAN, GSTIN, CIN and IFSC format checks.
- GSTIN-to-PAN consistency check (the PAN embedded in GSTIN must match the supplied PAN).
- Conservative legal-name comparison using the already-approved `compare_names()` policy. Fuzzy similarity never passes automatically; ambiguous cases are routed to review.
- OCR candidate comparison for PAN, GSTIN, CIN and legal name against saved application values.
- Bank account-holder comparison against the legal business name. A differing holder with linked authorisation evidence is routed to reviewer attention; without evidence it is a blocker.
- Bank evidence OCR account-holder comparison where available.
- Exact duplicate document detection using SHA-256 hashes.
- Required-document checks using the existing applicability/slot resolver.
- Persisted validation run history, tied to the application and current version.
- Vendor endpoints:
  - `POST /api/vendor/applications/{application_ref}/validate`
  - `GET /api/vendor/applications/{application_ref}/validation`
- New vendor UI section: **Validation**, with grouped blockers, reviewer attention, passed checks, counts, and next-step guidance.
- Owner isolation is enforced by the existing application access middleware.

## Validation status meanings

- `BLOCKED`: at least one blocking mismatch or missing required item exists.
- `NEEDS_REVIEW`: no blocker, but at least one item needs a human reviewer.
- `INCOMPLETE`: no blocker/review item, but an incomplete item remains.
- `READY_FOR_REVIEW`: no blocking or review findings were generated. This does **not** mean approved.

Individual findings use `pass`, `mismatch`, `needs_review`, `missing`, or `not_provided` statuses.

## Important limitations

- No live PAN, GSTIN, MCA/CIN, sanctions, or bank-account verification is connected.
- Format validity is not proof that an identifier exists or belongs to the vendor.
- OCR output is a candidate only and must be checked against the original uploaded document.
- Bank ownership evidence is a signal for human assessment, not an automatic ownership verification.
- The validation endpoint is a separate diagnostic run; it does not auto-approve, reject, or submit an application.

## Local run

Backend (PowerShell):

```powershell
cd backend
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend (second terminal):

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173/`. Log in, open an application, select **Validation**, and click **Run validation checks**.

## Tests

From `backend/`:

```powershell
python -m pytest -q
```

Release 1 adds deterministic unit tests and API persistence/access-isolation tests.
