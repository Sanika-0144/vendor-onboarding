# VendorFlow final deployment fix

## Root cause of the observed Save Draft 404

The backend already defines `PUT /api/vendor/applications/{application_ref}/draft`, and the frontend calls that same route. The observed 404 is therefore not caused by a missing draft route.

The backend access middleware first checks that the application reference exists in the active SQLite database and belongs to the authenticated vendor. The uploaded project snapshot's database does not contain `VND-B6626DF6`. The Render Free configuration stores SQLite under `/tmp`, which is ephemeral and can be cleared when the service restarts/redeploys/spins down. The browser can retain the old application reference in localStorage even after the server-side row has disappeared. This produces the observed 404 before the draft handler is reached.

## Changes in this package

- Missing application references now return HTTP 410 with an explicit explanation that the draft is no longer in current server storage and the vendor should return to My Applications and create a new draft.
- Added regression tests for successful draft save and missing/expired draft response.
- Updated `render.yaml` with the actual Render service URLs supplied by the project owner:
  - Frontend: https://vendorflow-frontend-17ik.onrender.com
  - Backend API: https://vendorflow-api-f5cm.onrender.com/api
- Existing API route and authenticated fetch behavior are preserved.

## Apply to Render

1. Back up the current GitHub repository.
2. Replace repository source files with this package's contents (do not upload local databases, uploaded files, `.env` files, keys, or virtual environments).
3. Commit and push to the deployed branch.
4. Render will redeploy the backend and frontend. Confirm the frontend service has `VITE_API_URL=https://vendorflow-api-f5cm.onrender.com/api` and backend has `FRONTEND_ORIGINS=https://vendorflow-frontend-17ik.onrender.com`.
5. Open the site, go to My Applications, and create a NEW application. Do not reuse the old `VND-B6626DF6` reference.
6. Save a small profile change. Then continue to tax, bank, document upload, validation, submit and reviewer tests.

## Critical free-tier limitation

This project still uses SQLite and local uploads under `/tmp` on Render Free. They are temporary. The fix makes expired drafts understandable; it does not make data persistent. For a stable demonstration, avoid redeploying/restarting the backend during a demo and create a fresh application after any restart. Do not use real vendor identity or bank documents on this configuration.

## Verification

- Backend automated tests: 84 passed.
- Python compilation: checked separately before release packaging.
- Frontend production build: not verified; `npm ci` timed out in the build environment. Render's own static-site build should be checked after push.
