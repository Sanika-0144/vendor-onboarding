# Baseline report — vendor onboarding core

**Date:** 12 November 2026  
**Scope:** inspection and execution only. No product code was changed.  
**Source of truth:** `docs/product_brief.md` (v1.0). This tree does not match the file names in brief section 13. The runnable core is `backend/vendor_core/` (see README). Brief section 13’s “120 tests” and modules such as `vendor_validation.py` / `application_lifecycle.py` are not in this folder. The suite here is 42 tests.

**Assumption:** material stack choices in brief section 16 are still open. `CURSOR_PROMPTS.md` names a candidate stack; this report does not lock it.

## Environment and commands

| Item | Result |
|---|---|
| Interpreter | Python 3.12.9, venv at `backend/.venv` (gitignored). Python 3.14 is also installed; 3.12 was used so `cryptography` installs from a wheel. |
| Install | `cryptography` 50.0.2, `pytest` 9.2.0 (`backend/requirements.txt`) |
| Tests | From `backend/`: `python -m pytest -q` → **42 passed in 0.51s**, exit code 0 |
| Demo | From `backend/`: `python -m demo.run_demo` → exit code 0 |

### Demo outcomes (all data fictional; extraction, malware, and sanctions inputs are synthetic)

| Scenario | Decision | Application state |
|---|---|---|
| Happy path: India private limited | APPROVED | COMPLETED |
| Happy path: US LLC | APPROVED | COMPLETED |
| Happy path: UK Ltd | APPROVED | COMPLETED |
| Edge 1: cosmetic name (`Pvt. Ltd.` vs `Private Limited`) | APPROVED | COMPLETED, with internal `NAME_COSMETIC` INFO findings |
| Edge 2a: sole proprietor, own-name account | APPROVED | COMPLETED, internal `SOLE_PROP_OWN_ACCOUNT` |
| Edge 2b: sole proprietor, third-party account | PENDING | ACTION_REQUIRED. Vendor text asks for relationship evidence. Internal `HOLDER_UNRELATED` is omitted. |
| Edge 3: PAN on the form differs from the card | PENDING | ACTION_REQUIRED. Vendor items: GSTIN/PAN consistency and PAN form-vs-document. |
| Edge 4: bank account already on vendor V-1001 | PENDING | UNDER_REVIEW. Vendor message is generic. No duplicate/vendor-id text. |
| Edge 4b: synthetic screening name `Blackwater Trading Co` | PENDING | UNDER_REVIEW. Match is internal. |
| Low-confidence PAN extraction (1 attempt) | PENDING | ACTION_REQUIRED. Vendor is asked to re-upload the PAN card. |

Edge 3 resubmission (v2), same CLI run:

- Decision: **APPROVED (COMPLETED)**
- `finding_diff`: `resolved` = `GEN-010|PAN|PAN_FORM_DOC_MISMATCH`, `IN-004|GSTIN|GSTIN_PAN_MISMATCH`; `still_open` = `[]`; `newly_introduced` = `[]`
- `changed_inputs`: `['tax_registrations']`
- `rules_rerun`: `GEN-004`, `GEN-010`, `IN-001`, `IN-002`, `IN-004`, `RSK-002`

The CLI does not print the word SYNTHETIC. Synthetic flags exist on demo document payloads (`scenarios._doc`) and are not copied onto `CheckResult`.

---

## (a) What each module does

### `backend/vendor_core/`

