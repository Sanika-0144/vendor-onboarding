# Cursor Prompt Pack — Vendor Onboarding System

## How to use this (5 minutes of setup)

1. Unzip this project. Open the **`vendor-onboarding/`** folder in Cursor (File → Open Folder).
2. Create the file `.cursor/rules/project.mdc` and paste the **RULES FILE** below into it (this is read by Cursor on every chat).
3. Confirm `docs/product_brief.md` exists (it is your brief). `backend/` already contains a **tested reference core** (`vendor_core/`, 42 passing tests).
4. Open a **new Agent chat for each prompt**, in order (Prompt 1 → 6). Paste one prompt at a time.
5. After each prompt: run the tests/app yourself, check the **"Done when"** list, commit to git, then move on. Do not paste the next prompt until the current one works.
6. If Cursor wanders: reply *"Stop. Re-read .cursor/rules/project.mdc and docs/product_brief.md, then continue only with the task in my last prompt."*

**Decisions pre-approved for this build (change them here before pasting if you disagree):**
Backend FastAPI + SQLite · Frontend React + Vite + TypeScript + Tailwind · Live updates via Server-Sent Events · Demo auth = role switcher (NOT real authentication) · Document extraction = synthetic adapter by default, optional Claude adapter behind an env var · Deployment = one container (FastAPI serves the built frontend) on Render or Railway.

---

## RULES FILE  (save as `.cursor/rules/project.mdc`)

```text
---
description: Vendor Onboarding System project rules
alwaysApply: true
---
Source of truth: docs/product_brief.md. Read it before any task.

NON-NEGOTIABLE PRINCIPLES
1. AI (LLM/OCR) only classifies and extracts documents and may polish vendor wording. It NEVER decides APPROVED/PENDING/REJECTED. Deterministic code decides.
2. Fail closed: a missing, errored, not-run or unavailable required check must never produce APPROVED. An empty rule set never approves.
3. Fuzzy similarity or a suspicion alone is never a BLOCKER. Only a reviewer-confirmed, configured disqualifying condition produces REJECTED.
4. Vendor-facing responses use ONLY vendor-visible findings. Internal-only findings (duplicate bank/tax ID, screening matches, fraud signals, reviewer notes) must never appear in any vendor endpoint, vendor UI, vendor email or vendor-facing log. Enforce this in the API response models, not just the UI.
5. Never put raw tax IDs, bank account numbers or full documents in logs, findings, audit events or normal UI views. Mask them (last 4). Encrypt sensitive fields at rest (Fernet; key from env var, never committed).
6. Nothing is live: no OCR, malware scanner, government registry, bank-verification or sanctions provider is connected unless I say so. Label every synthetic result "SYNTHETIC" in the UI and API. Never claim a verification succeeded that did not run. Syntax/checksum validity does not prove an identifier is genuine.
7. Preserve and reuse backend/vendor_core and its tests. Do not rewrite its logic without telling me why. Run the full test suite after every change; all tests must stay green.
8. Keep original submitted strings; normalised values are derived comparison data only.
9. Do not invent legal/tax rules, credentials, providers or outcomes. If something is ambiguous, state your assumption in one line and continue; for material architecture choices not already approved, ask.
10. Work incrementally: small steps, explain each material change, keep README.md current, no dead code, no placeholder "TODO: implement" in shipped paths.
```

---

## PROMPT 1 — Baseline, review and plan (no feature code)

```text
Read .cursor/rules/project.mdc and docs/product_brief.md fully. Then inspect backend/ (vendor_core/, configs/, demo/, tests/).

Tasks (do NOT add features yet):
1. Create a Python venv, install what backend needs (cryptography, pytest), run the full test suite and the CLI demo (python -m demo.run_demo). Report exact results.
2. Write docs/baseline_report.md containing: (a) what each module does, (b) the pipeline and decision roll-up as implemented, (c) a table mapping every acceptance criterion in brief section 15 to "implemented in core / needs API / needs UI / not in scope", (d) any defects, risky assumptions or gaps you find in the core (be specific; cite file and function), (e) a proposed build plan for the API and the two frontends that follows brief sections 6, 11 and 14.
3. Do not modify any file except creating docs/baseline_report.md.

Done when: tests pass, the report exists, and you have listed any defects you found. Stop and wait for my approval before changing any code.
```

---

## PROMPT 2 — API layer (FastAPI + SQLite)

