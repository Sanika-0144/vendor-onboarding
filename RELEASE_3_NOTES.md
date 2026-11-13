# VendorFlow Release 3 — Deployment & Production Hardening

## Included
- SQLite durability settings: foreign keys, WAL journal, busy timeout, and safer concurrent access for the single-instance Render deployment.
- Database-backed health check (`/health` returns 503 if storage is unavailable).
- Authentication endpoint throttling (per process): login 8 attempts/minute per IP; registration 30/minute; reviewer bootstrap 5/minute.
- One-time reviewer/admin bootstrap per database.
- Security response headers: nosniff, frame denial, referrer policy, permissions policy, and HSTS in production.
- ClamAV INSTREAM integration. Infected files are rejected; scanner errors fail closed when configured. If not configured, uploads are clearly marked `UNSCANNED` and the API returns a warning.
- Uploads remain limited to PDF/JPG/JPEG/PNG, 10 MB, and signature-checked. Private upload directory/file permissions are tightened on POSIX systems.
- Render environment config marks production mode and retains persistent disk paths.

## Apply
1. Back up the current project and Render persistent disk data.
2. Extract this ZIP and replace the existing `backend` and `frontend` folders plus `render.yaml` and README/release notes.
3. Preserve your existing `backend/data` and `backend/private_uploads` data if applying locally. On Render, do not delete or detach the `/var/data` disk.
4. Keep existing Render secrets unchanged. Do not regenerate `VENDORFLOW_AUTH_SECRET` or `VENDOR_FERNET_KEY` for an existing database: doing so can invalidate sessions and make encrypted fields unreadable.
5. Deploy the backend and frontend. Check `https://<your-api-host>/health`; it should report `status: ok` and `database: ok`.
6. For malware scanning, deploy a reachable ClamAV daemon and set `CLAMAV_HOST` (and optionally port/timeout) in Render. Until then, uploads are explicitly UNSCANNED.

## Operational limits
- SQLite + Render persistent disk is a single-instance deployment. Do not add multiple backend instances or use this as a horizontally scaled service.
- PostgreSQL and S3-compatible object storage are not part of this release; migration requires a planned data and file migration.
- Rate limiting is in-process and resets on restart; use a shared Redis-backed limiter for multi-instance deployment.
- No external PAN/GST/MCA/bank registry, sanctions, email, SSO/MFA, or managed malware provider is connected by this release.
