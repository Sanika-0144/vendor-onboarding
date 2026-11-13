# Configurable Global Vendor Onboarding System
## Product, workflow, verification logic and Cursor implementation brief

**Document version:** 1.0  
**Prepared:** 12 November 2026  
**Purpose:** Single source of truth for building the agreed MVP in Cursor AI.

> **Status note:** This document consolidates decisions made during product-design discussions and describes the current local Python backend-logic prototype. It is a build specification, not legal/tax advice, a production security certification, or evidence that external verification integrations are live.

---

## 1. Executive summary

Build a configurable, multi-country vendor onboarding system that accepts vendor submissions and supporting documents, evaluates them using country-, entity-, category-, jurisdiction- and buyer-policy-specific rules, and produces one explainable overall status: **APPROVED, PENDING or REJECTED**.

The system should reduce manual procurement work, improve consistency, surface discrepancies before payment setup, request missing/corrected information from vendors, route ambiguous or high-risk cases to authorised reviewers, and preserve a traceable history of submissions and decisions.

The MVP supports **India (IN), United States (US), and United Kingdom (GB)**, and both **goods suppliers and service providers**. It supports common legal forms including companies, LLPs, partnerships, sole proprietors/sole traders and an `other` route that requires human review until configured.

### Product promise

- Collect the right information for the vendor's circumstances.
- Apply only rules that are relevant and explicitly configured.
- Use AI for document classification/extraction assistance, not final decisions.
- Use deterministic code for validation, cross-checking and status decisions.
- Explain every actionable issue and communicate vendor-safe next steps.
- Keep internal risk signals private from vendors.

## 2. Problem statement and business context

Before paying a vendor, a company needs to establish that the vendor's identity, tax/registration details and payment information are sufficiently supported and consistent. Manual onboarding commonly involves incomplete forms, wrong documents, mismatched business and bank names, incorrect identifiers, jurisdiction inconsistencies, repeated email follow-ups and fragmented audit trails.

The product takes a vendor submission as input and produces an explainable onboarding outcome. For non-approved applications it must identify what information or review is needed. It must not equate a syntactically valid identifier with proof that an entity or account is genuine.

### Business objectives

1. Reduce manual collection and checking effort.
2. Apply consistent, configurable rules across supported countries.
3. Detect missing, malformed, inconsistent, stale, duplicate or uncertain information.
4. Produce transparent Approved/Pending/Rejected decisions.
5. Send actionable vendor correction requests without exposing sensitive internal risk signals.
6. Preserve application versions, findings, decisions and review history.

## 3. Scope and decisions already agreed

### 3.1 Confirmed product decisions

| Topic | Agreed decision |
|---|---|
| Product | Configurable Global Vendor Onboarding System |
| Countries | India, US, UK; use ISO-style codes `IN`, `US`, `GB` |
| Vendor categories | Goods and Services; multi-select allows either or both |
| Legal structures | Support common company/corporation, LLP, partnership, sole proprietor/sole trader structures; route unknown types to review |
| Submission channel | Vendor self-service portal plus internal procurement experience |
| MVP scope | Configurable onboarding and verification engine, not a full global verification provider platform |
| Overall statuses | `APPROVED`, `PENDING`, `REJECTED` only |
| Tax jurisdictions | Multiple registrations/jurisdictions per vendor are supported |
| US tax documents | W-9 workflow for applicable US persons; foreign/uncertain payees route to tax review (W-8 family not implemented in MVP) |
| GST/VAT/sales tax | Conditional applicability, not universally mandatory |
| Bank accounts | Multiple accounts; exactly one primary account for the application/profile under the agreed buyer-policy default |
| Bank ownership mismatch | Conditional acceptance where policy permits, with evidence and human review; not automatic rejection |
| Bank verification | Document-based MVP; future API integration points only |
| Document upload | Structured upload slots |
| Accepted document formats | PDF, JPG, JPEG, PNG |
| Low-confidence extraction | Ask for clearer re-upload first; if unresolved, offer/route to human review |
| Drafts | Automatically save progress |
| Pre-submit checks | Block missing mandatory fields/required documents; allow non-blocking warnings |
| Vendor tracking | Full vendor-facing milestones/status/actions; keep internal risk findings private |
| AI role | Classify/extract/draft wording only; AI does not decide final status |
| Decision logic | Deterministic rule/finding roll-up; fail closed for unresolved required checks |