```text
Using the approved stack (FastAPI + SQLite), build the API in backend/app/ WITHOUT modifying vendor_core except for genuine bug fixes (each with a new test).

Requirements:
1. Persistence (SQLite): applications (application_ref, state, decision_status, version, created/updated), application_versions (immutable submission JSON per version, with sensitive fields Fernet-encrypted: account_number, tax identifier values, iban), evaluations (full EvaluationResult JSON, masked), documents (slot_id, original filename, sha256, stored path, status, attempts), review_actions, audit (use vendor_core.audit.AuditLog or an equivalent hash-chained table). Files go to a private local folder, never served statically. Read VENDOR_FERNET_KEY and VENDOR_HMAC_KEY from env; generate a dev key on first run and print a warning (never commit it); add .env.example.
2. Endpoints (separate routers, separate Pydantic response models):
   VENDOR (public, vendor-safe only):
   - POST /api/vendor/applications (create draft) · PUT /api/vendor/applications/{ref}/draft (autosave any section; partial updates) · GET /api/vendor/applications/{ref}
   - GET /api/vendor/applications/{ref}/requirements  (resolved document slots + conditional fields from vendor_core.applicability)
   - POST /api/vendor/applications/{ref}/documents/{slot_id} (multipart upload; enforce pdf/jpg/jpeg/png, <=10MB, check file signature, store hash)
   - POST /api/vendor/applications/{ref}/presubmit  (blocks ONLY missing mandatory fields / required docs; returns non-blocking warnings separately)
   - POST /api/vendor/applications/{ref}/submit (declaration text+version+actor+timestamp recorded; creates new version; starts evaluation)
   - GET /api/vendor/applications/{ref}/status (EvaluationResult.to_dict(internal=False) only: milestones, document statuses, required actions)
   INTERNAL (header X-Demo-Role: procurement | compliance | admin; NOT real auth, label it clearly):
   - GET /api/internal/applications (filters: status, state, country, needs_review; sorted by risk_score) · GET /api/internal/applications/{ref} (full result incl. internal findings; compliance/admin see unmasked-last-4 only; never full values)
   - GET /api/internal/applications/{ref}/runs/{version}/events (stored stage events)
   - POST /api/internal/applications/{ref}/reviewer-actions (resolve_escalation | confirm_blocker) — compliance/admin only; re-evaluates, writes audit, voids risk resolutions per core logic
   - GET /api/internal/applications/{ref}/audit
   LIVE RUN: GET /api/stream/{ref}/{version} (Server-Sent Events). Run the engine in a background thread with step_delay ~0.35s so the live timeline is visible, emitting the engine's events; persist them.
3. Procurement analysts must NOT see sensitive reviewer-only data (confirm_blocker reasons, screening details); compliance/admin can. Enforce in code.
4. Resubmission: submit on an existing application creates a new version and calls engine.evaluate(previous=...). Persist rerun info and finding diff.
5. Tests (pytest + httpx TestClient): vendor endpoints NEVER leak internal findings (test with the duplicate-bank and sanctions scenarios, assert strings like "duplicate", "V-1001", "screening", raw IDs are absent from every vendor response); presubmit blocks only mandatory items; role enforcement; resubmission diff; upload validation; sensitive fields encrypted in the DB file (assert raw account number not present in the sqlite bytes).
6. Provide a seed script (scripts/seed_demo.py) that loads all scenarios from backend/demo/scenarios.py as applications.

Done when: pytest is green (old 42 + new), uvicorn app.main:app runs, and I can see interactive docs at /docs. Show me the endpoint list and a curl example for: create draft -> autosave -> presubmit -> submit -> status.
```

---

## PROMPT 3 — Document adapters (synthetic default, optional Claude)

```text
Implement the document pipeline adapters behind the ExtractionAdapter contract in backend/vendor_core/adapters.py. Requirements:

1. SyntheticExtractionAdapter (DEFAULT): for demo, a document's extraction result comes from a sidecar JSON next to the sample file (<filename>.extraction.json) or, for uploads of known sample files, from a lookup table keyed by file sha256 built from demo/scenarios.py. If nothing matches, return status FAILED (so the low-confidence / re-upload path is exercised honestly). Every result carries synthetic=true and the UI must show a "SYNTHETIC EXTRACTION" badge.
2. A script scripts/make_sample_docs.py that generates realistic sample PDFs (use reportlab) for every document in every scenario in demo/scenarios.py, plus a few JPGs with noise/rotation to look scanned, plus matching sidecar JSON, into sample_docs/<scenario>/. Include the Edge-3 case (PAN card showing ...234C while the form says ...234D).
3. ClaudeExtractionAdapter (OPTIONAL, enabled only if EXTRACTION_PROVIDER=claude and ANTHROPIC_API_KEY is set): send the document image/PDF to the Claude API and require strict JSON matching the schema {detected_type, fields:{name:{value,confidence,page}}, issue_date, expiry_date}. Rules: "extract only what is printed; null if absent; never infer"; validate the JSON against a Pydantic schema; treat output as UNTRUSTED; on schema failure or timeout mark FAILED. PRIVACY: never send full TIN/SSN/EIN or full bank account numbers to the model — instruct it to return only the last 4 digits for those fields, and document this limitation honestly in README. This adapter must be clearly labelled as a real model call (not synthetic) and I will test it manually; do not claim it is verified.
4. A StubMalwareScanner adapter returning status NOT_SCANNED/CLEAN with synthetic=true; policy malware_scan_required stays false by default and the UI says "No malware scanner connected (demo)".
5. Wire the adapters into the upload flow from Prompt 2: upload -> file checks -> classify/extract -> store extraction -> document status RECEIVED/PROCESSING/ACCEPTED/ACTION_REQUIRED/HUMAN_REVIEW after evaluation.
6. Tests: low-confidence two-attempt path (re-upload then human review), wrong document type in a slot, unsupported extension, oversized file, synthetic badge present in API output.

Done when: tests green, sample_docs/ generated, and uploading sample_docs/edge3_pan_mismatch files through the API reproduces the PAN-mismatch PENDING result.
```

