# VendorFlow — Release 2

FastAPI + SQLite backend and React + Vite frontend for the VendorFlow onboarding portal.

This release includes Release 1's deterministic validation engine plus the authenticated reviewer queue, application detail, reviewer decisions, comments and audit history. See `RELEASE_1_NOTES.md` and `RELEASE_2_NOTES.md` for scope and setup.

See `backend/requirements.txt` for Python dependencies and `frontend/package.json` for frontend scripts.


## Release 3: deployment and security hardening

- The free-tier `render.yaml` stores SQLite at `/tmp/vendorflow.sqlite3` and private uploads at `/tmp/private_uploads`. This is temporary storage: data and uploaded documents can be lost when the free service restarts, redeploys, or spins down. Use synthetic test data only. For real vendor onboarding, switch to a paid persistent disk or a managed database plus durable object storage.
- SQLite runs with foreign keys, WAL journaling, a busy timeout, and normal synchronous mode. Local development continues to use SQLite.
- Authentication endpoints have per-process rate limits. Reviewer bootstrap is one-time per database. Reviewer/admin accounts must be created using the setup key only for the first reviewer.
- API responses include browser security headers; HSTS is enabled when `VENDORFLOW_ENV=production` or `RENDER` is set. CORS origins must be explicitly configured.
- Uploaded documents are extension/signature checked, size limited to 10 MB, stored outside the public frontend, and written with restrictive file permissions where supported.
- Optional ClamAV scanning is supported with `CLAMAV_HOST`, `CLAMAV_PORT` (default 3310), and `CLAMAV_TIMEOUT_SECONDS` (default 8). If ClamAV is not configured, files are explicitly labelled `UNSCANNED`; the application does not claim they are clean. If configured but unavailable, upload fails closed.

### Important deployment boundary

This release hardens the existing SQLite + Render persistent-disk deployment. It is intended for a single backend instance. PostgreSQL and S3-compatible object storage are not silently enabled: moving to multi-instance production requires a deliberate data migration and storage configuration. Live government registry checks, bank verification, sanctions screening, outbound email, SSO/MFA, and a managed malware-scanning service still require external providers and credentials.