### 3.2 Five-dimensional rule applicability

Every rule is evaluated against the following context:

1. Country of legal registration (where relevant to the rule).
2. Legal entity type.
3. Vendor category (goods, services or both).
4. Relevant jurisdiction for the specific rule (registration, tax, bank or operating jurisdiction).
5. Buyer policy.

The rule engine must not confuse registration country with tax, operating or bank country. A business registered in India may legitimately have a UK bank account or tax registrations in more than one jurisdiction. Cross-border differences should be evaluated, not automatically rejected.

### 3.3 Out of scope for initial MVP

- Full country coverage beyond IN/US/GB.
- Complete legal/tax advice or autonomous legal interpretation.
- Live verification against every government registry.
- Live bank account ownership verification.
- Full sanctions-screening integration.
- Automated W-8 document processing for foreign US payees (review route only).
- Definitive AI forgery detection.
- Production-grade identity verification/KYC unless separately scoped.

## 4. Users and access boundaries

### Vendor / supplier

Creates and edits a draft, submits business/tax/bank information, uploads requested documents, sees vendor-safe status milestones, receives correction requests and resubmits only the changed information.

### Procurement analyst

Views applications, completeness, verification results, vendor-visible corrections, status, application history and non-sensitive supporting information needed for the role.

### Compliance / finance reviewer

Reviews escalations such as ownership ambiguity, possible duplicates, sanctions potential matches, unusual document findings or unresolved tax applicability. Access to sensitive identifiers must be permission-controlled and audited.

### System administrator / policy owner

Maintains country/entity/category/buyer-policy configurations, effective dates, rule versions, permitted document types and reviewer permissions. Legal/tax rules need qualified policy ownership and current source references.

**Role-based access control is required for production.** The local prototype does not yet provide a complete authentication/RBAC implementation.

## 5. End-to-end workflow

1. Vendor opens the portal and creates/continues a draft.
2. Vendor selects registration country, legal entity type, vendor category and operating/tax/bank jurisdictions as relevant.
3. The applicability engine resolves the required fields, identifiers and document slots using the five dimensions and buyer policy.
4. Vendor completes the Business Profile.
5. Vendor enters Tax & Registration details for one or more tax jurisdictions.
6. Vendor enters one or more bank accounts, designating exactly one primary account.
7. Vendor uploads documents into structured slots.
8. The document pipeline performs file checks, classification/extraction via adapters, confidence handling and deterministic cross-checks.
9. Review & Submit shows the summary, missing mandatory items, non-blocking warnings and declarations.
10. Submission creates a unique application reference and immutable version/event history.
11. The verification engine runs the resolved rules and generates CheckResult/Finding objects.
12. Decision engine returns APPROVED, PENDING or REJECTED.
13. Vendor receives safe actionable corrections if needed; internal risk findings remain private.
14. Resubmission detects changed inputs, reruns dependent checks and records resolved/still-open/new findings.
15. Procurement/compliance users track and review the application.

### Separate state concepts

- `application_state`: for example `DRAFT`, `SUBMITTED`, `PROCESSING`, `ACTION_REQUIRED`, `UNDER_REVIEW`, `COMPLETED`.
- `decision_status`: `null` before decision, then `APPROVED`, `PENDING` or `REJECTED`.
- Document-level status: `RECEIVED`, `PROCESSING`, `ACCEPTED`, `ACTION_REQUIRED`, `HUMAN_REVIEW`.

A complete submission is not the same as an approved vendor. Pre-submission completeness checks are not full verification.

## 6. Vendor portal specification

### 6.1 Section 1 — Business Profile