---

## PROMPT 4 — Vendor portal (React + Vite + TypeScript + Tailwind)

```text
Create frontend/ (Vite + React + TypeScript + Tailwind). Build the VENDOR portal exactly per brief section 6, talking only to /api/vendor/*.

1. Five-step wizard with a left progress rail: Business Profile, Tax & Registration, Banking Information, Supporting Documents, Review & Submit. Each step shows completeness.
2. Dynamic forms driven by GET /requirements: entity-type options by country (IN/US/GB), Goods/Services multi-select with conditional fields, multiple tax registration records (jurisdiction, type, value, indirect-tax status registered/not_registered/application_pending/not_applicable + reason), multiple bank accounts with exactly one primary (radio), country-specific bank identifiers (IFSC / ABA + ACH-or-wire / sort code), account holder type and relationship fields when holder differs.
3. AUTO-SAVE: debounce ~800ms to PUT /draft with a visible "Saved HH:MM" / "Saving..." indicator; resuming a draft via application ref restores everything.
4. Structured upload slots: one card per slot with requirement badge (REQUIRED/CONDITIONAL/RECOMMENDED/OPTIONAL), drag-and-drop, file type/size hints (PDF/JPG/JPEG/PNG, 10MB), and processing status chips (RECEIVED, PROCESSING, ACCEPTED, ACTION_REQUIRED, HUMAN_REVIEW). Show "SYNTHETIC EXTRACTION" and "No malware scanner connected (demo)" notices.
5. Review & Submit: masked summary (last 4 only) with edit links, outstanding-requirements list that BLOCKS submit only for mandatory items, non-blocking warnings, declaration checkbox, then submit -> application reference.
6. Tracking page (/track/:ref): milestones, status, the vendor-safe correction list (each item says exactly what to fix and which document), per-document statuses, and a "Resubmit only what changed" flow. It must never display or hint at internal findings.
7. A "Load demo scenario" dropdown (dev/demo mode only) that pre-fills the form from a scenario and lists the matching files in sample_docs/ to upload — this is for the live demo.
8. Design: clean, professional, accessible (labels, focus states, keyboard nav, responsive down to tablet), consistent spacing, a clear empty/loading/error state everywhere. No lorem ipsum.
9. A persistent top banner in demo mode: "Demo environment — fictional data. Document extraction, malware scanning, registry, bank and sanctions checks are simulated."

Frontend tests: at least component tests for the primary-account rule, autosave, and the presubmit blocking behaviour (Vitest + Testing Library).

Done when: I can complete an Indian private-limited onboarding end-to-end in the browser and see APPROVED; then the PAN-mismatch scenario shows PENDING with a clear correction list and I can resubmit to APPROVED.
```

---

## PROMPT 5 — Procurement dashboard + live run view