| Module | Role |
|---|---|
| `models.py` | Enums from brief section 8: `Severity`, `Applicability`, `CheckStatus`, `DecisionStatus`. Dataclasses `Finding`, `CheckResult`, `Decision`. `derive_status` maps findings to PASS / FAIL / REVIEW_REQUIRED. `Finding.finding_id` is `rule_id\|subject\|code`. |
| `applicability.py` | Loads JSON config. `VendorContext` is the five-dimension snapshot. `resolve_applicability` marks each catalogue rule REQUIRED, CONDITIONAL, NOT_APPLICABLE, or REVIEW_REQUIRED. `resolve_slots` builds document slots, including one bank-evidence slot and one optional authorisation slot per account. |
| `rules.py` | Deterministic handlers (`HANDLERS`) for intake, documents, IN/US/GB identifiers, banking, cross-checks, and risk. Reads extraction fields off the submission dict. Does not call a model. |
| `validators.py` | Syntax/checksum helpers: PAN, CIN, LLPIN, IFSC, GSTIN, ABA, EIN (syntax only), UK company number, UTR, GB VAT, sort code, UK account number, IBAN, BIC. Docstring states these do not prove issuance or ownership. `make_gstin` is for fixtures only. |
| `names.py` | Conservative normalisation and tiers: EXACT, COSMETIC, FORM_MISSING, ABBREVIATED, FORM_CONFLICT, AMBIGUOUS, MISMATCH. Original strings are not written back. Similarity at or above 85 becomes AMBIGUOUS (review), never a pass. |
| `decision.py` | `decide`: BLOCKER → REJECTED; empty required set, unresolved applicability, missing/errored/not-run required rules, or FIXABLE/ESCALATE findings → PENDING; otherwise APPROVED. |
| `engine.py` | `OnboardingEngine.evaluate`: applicability, optional resubmission reuse, stage loop, reviewer actions, `decide`, vendor message, in-memory events. `EvaluationResult.to_dict(internal=False)` is the vendor-safe view. |
| `communication.py` | Vendor message from vendor-visible FIXABLE and ESCALATE findings only. Rejected text is generic. `validate_polished` checks LLM wording. `vendor_tracking` maps application state to four milestones. |
| `resubmission.py` | HMAC fingerprints, changed paths, dependency reruns, finding diff (`resolved` / `still_open` / `newly_introduced`), and `attempt_policy` (not called by the engine). |
| `adapters.py` | `SanctionsAdapter` protocol. `SyntheticSanctionsAdapter` reads `sanctions_synthetic.json`. `UnavailableSanctionsAdapter` returns UNAVAILABLE. `StubExtractionAdapter.extract` raises `NotImplementedError`. No registry or bank-ownership adapter. |
| `security.py` | `mask` / `mask_deep`, HMAC fingerprints, Fernet `encrypt_field` / `decrypt_field` (key from `VENDOR_FERNET_KEY`). HMAC key falls back to the literal `dev-only-insecure-key`. |
| `audit.py` | Append-only JSONL hash chain. Masks payload via `mask_deep`. Not written by the engine. A full-file rewrite can still be consistent if the attacker recomputes the chain. |
| `__init__.py` | Exports the engine, config loader, sanctions adapters, and decision/severity enums. |

### `backend/configs/`

| File | Role |
|---|---|
| `rule_catalog.json` | 29 rules, catalogue version `2026.11-mvp-1`. Each rule has stage, handler, `depends_on`, applicability, and `applies_to`. |
| `country_rules.json` | IN/US/GB entity lists, extraction thresholds, doc types, 10 document slots, identifier-to-slot map, PAN holder map, W-9 classification map. Version `2026.11-mvp`. |
| `buyer_policy_default.json` | Policy `default` / `1.0-demo`: file size 10 MB, extensions, re-upload threshold, lapse/attempt defaults, sanctions required, sole-prop personal account `accept_with_evidence`, declared indirect-tax status accepted when a reason is present. |
| `existing_vendors.json` | Two synthetic vendor records for duplicate bank/tax checks. |
| `sanctions_synthetic.json` | Two synthetic names. Not a real sanctions list. |

### `backend/demo/` and `backend/tests/`

| Path | Role |
|---|---|
| `demo/scenarios.py` | Fictional IN/US/GB happy paths and the brief section 10 edge cases. Extraction and malware results are inlined and marked `synthetic: true`. |
| `demo/run_demo.py` | CLI runner. Fixed `today` of 2026-11-12. Runs every scenario, then the Edge 3 resubmission. |
| `tests/test_core.py` | Validators, name tiers, happy paths, edge cases, fail-closed sanctions/errors/empty rule set, banking, documents, privacy, resubmission, events, audit tamper detection. |

There is no `backend/app/`, no frontend, no database, and no file storage.

---

## (b) Pipeline and decision roll-up as implemented