**Business identity**
- Country of legal establishment/registration — required.
- Legal business name (or proprietor's legal name) — required.
- Trading/brand name — optional.
- Legal entity type — required; options loaded by country.
- Website — optional.

**Business location**
- Registered office/principal business address — required.
- Operating countries — required as defined by product workflow.
- Operating address — optional.
- “Same as registered address” — checkbox.

**Vendor classification**
- Vendor category — required multi-select: Goods, Services, or both.
- Products supplied — conditional when Goods selected.
- Services provided — conditional when Services selected.
- Industry/business sector — capture as configured; allow an “Other” value and avoid silently excluding legitimate suppliers.

**Contacts**
- Primary contact name — required.
- Business email — required.
- Phone — recommended/optional under policy.
- Authorised representative name and designation/relationship — required where applicable. For a sole proprietor, proprietor may be the authorised representative.

Preserve the submitted legal name and trading name separately. Keep original strings; normalised values are derived comparison data and must not overwrite source values.

### 6.2 Entity types to configure

| Country | Initial entity categories |
|---|---|
| India | Private limited company, public limited company, LLP, partnership, sole proprietorship, other |
| US | Corporation, LLC, LLP where applicable, partnership, sole proprietorship, other |
| UK | Private limited company, public limited company, LLP, partnership, sole trader, other |

This is a product taxonomy, not an exhaustive legal classification. Entity-type options and evidence requirements must be confirmed against current local rules. Unknown/unconfigured entity types go to human review instead of being guessed.

### 6.3 Section 2 — Tax & Registration

Keep three concepts separate:
1. Legal business registration identifier/evidence.
2. Direct tax identity/documentation.
3. Indirect tax registration (GST, VAT, relevant state sales/use taxes).

Use an array of registration records; do not assume one vendor has only one tax jurisdiction.

**India (`IN`)**
- PAN: applicable taxpayer/person/entity identifier; applicability and holder type depend on legal/tax facts.
- CIN: for applicable companies.
- LLPIN: for LLPs.
- Partnership evidence: where applicable.
- GSTIN: conditional; do not require every vendor to provide GSTIN. Assess applicability under configured current rules and buyer policy.
- For sole proprietors, distinguish proprietor identity from trading name.

**United States (`US`)**
- State of formation and state registration details for relevant entities.
- W-9 document workflow for applicable US persons; extract tax classification, legal name, business/disregarded entity name where present, and TIN reference securely.
- A sole proprietor may need to provide the owner's appropriate TIN rather than assuming EIN.
- Foreign-person or uncertain classification routes to tax review; initial MVP does not implement complete W-8 processing.
- State sales/use tax registrations are conditional based on state, activity and applicable rules.

**United Kingdom (`GB`)**
- Companies House number for applicable registered companies/LLPs; not for every sole trader or general partnership.
- UTR where relevant to the tax relationship.
- VAT number and certificate only when registered; applicability is conditional and must not be based on one turnover field alone.

**Status choices for indirect tax**
- `registered`
- `not_registered`
- `application_pending`
- `not_applicable`

A vendor declaration alone must not be treated as a legal determination. If applicability is unclear, route to review. Store the assessment reason and source/policy version.

### 6.4 Section 3 — Banking Information

Support multiple accounts. Exactly one primary account is required under the agreed standard buyer policy. Each account is independently evaluated.

**Common fields**
- Bank country — required and separate from business registration country.
- Bank name — required.
- Branch — optional where relevant.
- Account holder name — required.
- Account holder type — business, individual, joint, other.
- Account type — country/payment-specific options.
- Currency — required.
- Account number — required, stored as a string to preserve leading zeroes, protected at rest.
- Primary account flag — exactly one primary.

**Country identifiers**
- India: IFSC and account number.
- US: ABA routing number, routing use/type (ACH or wire as applicable), and account number.
- UK: sort code and account number; IBAN/BIC where relevant to international payments.

**Account ownership**
- Relationship options can include same legal entity, sole proprietor, director/authorised individual, parent/subsidiary/related party, joint, other.
- Mismatch is not automatic fraud. Request relationship explanation and appropriate evidence; route uncertain/related-party cases to human review under buyer policy.
- Unrelated third-party accounts are escalated; do not approve until the relationship is established.

**Evidence**
- Bank confirmation letter, appropriate bank statement excerpt, cancelled cheque where accepted, or other policy-approved bank evidence.
- Collect only relevant portions; avoid unrelated transaction data where possible.

**MVP boundary:** Document-based comparison only. No live bank ownership API is connected. Format/reference checks do not prove account ownership.

### 6.5 Section 4 — Supporting Documents

Use structured upload slots, not a single uncontrolled upload area. Slots are generated from country + entity type + vendor category + jurisdiction + buyer policy.

Document groups:
- Business registration evidence.
- Tax documents and declarations.
- Banking evidence.
- Category/business-specific certifications or licences.
- Authorisation and additional supporting evidence.

Each requirement is classified as `REQUIRED`, `CONDITIONAL`, `RECOMMENDED` or `OPTIONAL`.

**Accepted formats:** PDF, JPG, JPEG, PNG. Proposed initial maximum: 10 MB per file (configurable).

**Processing pipeline**
1. Upload to private storage.
2. Check extension, file signature, size, integrity and basic safety.
3. Obtain malware scan result from an actual approved scanner adapter.
4. Classify document type; compare detected type with expected slot.
5. Extract fields using an approved OCR/document-AI adapter.
6. Return field-level values, confidence, page/source location and extraction status; do not infer absent values.
7. Apply field-specific confidence thresholds; do not use one universal threshold without calibration.
8. Run deterministic validations and cross-reference checks.
9. Generate structured findings.
10. Mark document `ACCEPTED`, `ACTION_REQUIRED` or `HUMAN_REVIEW` as applicable.

**Low-confidence path:** Ask vendor for a clearer upload first. If confidence remains inadequate after configured attempts, route to human review. Critical missing/uncertain fields must never be guessed or silently approved.

**Other controls:** Hash files for exact duplicate identification; keep file versions; preserve the original upload; treat suspected alteration as a review signal, not a definitive automated forgery verdict. File signature checks are not malware scanning.

### 6.6 Section 5 — Review & Submit

- Show a summary of all five sections with edit links.
- Mask tax identifiers and account numbers.
- Show document-slot completeness and outstanding actions.
- Automatically save drafts.
- Pre-submit validation blocks only missing mandatory fields and mandatory applicable documents; non-blocking warnings are allowed.
- Vendor confirms information accuracy and authority to submit.
- Record actor, timestamp, declaration text/version and application version.
- On submission, generate unique application ID, timestamp and submission version.
- Show full vendor-facing tracking milestones and actions, but never expose internal-only findings, sanctions signals or confidential reviewer notes.
- Allow vendor to correct/resubmit only affected fields/documents where possible.

## 7. Document-processing and AI architecture

### AI responsibilities
- Classify uploaded document type.
- Extract printed information into schema-bound structured output.
- Provide field-level confidence and source/page references.
- Assist with wording of vendor communications only from approved finding data.

### Deterministic-code responsibilities
- Resolve applicability.
- Check required fields and documents.
- Validate identifier formats/checksums where implemented.
- Compare identifiers and names.
- Evaluate dates/expiry against versioned policy.
- Compare extracted data against submitted form.
- Detect duplicates in the platform database.
- Aggregate findings and determine final status.
- Filter vendor-visible vs internal-only information.

### Human responsibilities
- Resolve unclear applicability and unusual entity types.
- Review ambiguous name/ownership relationships.
- Investigate potential duplicate, sanctions or suspicious document matches.
- Approve policy exceptions where authorised.

**LLM must never make the final Approved/Pending/Rejected decision.** All model outputs are untrusted inputs and must be validated by code.

## 8. Rule applicability and validation framework

### 8.1 Applicability states
- `REQUIRED`: must run and be satisfied.
- `CONDITIONAL`: requires explicit condition resolution before treating as required or not applicable.
- `OPTIONAL`: run if information is supplied, but omission does not block.
- `NOT_APPLICABLE`: skip and record reason; this is not a pass.
- `REVIEW_REQUIRED`: human/policy resolution needed.

### 8.2 Standard `CheckResult`
Each rule execution returns one structured result containing:
- `rule_id`
- `applicability`
- `check_status` (`PASS`, `FAIL`, `REVIEW_REQUIRED`, `NOT_RUN`, `ERROR`)
- `findings[]`
- `evidence_refs[]`
- `rule_version`
- metadata/subject reference as needed.

A rule may produce multiple findings. A finding represents one issue; CheckResult represents one rule execution.

### 8.3 Standard `Finding`
- Unique `finding_id`.
- `check_id` / `rule_id`.
- `severity`.
- affected fields.
- safe explanatory message.
- vendor visibility flag.
- remediation/action text.
- escalation flag.
- evidence references (protected references, not secret raw values).

### 8.4 Severity levels
| Severity | Meaning | Decision effect |
|---|---|---|
| `PASS` | Check succeeded | No issue |
| `INFO` | Cosmetic normalisation or note | Non-blocking |
| `WARN` | Concern/reminder | Non-blocking unless buyer policy says otherwise |
| `FIXABLE` | Vendor can correct | `PENDING` |
| `ESCALATE` | Human review needed | `PENDING` |
| `BLOCKER` | Confirmed configured disqualifying condition | `REJECTED` |

Applicability, check status and severity are separate. A check can be `NOT_APPLICABLE` and `NOT_RUN`; this does not mean it passed.

### 8.5 Decision roll-up
- If a confirmed configured `BLOCKER` exists → `REJECTED`.
- Else if any required rule is missing, failed, errored, not run, conditional/unresolved or review-required → `PENDING`.
- Else if any fixable or escalated finding remains → `PENDING`.
- Else if all expected required checks ran and passed → `APPROVED`.
- A non-empty expected required-rule set is mandatory; an empty rule set must not approve.
- Technical failures and unavailable integrations must never silently become approval.
- Similarity scores and suspected signals alone are not proof of fraud and must not create a blocker.

## 9. Country rule matrix — initial inventory

The following is the MVP rule inventory, not a complete legal determination. Before production, confirm current applicability, accepted evidence, formats, checksum/reference sources and effective dates with authoritative sources and qualified policy owners.

### India (`IN`)
- PAN: applicability/holder type based on taxpayer/entity facts; format check when applicable.
- CIN: companies; syntax plus appropriate evidence/registry reference.
- LLPIN: LLPs; syntax plus appropriate evidence/registry reference.
- Partnership: applicable partnership identity/evidence; requirements vary.
- Sole proprietorship: proprietor identity and appropriate business evidence; no automatic incorporation-certificate demand.
- GSTIN: conditional registration applicability; syntax/checksum and certificate consistency when supplied; live status lookup only if integrated.
- IFSC: format and reference validation for Indian bank accounts.

### United States (`US`)
- State of formation/registration details for applicable entities; state-specific rules.
- W-9 for applicable US persons; extract taxpayer name, business/disregarded entity name, tax classification and TIN securely.
- Foreign person/uncertain classification → tax review; no complete W-8 workflow in initial MVP.
- EIN: syntax check only when supplied; does not prove issuance/ownership.
- State sales/use tax: conditional based on state, activities and applicable obligations.
- ABA routing: nine-digit structure/check digit validation; ACH/wire routing context must be captured. No live bank ownership verification.

### United Kingdom (`GB`)
- Companies House number for applicable registered companies/LLPs; not for all sole traders/partnerships.
- UTR where relevant; not interchangeable with company number.
- VAT registration conditional; check number format and use HMRC lookup only if integrated and authorised.
- Sort code for UK domestic banking; account number checks are conservative syntax only.
- IBAN/BIC where relevant to international payment arrangements.

### Cross-country checks
- Form legal name vs registration/tax/bank documents.
- Form identifier vs document identifier (exact after only explicitly allowed separators/case normalisation).
- Address consistency (warn/review, not automatic rejection).
- Bank country vs payment context (evaluate cross-border legitimacy; no automatic failure).
- Duplicate tax/company IDs and bank accounts against existing vendor records.
- Name/trading name/director/signatory screening and sanctions only through configured, authorised sources; potential matches go to human review.

## 10. Edge cases for MVP demonstration

These are recommended demo scenarios based on the design discussion. The final 2–4 pitch scenarios should be selected and confirmed during testing.

1. **Cosmetic name variation:** `ABC Manufacturing Pvt. Ltd.` vs `ABC Manufacturing Private Limited`. Normalise conservatively, preserve original values, pass with an informational note if the entity form is consistent.
2. **Sole proprietor personal bank account:** Vendor legal identity is the proprietor; bank account is in proprietor's name. Do not automatically reject; evaluate policy/evidence and route unclear cases to human review.
3. **Tax identifier mismatch:** Form PAN/TIN differs from uploaded tax document. Generate vendor-visible `FIXABLE` finding and set overall status to `PENDING` unless evidence establishes a blocker.
4. **Duplicate bank account / unexplained third-party account:** Compare against existing vendor records. Keep the signal internal, investigate relationships and only reject if a configured disqualifying condition is established.

Additional test scenarios: cross-border bank account; missing/expired document; low-confidence extraction with re-upload then reviewer fallback; multiple bank accounts with zero or two primary accounts; unresolved GST/VAT applicability; unavailable registry/bank service; changed bank details after a risk flag.

## 11. Communication, resubmission and audit

### Vendor communication
- Vendor messages are built from vendor-visible findings and remediation text.
- Every vendor-visible fixable finding must appear in the correction request.
- LLM may polish wording but cannot add/drop actions or invent reasons; validate output against finding IDs and fall back to deterministic templates.
- Internal-only findings (potential sanctions, duplicate-account signals, fraud review) remain private to authorised reviewers.
- Never tell a potentially suspicious vendor exactly which confidential risk signal triggered screening if doing so could disclose internal controls.

### Resubmission
- Keep original submission and document versions.
- Define input dependencies for every rule.
- Detect changes using field/document fingerprints; use HMAC for sensitive comparison fingerprints rather than storing raw values in diff metadata.
- Rerun checks whose dependencies changed.
- Rerun all relevant risk checks if tax ID or bank details change after a flag.
- Produce `resolved`, `still_open` and `newly_introduced` finding groups.
- Current prototype defaults include escalation after 3 unsuccessful attempts and lapsed pending after 14 days; these are configurable buyer-policy defaults, not universal requirements.

### Audit history
Record event type, actor reference, timestamp, application/version, rule version, findings, decision and communication reference. Mask sensitive values in logs. Local JSONL hash chaining detects certain edits but is not tamper-proof if an attacker can rewrite the full file. Production needs protected central logs, access control, backups and external integrity anchoring.

## 12. Security and privacy requirements

- Encrypt sensitive tax/bank values at rest.
- Keep raw identifiers out of logs, findings and normal UI views; mask values (e.g. last four digits only where appropriate).
- Store documents in private, access-controlled storage.
- Use secrets manager/key vault for encryption keys; never commit keys.
- Apply role-based access controls and audit access to sensitive values.
- Do not send full SSN/ITIN/EIN, bank account numbers or full bank statements to an ordinary external LLM.
- Collect only relevant pages/fields; encourage redaction of unrelated bank transactions.
- Use actual malware scanning and safe file parsing before processing.
- Apply retention/deletion policy, consent/privacy notices, key rotation, rate limits and backups before production.
- Protect email delivery and prevent vendor-facing messages from leaking internal risk findings.

## 13. Current backend prototype — what exists today

The existing local Python backend package is a logic MVP, not a complete deployed web application.

| Module/file | Responsibility |
|---|---|
| `vendor_validation.py` | Enums, Finding/CheckResult, required fields, name/identifier comparisons, date validation |
| `applicability_engine.py` | VendorContext, RuleDefinition, five-dimensional applicability resolution |
| `country_validators.py` | India/US/UK syntax/checksum validators and bank identifier checks |
| `document_verification.py` | File signature/size/extension checks, document slots, extraction metadata/confidence, W-9 checks and cross-references |
| `risk_checks.py` | Account ownership relationship review and duplicate checks |
| `onboarding_engine.py` | Orchestrates applicable checks for a submission |
| `decision_engine.py` | Deterministic Approved/Pending/Rejected roll-up |
| `vendor_communication.py` | Vendor-safe correction messages; internal finding filtering |
| `resubmission.py` | Dependency-aware reruns, change detection, HMAC fingerprints, attempt/lapse policy |
| `external_verification.py` | Protocols/contracts for registry, bank and sanctions adapters; no live provider connected |
| `application_lifecycle.py` | Local SQLite application/draft/submission storage with Fernet encryption |
| `audit_trail.py` | Local JSONL append-only hash-chained events and common sensitive-key masking |
| `country_rules.json` | Country/entity/category and buyer policy defaults |
| `rule_catalog.json` | Initial versioned rule catalogue |
| `rule_dependencies.json` | Input-to-rule dependency map |
| `demo.py`, `demo_submission.json` | Fictional demo cases |
| `test_vendor_validation.py`, `test_complete_logic.py` | Unit and integration tests |

The delivered package reports 120 tests passed and 0 failed. The demo produces an Approved consistent Indian vendor and a Pending PAN/document mismatch case. Re-run tests in the target environment before relying on the result.

### Prototype limitations — do not overstate
- Document classification, extraction and malware-scan results in the demo are synthetic adapter outputs; no live OCR/LLM/antivirus service is connected.
- No live government registry, bank, sanctions or external verification provider is connected.
- Syntax/checksum validators do not prove identifier issuance, active status, legal applicability or ownership.
- GSTIN checksum helper is a secondary implementation and requires independent validation against authoritative test vectors before production use.
- UK bank account-number checks are conservative; banking-format exceptions need configuration.
- W-8 workflow is review-only; no complete W-8 extraction/process.
- SQLite/Fernet local storage and JSONL hash chain are development/demo controls, not production security certification.
- No complete frontend, production API deployment, user authentication/RBAC, real email delivery, cloud object storage, data retention enforcement or production monitoring is included.

## 14. Cursor implementation plan

### Phase A — Repository inspection and baseline
1. Extract/open the existing `vendor_onboarding_backend_mvp.zip` folder in Cursor.
2. Read `README.md` and `SOURCE_INDEX.md` first.
3. Run tests and demo before making changes.
4. Preserve existing interfaces and tests; do not rewrite the backend without a reason.
5. Identify any defects or missing functionality and propose a plan before modifying files.

### Phase B — API and data contract design
1. Propose API framework and endpoint contracts; framework has not yet been selected by the product owner.
2. Define request/response schemas for vendor profile, tax records, bank accounts, document uploads, application tracking and reviewer actions.
3. Separate public vendor-safe endpoints from internal reviewer/admin endpoints.
4. Define authentication, role permissions and ownership checks.
5. Obtain product-owner approval for framework/database/storage choices before locking them in.

### Phase C — Vendor portal
1. Build five sections exactly as specified.
2. Implement dynamic country/entity/category/jurisdiction/buyer-policy fields.
3. Implement automatic draft save and resume.
4. Implement structured upload slots and file status UI.
5. Implement masked review summary, declarations and pre-submit validation.
6. Generate application reference and tracking milestones.

### Phase D — Procurement dashboard
1. Application queue with status and basic filters.
2. Application detail view with sections, document statuses and findings.
3. Separate vendor-visible actions and internal-only findings.
4. Reviewer assignment, resolution notes and authorised status transitions.
5. Audit-history timeline.

### Phase E — Real adapters and integrations
1. Connect a secure OCR/document-AI provider; validate model output as untrusted input.
2. Connect an approved malware scanner.
3. Add registry/bank/screening providers only after access, legal basis, credentials and test arrangements are confirmed.
4. Implement secure email delivery and message templates.
5. Add monitoring, retry, timeout and provider-unavailable behaviour.

### Phase F — End-to-end test and demo
1. Run happy paths for IN, US and GB.
2. Run 4 selected edge cases.
3. Verify role-based privacy and internal finding filtering.
4. Test resubmission and rule dependency reruns.
5. Prepare five-minute demo and clear statements of what is real vs simulated.

## 15. Acceptance criteria for the Cursor build

The MVP is ready for demo when:

1. A vendor can create, save, resume and submit an application.
2. The form adapts to country, entity type and goods/services selection.
3. Multiple tax registrations/jurisdictions can be stored.
4. Multiple bank accounts can be added and exactly one primary selected.
5. Bank ownership mismatch follows configured conditional review rather than automatic rejection.
6. Documents are uploaded to structured slots and their processing state is visible.
7. Pre-submit blocks only mandatory omissions and applicable required documents.
8. Required checks cannot be silently skipped; unresolved or errored required checks cannot approve.
9. Final decision is exactly Approved, Pending or Rejected.
10. Pending applications show actionable vendor-safe correction requests.
11. Internal risk findings are not exposed to vendors.
12. Resubmission preserves versions and reruns dependent rules.
13. Sensitive values are masked/encrypted and access is role-controlled.
14. Audit history records who/what/when/rule version/decision.
15. Automated tests and the fictional demo run successfully in the local environment.
16. UI and demo clearly identify synthetic or unavailable integrations.

## 16. Decisions still open — do not silently assume

The following have not been locked by the product owner:
- Frontend framework (React/Next.js or alternative).
- API framework (FastAPI or alternative).
- Production database (PostgreSQL or alternative); current prototype uses SQLite locally.
- Cloud/file storage provider.
- Authentication provider and exact roles/permission model.
- Email provider.
- OCR/document-AI provider.
- Malware scanning provider.
- Real government registry, bank and sanctions providers.
- Exact production retention schedule and jurisdiction-specific privacy/compliance controls.
- Final 2–4 pitch edge cases (the four scenarios in this document are recommended candidates).
- Exact country/entity-specific legal applicability rules, current formats and official reference data; these require authoritative validation before production.

Cursor must present options and trade-offs for material product/architecture decisions and wait for the product owner's approval. Do not invent credentials, external integrations, legal rules or successful verification outcomes.

## 17. Suggested project structure

```text
vendor-onboarding/
  backend/
    app/
      api/
      schemas/
      services/
      validators/
      rules/
      integrations/
      security/
      persistence/
    tests/
  frontend/
    vendor-portal/
    procurement-dashboard/
  configs/
    countries/
    entity_types/
    vendor_categories/
    buyer_policies/
  docs/
    product_brief.md
    api_contracts.md
    rule_matrix.md
  scripts/
  README.md
```

This is a proposed structure for the full product. Keep the current backend prototype intact until the integration/refactor plan is approved.

## 18. Copy/paste instruction for Cursor AI

> You are working on the Configurable Global Vendor Onboarding System. First inspect the existing backend project and read its README, source index, tests and configuration files. Preserve the existing Python validation/decision logic and its tests. The agreed MVP supports India (IN), US (US) and UK (GB), goods and services, common legal entity forms including sole proprietors/sole traders, multiple tax jurisdictions and multiple bank accounts with exactly one primary. The system uses a five-dimensional rule applicability model: registration country, entity type, vendor category, the specific tax/bank/operating jurisdiction and buyer policy. It uses structured CheckResult/Finding objects, AI-assisted document classification/extraction, deterministic validation and final status decisions (APPROVED/PENDING/REJECTED). AI must never decide the final status. Unresolved applicability, missing required checks, technical errors and unavailable required verification must not silently approve. Vendor messages must include every vendor-visible fixable item and must not reveal internal-only risk findings. The vendor portal has five sections: Business Profile, Tax & Registration, Banking Information, Supporting Documents, Review & Submit. Drafts auto-save, pre-submit blocks only missing mandatory applicable requirements, and vendors receive full safe tracking. Document uploads use structured slots and PDF/JPG/JPEG/PNG. Uncertain critical extraction requests re-upload, then human review if unresolved. No live OCR, malware scanner, government, bank or sanctions provider is currently connected; do not claim otherwise. Before choosing a frontend framework, API framework, production database, storage, authentication, email or AI provider, present options and trade-offs and wait for approval. Work incrementally, write/maintain tests, run the full test suite after changes, explain each material change and keep the README current. Use the attached Product Brief as the product source of truth.

---

## Appendix A — Glossary

- **Applicability engine:** Resolves whether each rule is required, conditional, optional, not applicable or needs review.
- **CheckResult:** Structured result of one rule execution.
- **Finding:** One issue/note emitted by a check, with severity, affected fields and remediation.
- **Deterministic validation:** Reproducible code-based checks; same inputs/rules produce the same outcome.
- **Document slot:** A named requirement into which a vendor uploads an expected document type.
- **External verification:** A response from an authorised registry, bank, screening or other provider; not the same as format validation.
- **Fail closed:** Never approve if a required check is absent, unresolved or errored.
- **Human review:** An authorised person resolves ambiguity or an exception.
- **Rule version:** Version of the validation policy used for a decision.
- **Vendor-safe finding:** An issue and remediation that can be communicated to the vendor without exposing internal controls.

## Appendix B — Core project principle

**Collect accurately. Resolve applicability. Verify deterministically. Escalate uncertainty. Explain every action. Preserve the audit trail.**