```text
Add the INTERNAL experience to frontend/ (routes under /internal, role switcher in the header: procurement / compliance / admin, clearly labelled "demo roles, not real authentication").

1. LIVE RUN VIEW (most important screen): consume the SSE stream. Vertical timeline of stages (Intake, Documents, Tax & registration, Banking, Cross-referencing, Risk checks, Decision, Communication). Each stage expands to show its rules as they complete with status icons (pass / flagged / review / not-applicable / error), the findings, and the extracted-vs-submitted values (masked). Show applicability resolution at the top (country, entity, categories, N rules required, N not applicable and why). Animate rows in as events arrive. Include a "Replay" button.
2. SIDE-BY-SIDE COMPARISON panel: form vs each document for legal name, identifiers (masked), bank holder, address — mismatches highlighted; cosmetic-name differences labelled "cosmetic (normalised)", original strings preserved.
3. DECISION CARD: status badge (APPROVED/PENDING/REJECTED), application state, the reasons list linked to findings, a risk score used only for queue ordering, "needs human review" flag, the vendor message exactly as sent (and a note of how many internal findings were hidden from the vendor), plus a Rule-version label.
4. DASHBOARD: table of applications (ref, vendor, country, entity, status, state, needs-review, risk score, updated), counts by status, filters (status/state/country/needs review), search, click-through. Sort the review queue by risk score.
5. APPLICATION DETAIL: tabs — Overview, Findings (internal vs vendor-visible clearly separated), Documents, Versions (with resolved / still-open / newly-introduced diff and which rules were re-run vs reused), Reviewer actions, Audit timeline (who/what/when/rule version).
6. REVIEWER ACTIONS (compliance/admin only): resolve an escalation with a note, or confirm a disqualifying condition (-> REJECTED). Confirmation dialogs; analysts see these controls disabled with an explanation.
7. A "Run scenario" panel for the demo: buttons for each scenario (3 happy paths + edge cases 1, 2a, 2b, 3, 4, 4b, low-confidence) that submit and open the live view directly.
8. Same banner/synthetic labelling rules as the vendor portal.

Done when: from the dashboard I can click "Edge 4: duplicate bank", watch the live run, see PENDING / Under review with an internal-only finding, switch to the vendor tracking page and confirm NOTHING about the duplicate appears there, then as compliance resolve it and see APPROVED with an audit entry.
```

---

## PROMPT 6 — Hardening, deploy, demo kit

```text
Final pass. Do all of the following:
1. Run every test (backend + frontend). Fix failures. Add any missing tests for the acceptance criteria in brief section 15 (map each criterion to a test in docs/acceptance_matrix.md; mark anything not met honestly).
2. Security/privacy review of your own work: grep logs, API responses, audit file, DB file and frontend bundles for raw PAN/GSTIN/account numbers/EIN; confirm only masked values; confirm vendor endpoints cannot return internal findings under any code path; confirm .env/keys are gitignored. Report what you checked and results.
3. Single-container deploy: Dockerfile that builds the frontend and serves it from FastAPI (static + /api), env vars documented, SQLite on a mounted volume, health endpoint. Provide a render.yaml (or Railway equivalent) and step-by-step deploy notes. Seed the demo data on first boot behind a DEMO_MODE=true flag.
4. A reliable demo mode: DEMO_MODE=true pre-seeds scenarios, uses the synthetic adapters, fixed "today" of 2026-11-12 for reproducibility (configurable), and a "Reset demo data" button (internal admin only).
5. docs/DEMO_SCRIPT.md: a 5-minute run order (happy path -> cosmetic name -> sole-proprietor -> PAN mismatch + resubmission -> duplicate bank, vendor-vs-internal view), exact clicks, what to say at each step, and a "what is real vs simulated" slide-free talk track. Also a 10-question interview Q&A (why rules decide not the LLM, how fail-closed works, how name matching is tuned, how this scales, what is not production-ready).
6. Update README.md: architecture, how to run locally (one command each for backend, frontend, tests), env vars, security model, a candid "NOT production-ready" list (no real auth/RBAC, SQLite/Fernet/JSONL are dev controls, no live registry/bank/sanctions/OCR/malware providers, GSTIN checksum validated only against public test vectors, UK account checks conservative, W-8 not implemented).

Done when: a clean clone can be started with the documented commands, all tests pass, the Docker image runs the full demo, and DEMO_SCRIPT.md can be followed verbatim.
```

---

## Optional follow-up prompts (use only if needed)

**Cursor broke tests / changed core logic:**
```text
Revert any changes to backend/vendor_core that are not required by a failing test I asked you to fix. Explain each remaining change in one line and show the test that justifies it. Then re-run the full suite.
```

**Vendor view might be leaking:**
```text
Write an adversarial test that submits every scenario in demo/scenarios.py, calls every /api/vendor/* endpoint, serialises all responses, and asserts none contain: any finding_id with a RSK- prefix, the words duplicate/sanction/screening/fraud/risk, any existing-vendor id, or any unmasked identifier from the submission. Fix any leak at the response-model layer.
```

**UI looks generic:**
```text
Restyle the UI to feel like a polished B2B finance product: restrained neutral palette with one accent, clear typographic hierarchy, generous whitespace, status colours used consistently (green approved, amber pending, red rejected, grey not-applicable), subtle motion only in the live run view. Do not change behaviour or tests.
```