```text
submission dict
  -> VendorContext.from_submission
  -> resolve_applicability + resolve_slots
  -> HMAC fingerprints
  -> if previous evaluation and same rule_version:
       reuse rules whose depends_on paths did not change
     else if rule version changed: run every rule
  -> for stage in INTAKE, DOCUMENTS, FORMAT, BANKING, CROSS_REFERENCE, RISK:
       NOT_APPLICABLE -> CheckStatus.NOT_RUN (handler not called)
       else -> handler, or CheckStatus.ERROR + internal ESCALATE on exception
  -> optional guard RSK-004 if bank/tax changed after a prior risk flag
     (also drops reviewer resolutions of RSK-001/002/003)
  -> reviewer actions: confirm_blocker | resolve_escalation
  -> decide()
  -> build_vendor_message()
  -> in-memory events (not an audit file)
```

`RSK-004` is injected in `OnboardingEngine.evaluate`. It is not a catalogue rule.

### Applicability (`resolve_applicability`)

For each catalogue rule, in order:

1. Country, category, and entity filters in `applies_to`. A miss is NOT_APPLICABLE. Entity type `other` on an entity-restricted rule is REVIEW_REQUIRED.
2. If `policy_flag` is set and the policy value is true, the rule is REQUIRED; if false, NOT_APPLICABLE. This is how `RSK-003` follows `require_sanctions_screening`. The catalogue value CONDITIONAL on that rule is not used.
3. `IN-004` / `US-003` / `GB-003` use the indirect-tax declaration (`registered`, `not_registered`, `not_applicable`, anything else including `application_pending`).
4. Otherwise the catalogue applicability is used.

`tax_jurisdictions` and `operating_countries` are stored on `VendorContext` and included in the intake event. `resolve_applicability` does not read them. Country rules are gated by **registration** country. Bank country is handled inside `bank_identifiers`, per account.

NOT_APPLICABLE is stored as NOT_RUN with a reason. It is not treated as a pass.

### Stages and rules

| Stage | Rules | What they do |
|---|---|---|
| INTAKE | GEN-001, GEN-002, GEN-003 | Required profile fields, category-conditional product/service text, configured entity type, declaration flag. |
| DOCUMENTS | GEN-004 … GEN-008 | Required slots present; extension, size, `signature_ok is False`, malware flag; detected type vs slot; issue/expiry/max age; low-confidence critical fields. |
| FORMAT | IN-001 … IN-004, US-001 … US-003, GB-001 … GB-003 | Identifier syntax and a few consistency checks. US EIN and GB UTR run only when a value is supplied (OPTIONAL). W-9 foreign/`us_person: false` escalates. |
| BANKING | BNK-001, BNK-002, BNK-003, BNK-005 | One primary account; IFSC/ABA/sort code and account-number shape; ownership relationship; cross-border bank is INFO. |
| CROSS_REFERENCE | BNK-004, GEN-009, GEN-010, GEN-011 | Bank document vs form; legal name vs `name_xref` slots; form id vs extracted id; city/postcode overlap as WARN. |
| RISK | RSK-001, RSK-002, RSK-003 | Duplicate bank key, duplicate tax id, sanctions adapter. Findings are `vendor_visible=False`. No adapter, or status other than OK, is NOT_RUN. |

Document status (`_doc_statuses`) is set only for uploaded files: HUMAN_REVIEW if a related ESCALATE exists, else ACTION_REQUIRED if FIXABLE or BLOCKER, else ACCEPTED. Missing slots are omitted. RECEIVED and PROCESSING are never set.

### Decision (`decision.decide`)

1. Any finding with severity BLOCKER → **REJECTED**, `application_state=COMPLETED`.
2. Otherwise collect reasons:
   - no REQUIRED rule in the applicability list → `EMPTY_EXPECTED_RULE_SET`
   - CONDITIONAL or REVIEW_REQUIRED applicability → `UNRESOLVED_APPLICABILITY`
   - REQUIRED rule absent, NOT_RUN, or ERROR → `REQUIRED_RULE_MISSING` / `REQUIRED_RULE_NOT_RUN` / `REQUIRED_RULE_ERROR`
   - any FIXABLE or ESCALATE finding → that severity
3. Any reason → **PENDING**. `application_state` is ACTION_REQUIRED when a vendor-visible FIXABLE exists, otherwise UNDER_REVIEW.
4. No reasons → **APPROVED**, `application_state=COMPLETED`.

WARN and INFO do not create reasons. `risk_score` is a weighted sum and does not change status. Fuzzy name tiers never create BLOCKER. The only BLOCKER path in code is reviewer action `confirm_blocker` (`OnboardingEngine._apply_reviewer_actions`).

Vendor copy (`build_vendor_message`): APPROVED is a thank-you; REJECTED is a generic refusal with no control names; PENDING lists every vendor-visible FIXABLE remediation and vendor-visible ESCALATE review line. `to_dict(internal=False)` returns reference, version, state, status, milestones, document statuses, vendor-safe findings, and the message. It omits events, internal findings, fingerprints, and risk score.

---

## (c) Brief section 15 — acceptance criteria

| # | Criterion | Status | Where it stands |
|---|---|---|---|
| 1 | Create, save, resume, and submit an application | needs API, needs UI | No draft store. `evaluate` assumes a finished dict. |
| 2 | Form adapts to country, entity type, and goods/services | implemented in core; needs UI | `resolve_applicability`, `resolve_slots`, and `profile_fields` encode this. No form. |
| 3 | Multiple tax registrations / jurisdictions can be stored | implemented in core | The submission shape is a list. Same-type records are only partly checked (see defects). |
| 4 | Multiple bank accounts, exactly one primary | implemented in core | `bank_primary`, plus per-account slots. |
| 5 | Ownership mismatch uses conditional review, not automatic rejection | implemented in core | `bank_ownership`. Demo edge 2a approves under policy; edge 2b is PENDING. |
| 6 | Structured slots and visible processing state | implemented in core; needs API, needs UI | Slots and ACCEPTED / ACTION_REQUIRED / HUMAN_REVIEW exist. No upload pipeline and no RECEIVED / PROCESSING. |
| 7 | Pre-submit blocks only mandatory fields and required documents | needs API, needs UI | There is no pre-submit entry point. `evaluate` always runs format, cross-check, and risk. |
| 8 | Required checks cannot be skipped; unresolved or errored required checks cannot approve | implemented in core | Covered by `decide` and tests (empty catalogue, handler exception, sanctions outage, entity `other`, undeclared GST). Default malware policy and resubmission reuse qualify this; see defects. |
| 9 | Decision is only Approved, Pending, or Rejected | implemented in core | `DecisionStatus` has those three values. |
| 10 | Pending applications show actionable vendor-safe corrections | implemented in core; needs API, needs UI | `build_vendor_message` / `vendor_safe_findings`. Nothing sends or renders them. |
| 11 | Internal risk findings are not exposed to vendors | implemented in core; needs API | Filtering is in `to_dict(internal=False)` and the message builder. Tests cover the duplicate-bank vendor view. The API must use these models and must not return `events`. |
| 12 | Resubmission keeps versions and reruns dependent rules | implemented in core; needs API | Diff and `rules_to_rerun` work (Edge 3 demo). Version history is not stored. Reuse misses some inputs (defects). |
| 13 | Sensitive values masked/encrypted; access role-controlled | needs API | `mask` is used in finding text. Fernet helpers exist and are unused by the engine. No RBAC. |
| 14 | Audit records who / what / when / rule version / decision | needs API | `AuditLog.append` has those fields. `evaluate` only keeps events in memory. |
| 15 | Automated tests and the fictional demo run locally | implemented in core | 42 passed; demo exit code 0. Results in the section above. |
| 16 | UI and demo identify synthetic or unavailable integrations | needs UI | Payloads and the sanctions note can say synthetic. `show()` in `demo/run_demo.py` does not print SYNTHETIC. `CheckResult` has no synthetic flag. Unavailable sanctions correctly fail closed. |

Out of scope for this MVP (brief section 3.3), and not in the core: live government registries, live bank-ownership APIs, a full sanctions provider, W-8 processing, forgery verdicts, production KYC. Format checks that return PASS are not external verification.

---

## (d) Defects, risky assumptions, and gaps

Observed with the demo engine (`today=2026-11-12`, synthetic sanctions, HMAC key `b"demo"`) unless noted as code inspection. The 42 tests do not cover these cases. They are not a reason the suite failed.

### Defects

1. **Re-upload count is invisible to resubmission**, so a second unclear upload does not move to human review.  
   `resubmission.flatten` drops `upload_attempts`. `OnboardingEngine.evaluate` then reuses GEN-008.  
   Probe: `low_confidence(1)` then `low_confidence(2)` with `previous` set. `changed_paths` is `[]`, `rules_rerun` is `[]`, the reused finding stays `LOW_CONFIDENCE_REUPLOAD`. A fresh `evaluate` of `attempts=2` (what the unit test does) correctly emits `LOW_CONFIDENCE_HUMAN_REVIEW`.

2. **Document expiry is not rechecked when the clock moves and the file is unchanged.**  
   `fingerprints` hashes submission fields only. `doc_validity` uses `EvalContext.today`, which is not part of the fingerprint.  
   Probe: trade licence expiry `2026-11-20` on 12 Nov 2026 is `EXPIRING_SOON` and APPROVED (WARN). The same payload with `previous` on 1 Dec 2026 reuses every rule and stays APPROVED with `EXPIRING_SOON`, even though `doc_validity` would emit FIXABLE `EXPIRED` on a fresh run.

3. **Truthy strings pass boolean gates.**  
   `bank_primary` uses `if b.get("is_primary")`. `declaration` uses `if not d.get("accepted")`.  
   Probe: a second account with `is_primary="false"` is counted as primary (`PRIMARY_COUNT`). `declaration.accepted="false"` produces no GEN-003 finding and the India happy path stays APPROVED.

4. **Unparseable dates are treated as missing.**  
   `rules._parse` returns `None` on `ValueError`. `doc_validity` then skips future, expiry, and `max_age_days` checks.  
   Probe: bank evidence `issue_date="not-a-date"` (max age 90 days in `country_rules.json`) produces no GEN-007 finding and APPROVED.

5. **A GSTIN/VAT/sales-tax value is not validated when the first declaration says not registered.**  
   `indirect_status` returns the first row of that type. `resolve_applicability` / `_resolve_indirect` then sets NOT_APPLICABLE when a reason is present and `accept_declared_indirect_tax_status_with_reason` is true. `evaluate` does not call the handler for NOT_APPLICABLE.  
   Probe: sole-prop GSTIN status `not_registered` with `value="NOTAREALGSTIN"` → `IN-004` applicability NOT_APPLICABLE, check NOT_RUN, no findings, decision APPROVED.  
   Related: `EvalContext.reg` and `in_gstin` only see the first row. `xref_identifiers` compares every row of a type to the single slot in `registration_id_map`.

6. **Default policy approves when no malware scan ran, and a synthetic CLEAN is indistinguishable from a real scan.**  
   `buyer_policy_default.json` sets `malware_scan_required` to false. `file_quality` records a problem only for `INFECTED`, or for any non-CLEAN status when the flag is true.  
   Probe: deleting `malware_scan` on every India happy-path document → GEN-005 PASS, decision APPROVED.  
   `file_quality` never reads `malware_scan.synthetic` or `extraction.synthetic`. Demo files set `synthetic: true` and still pass as ordinary successes. That conflicts with principle 6 (label synthetic results; do not claim a check succeeded if it did not run). The fail-closed path exists only when the policy flag is turned on (covered by `test_malware_scan_required_but_unavailable_fails_closed`).

7. **`mask_deep` does not know the submission’s sensitive keys.**  
   `security.SENSITIVE_KEYS` includes `ifsc`, `aba`, `sort_code`, `cin`, `company_number`, and `value`, but bank routing is stored as `identifier` and company/CIN numbers are cross-checked as `registration_number`. Neither key is masked. Finding text uses `mask()` directly, so the demo findings stay masked. An audit or log of the raw submission through `mask_deep` would keep those values.

### Risky assumptions

8. **Several buyer-policy keys do nothing.**  
   `exactly_one_primary_bank_account` is never read; `bank_primary` always requires exactly one primary.  
   `address_mismatch_severity` is never read; `xref_address` always uses WARN.  
   `attempt_policy` in `resubmission.py` implements `escalate_after_failed_attempts` (3) and `lapse_pending_after_days` (14) and has no caller. The engine will not escalate or lapse on those defaults.

9. **`decide` ignores REQUIRED + FAIL / REVIEW_REQUIRED and waits for findings.**  
   `decision.decide`: those statuses hit `pass`. Today `derive_status` only returns FAIL when a BLOCKER or FIXABLE exists, and REVIEW_REQUIRED when an ESCALATE exists, so this still pendings or rejects. A future handler that sets FAIL with only WARN findings would approve.

10. **Declared indirect-tax status is accepted as NOT_APPLICABLE.**  
    Default `accept_declared_indirect_tax_status_with_reason` is true. The applicability reason says it is a declaration, not a legal determination, but the rule does not run and no finding is stored. Brief section 6.3 says a declaration alone is not a legal determination and unclear applicability goes to review. This is policy-shaped behaviour, and it is what the happy paths rely on for GST/VAT/sales tax.

11. **HMAC default key.**  
    `security.get_secret_key` uses `dev-only-insecure-key` when `VENDOR_HMAC_KEY` is unset. Fingerprints would be reproducible by anyone who knows that string.

12. **GSTIN and GB VAT checksums are local implementations.**  
    `validators.gstin_check_char` / `valid_gstin` match the fixture `27AAPFU0939F1ZV` and the module’s own warning: validate against authoritative vectors before production. `valid_gb_vat` is a 9-digit modulus-97 check (plus a +55 alternative, 12-digit branch numbers use the first 9). The brief says the same for HMRC. These passes do not mean the number was issued.

13. **Sanctions “match” includes weak name tiers.**  
    `SyntheticSanctionsAdapter.screen` treats EXACT, COSMETIC, FORM_MISSING, ABBREVIATED, and AMBIGUOUS as matches. That widens review; it does not create BLOCKER until `confirm_blocker`. The list is synthetic.

14. **`validate_polished` rejects substrings** `sanction`, `fraud`, `duplicate`, `screening`, and `risk` anywhere in the polished text (`communication.validate_polished`). That blocks obvious leaks and will also reject harmless wording that contains those letters.

15. **`file_quality` returns on the first unscanned file** when `malware_scan_required` is true (`return` inside the document loop). Later files are not checked. Status is NOT_RUN, so the decision still fails closed.

### Gaps versus the brief (not wired, or only partly wired)

16. **Jurisdiction dimension.** A tax registration outside the registration country does not turn on that country’s rules. An IN company is not run through GB VAT rules if it also has a GB VAT row, and the reverse. Bank country is evaluated per account. Operating country is used for the cross-border INFO note and as a required profile field.

17. **Brief section 9 items with no rule or slot:**
    - India sole proprietor: PAN and no incorporation demand are in place. There is no business-evidence slot for sole proprietors or for US/GB sole traders.
    - India partnership: deed slot plus PAN holder type. No partnership registration identifier.
    - US state of formation / state registration is not a profile field and not a validator. The formation **document** slot is required for corporation, LLC, and LLP.
    - US sales/use tax “format” check is `lambda v: bool(v)` in `us_sales_tax`. Any non-empty string passes.
    - `validators.valid_bic` is never called. `bank_identifiers` checks IBAN when present.
    - W-8 is review-only, and only inside `us_w9` when a W-9 file exists and `us_person` is false or the classification contains “foreign”. A missing W-9 is `GEN-004` `MISSING_DOC` (vendor is asked to upload a W-9).

18. **Section 6 fields not enforced by `profile_fields` or `bank_identifiers`:** phone, website, industry/sector, “same as registered address”, authorised-representative designation (only the name is required, and sole proprietors skip the representative), bank name, currency, holder name as its own required-field finding (a blank holder name falls through name comparison into “name differs”).

19. **Document pipeline steps that the core expects the caller to have done:** private storage, real file-signature bytes, malware scan, classification, extraction, file hash, duplicate-file detection. `signature_ok`, `detected_type`, `extraction`, and `malware_scan` are trusted fields on the dict. A client who can set `signature_ok: true`, `malware_scan.status: CLEAN`, and high-confidence extraction can satisfy those rules. The API must overwrite them server-side.

20. **No persistence and no audit write.** Fernet, SQLite lifecycle, and production RBAC from brief section 13 are not in this package. `AuditLog` is a library the API can call.

21. **Low-confidence threshold vs policy name.** `extraction_confidence` uses `attempts < max_reupload_attempts`. With the default value 2, attempt 1 asks for a re-upload and attempt 2 escalates. The vendor gets one re-upload, not two.

22. **Finding identity collisions.** `Finding.finding_id` ignores the message. Two issues with the same rule, subject, and code collapse in `diff_findings`.

---

## (e) Proposed build plan (brief sections 6, 11, and 14)

Do not rewrite `vendor_core` for the API. Call `OnboardingEngine`, `resolve_slots`, `build_vendor_message`, `validate_polished`, `AuditLog`, and the Fernet helpers. Bug fixes in the core, if you approve any from section (d), each get a regression test and stay separate from feature work.

**Stack is not locked here.** Brief section 16 and phase B require your approval. Candidate that matches `CURSOR_PROMPTS.md`, with the trade-off in one line:

| Choice | Candidate | Why this candidate, pending your yes |
|---|---|---|
| API | FastAPI | One Python process can import `vendor_core` directly. Contracts via Pydantic. |
| App database | SQLite for the demo | Matches the local prototype. PostgreSQL stays the production option in section 16; do not pretend SQLite is the production control. |
| Files | Private local directory, not static-hosted | Brief section 12. Cloud bucket stays open. |
| Vendor portal and procurement UI | React + Vite + TypeScript | Two frontends as in section 14 phases C and D. Next.js is the alternative if you want server rendering; say so before phase C. |
| Live timeline | Server-Sent Events | The engine already emits ordered stage events (`step_delay` exists). |
| Auth for the demo | Role switcher labelled as not real authentication | Brief section 4: production RBAC is required later. Demo header such as `X-Demo-Role` must be obvious in the UI. |
| OCR / malware / email / registries | Not connected | Synthetic extraction adapter only, every result labelled SYNTHETIC. |

Say if any row should change before implementation starts.

### Phase B — API and contracts (brief 14.B, data from section 6, behaviour from section 11)

Separate response models: a vendor model built only from `EvaluationResult.to_dict(internal=False)`, and internal models for procurement vs compliance. Do not filter only in the UI.

Vendor routes (own applications only):

- Create draft and patch any of the five sections (autosave). Keep the submitted strings. Store normalised values only as derived columns if needed, never overwriting the source.
- `GET` requirements: call `resolve_applicability` / `resolve_slots` for country, entity, categories, jurisdictions, and policy. Return which fields and slots are REQUIRED, CONDITIONAL, RECOMMENDED, OPTIONAL, or REVIEW_REQUIRED.
- Document upload into a slot id: PDF/JPG/JPEG/PNG, max 10 MB from policy, signature check, sha256, private path, attempt counter. Server sets `signature_ok`, scan, and extraction. Ignore client-supplied extraction and scan fields.
- Pre-submit: block only missing mandatory profile fields and applicable REQUIRED slots. Return WARN-level items separately. Do not run risk rules to decide whether the submit button is enabled, and do not show internal findings.
- Submit: record actor, timestamp, declaration text/version, new immutable version, application reference. Then `evaluate`. First version has `previous=None`. Later versions pass the prior `EvaluationResult`.
- Vendor status: milestones from `vendor_tracking`, document statuses, vendor message. Persist and return the message from `build_vendor_message`. If an LLM polishes it, accept the text only when `validate_polished` returns true; otherwise keep the template.

Internal routes:

- Queue with status, state, country, needs-review, sorted by `risk_score`.
- Detail: full sections, slot states, vendor-visible actions, and internal findings. Procurement does not receive screening match detail or `confirm_blocker` reasons. Compliance/admin can. Identifiers in every role’s normal view are last-4 only.
- Reviewer actions `resolve_escalation` and `confirm_blocker` (compliance/admin), then re-evaluate. The core already voids risk resolutions when bank/tax details change after a flag.
- Audit read: event type, actor, timestamp, application version, rule version, decision. Payloads passed through `mask_deep` after the key list covers `identifier` and `registration_number` (defect 7), or masked explicitly before append.
- SSE of the engine’s stage events for one version, for the procurement timeline. Vendor clients do not subscribe to that stream.

Persistence sketch:

- Application row: reference, state, decision status, current version.
- Version row: immutable submission JSON. Encrypt `account_number`, tax `value`, and `iban` with Fernet. Key from `VENDOR_FERNET_KEY`, never committed. `VENDOR_HMAC_KEY` required for fingerprints (no silent default in the API process).
- Evaluation row: masked `to_dict(internal=True)` for reviewers, plus the vendor view that was actually sent.
- Document row: slot, original filename, sha256, path, status, attempts.
- Audit: `AuditLog` or a hash-chained table with the same fields.

Tests to add with the API: vendor responses for the duplicate-bank and sanctions scenarios contain none of `duplicate`, `V-1001`, `screening`, `sanction`, or raw ids; presubmit ignores risk-only failures; role split; resubmission diff; upload type/size; raw account number absent from the database file bytes.

### Phase C — Vendor portal (brief section 6 and 14.C)

Five sections, in order, with edit links from review:

1. **Business profile** — registration country, legal name, trading name, entity type options from `country_rules.json` for IN/US/GB, website optional, registered address, operating countries, optional operating address, vendor category multi-select, conditional goods/services text, industry if you add it to config, contact name, email, phone as optional, authorised representative where the core requires it.
2. **Tax and registration** — repeatable jurisdiction rows. Separate registration id, direct tax, and indirect tax. Status values `registered`, `not_registered`, `application_pending`, `not_applicable`, each with a reason. Do not present a declaration as a government determination.
3. **Banking** — repeatable accounts, bank country independent of registration country, country-specific identifier (IFSC, ABA plus ACH/wire, sort code, IBAN when supplied), account number as text, exactly one primary.
4. **Documents** — slots from the requirements endpoint, grouped as in section 6.5. Show file status. Low confidence: re-upload copy first; after the configured attempt, show human-review copy.
5. **Review and submit** — masked ids (last 4), slot completeness, warnings vs blocking gaps, declaration with version, then the generated reference and vendor milestones.

Autosave on section edits. Resume a draft by reference. After submit, show only the vendor status payload. Correction resubmit sends changed fields/files and creates a new version.

Label every scan, extraction, and screening line that did not call a live provider with the visible word SYNTHETIC.

### Phase D — Procurement dashboard (brief 14.D and section 11)

- Queue and filters (status, state, country, needs review).
- Application detail: five sections, document statuses, vendor-visible actions, internal findings in a separate block that procurement cannot see when the item is a duplicate, screening, or fraud signal.
- Reviewer actions and notes for compliance/admin, written to the audit timeline.
- Timeline: who, what, when, rule version, decision, communication reference. Masked values only.

### Explicitly later (brief 14.E and 14.F) — not part of the first build

Live OCR, malware scanner, registry, bank, sanctions, and email providers. End-to-end pitch of IN/US/GB happy paths plus the four edge cases, with a spoken line on what is synthetic.

### Core fixes to approve or defer before phase B

Recommend fixing before the API stores decisions, because they change outcomes:

- Defects 1 and 2 (resubmission reuse).
- Defect 3 (boolean coercion) at the API boundary even if the core stays strict about JSON booleans.
- Defect 4 (invalid dates).
- Defect 6 at least as a SYNTHETIC / NOT_RUN label on file and extraction checks, so the UI cannot show a scan as a real pass.

Defer unless you want them in the same pass: policy keys that are unread (8), first-of-type tax rows (5), `mask_deep` key list (7), BIC and the section 9 evidence gaps (17). Those change product behaviour and need your call.

No code changes will be made until you approve this report and the stack row above.
