"""Deterministic rule handlers. Each handler: (EvalContext, rule_dict) -> HandlerOutput.

Handlers never see raw model output as truth: extraction values are re-validated here.
Messages/evidence use masked values only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import validators as V
from .adapters import SanctionsAdapter
from .applicability import Config, Slot, VendorContext, indirect_status, INDIRECT_RULES
from .models import CheckStatus, Finding, Severity
from .names import compare_names
from .security import mask


@dataclass
class EvalContext:
    sub: dict[str, Any]
    vctx: VendorContext
    cfg: Config
    slots: list[Slot]
    existing_vendors: list[dict[str, Any]]
    sanctions: SanctionsAdapter | None
    today: date
    applicability: dict[str, str] = field(default_factory=dict)

    @property
    def profile(self) -> dict[str, Any]:
        return self.sub.get("profile", {})

    @property
    def policy(self) -> dict[str, Any]:
        return self.cfg.policy

    def doc(self, slot_id: str) -> dict[str, Any] | None:
        for d in self.sub.get("documents", []):
            if d.get("slot_id") == slot_id:
                return d
        return None

    def reg(self, reg_type: str) -> dict[str, Any] | None:
        for r in self.sub.get("tax_registrations", []):
            if (r.get("type") or "").upper() == reg_type:
                return r
        return None

    def threshold(self, field_name: str) -> float:
        ex = self.cfg.country_rules["extraction"]
        return ex["field_thresholds"].get(field_name, ex["default_threshold"])


@dataclass
class HandlerOutput:
    findings: list[Finding] = field(default_factory=list)
    status: CheckStatus | None = None     # override (e.g. NOT_RUN)
    note: str = ""
    evidence: list[str] = field(default_factory=list)


def F(rule: dict, code: str, sev: Severity, msg: str, *, subject="-", fields=(), vv=True, fix="", esc=None, ev=()):
    return Finding(rule["rule_id"], code, sev, msg, subject, list(fields), vv, fix,
                   esc if esc is not None else sev == Severity.ESCALATE, list(ev))


def _label(c: "EvalContext", slot_id: str) -> str:
    for s in c.slots:
        if s.slot_id == slot_id:
            return s.label
    return slot_id


def _val(doc: dict | None, name: str):
    if not doc:
        return None, 0.0
    f = (doc.get("extraction") or {}).get("fields", {}).get(name)
    if not f:
        return None, 0.0
    return f.get("value"), float(f.get("confidence") or 0.0)


def _parse(d: str | None) -> date | None:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date() if d else None
    except ValueError:
        return None


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"}


# ============================================================ INTAKE
def profile_fields(c: EvalContext, rule) -> HandlerOutput:
    p, out = c.profile, []
    need = {"country": "country of registration", "legal_name": "legal business name", "entity_type": "legal entity type",
            "contact_name": "primary contact name", "contact_email": "business email"}
    for k, label in need.items():
        if not p.get(k):
            out.append(F(rule, f"MISSING_{k.upper()}", Severity.FIXABLE, f"Missing: {label}.", fields=[f"profile.{k}"],
                         fix=f"Please provide the {label}."))
    addr = p.get("registered_address") or {}
    if not (addr.get("line1") and addr.get("city") and addr.get("country")):
        out.append(F(rule, "MISSING_ADDRESS", Severity.FIXABLE, "Registered address is incomplete.",
                     fields=["profile.registered_address"], fix="Please provide the full registered address (street, city, country)."))
    if not p.get("operating_countries"):
        out.append(F(rule, "MISSING_OPERATING", Severity.FIXABLE, "Operating countries not provided.",
                     fields=["profile.operating_countries"], fix="Please list the countries you operate in."))
    cats = [x.lower() for x in p.get("categories", [])]
    if not cats:
        out.append(F(rule, "MISSING_CATEGORY", Severity.FIXABLE, "Vendor category not selected.", fields=["profile.categories"],
                     fix="Please select Goods, Services, or both."))
    if "goods" in cats and not p.get("products_supplied"):
        out.append(F(rule, "MISSING_PRODUCTS", Severity.FIXABLE, "Products supplied not described.", fields=["profile.products_supplied"],
                     fix="Please describe the goods you supply."))
    if "services" in cats and not p.get("services_provided"):
        out.append(F(rule, "MISSING_SERVICES", Severity.FIXABLE, "Services provided not described.", fields=["profile.services_provided"],
                     fix="Please describe the services you provide."))
    if p.get("entity_type") != "sole_proprietor" and not (p.get("authorised_rep") or {}).get("name"):
        out.append(F(rule, "MISSING_AUTH_REP", Severity.FIXABLE, "Authorised representative missing.", fields=["profile.authorised_rep"],
                     fix="Please provide the authorised representative's name and designation."))
    em = p.get("contact_email") or ""
    if em and not EMAIL_RE.match(em):
        out.append(F(rule, "BAD_EMAIL", Severity.FIXABLE, "Business email format looks invalid.", fields=["profile.contact_email"],
                     fix="Please provide a valid business email address."))
    elif em and em.split("@")[-1].lower() in FREE_MAIL and p.get("entity_type") != "sole_proprietor":
        out.append(F(rule, "FREE_MAIL", Severity.WARN, "Business email uses a free mail domain.", fields=["profile.contact_email"], vv=False))
    return HandlerOutput(out)


def entity_configured(c: EvalContext, rule) -> HandlerOutput:
    country = c.vctx.registration_country
    allowed = c.cfg.country_rules["countries"].get(country, {}).get("entity_types", [])
    et = c.vctx.entity_type
    if country not in c.cfg.country_rules["countries"]:
        return HandlerOutput([F(rule, "COUNTRY_UNSUPPORTED", Severity.ESCALATE,
                                "Registration country is not configured; manual review needed.", fields=["profile.country"])])
    if et == "other" or et not in allowed:
        return HandlerOutput([F(rule, "ENTITY_UNCONFIGURED", Severity.ESCALATE,
                                "Your legal structure needs manual review by our team.", fields=["profile.entity_type"])])
    return HandlerOutput()


def declaration(c: EvalContext, rule) -> HandlerOutput:
    d = c.sub.get("declaration") or {}
    if not d.get("accepted"):
        return HandlerOutput([F(rule, "NOT_ACCEPTED", Severity.FIXABLE, "Declaration not accepted.", fields=["declaration"],
                                fix="Please confirm the accuracy declaration and your authority to submit.")])
    return HandlerOutput()


# ============================================================ DOCUMENTS
def slots_complete(c: EvalContext, rule) -> HandlerOutput:
    out = []
    for s in c.slots:
        if s.requirement == "REQUIRED" and not c.doc(s.slot_id):
            out.append(F(rule, "MISSING_DOC", Severity.FIXABLE, f"Required document missing: {s.label}.", subject=s.slot_id,
                         fields=[f"documents.{s.slot_id}"], fix=f"Please upload: {s.label}."))
    return HandlerOutput(out)


def file_quality(c: EvalContext, rule) -> HandlerOutput:
    out, pol = [], c.policy
    max_bytes = pol["max_file_size_mb"] * 1024 * 1024
    for d in c.sub.get("documents", []):
        sid = d.get("slot_id", "?")
        ext = (d.get("filename", "").rsplit(".", 1)[-1] or "").lower()
        if ext not in pol["allowed_extensions"]:
            out.append(F(rule, "BAD_EXTENSION", Severity.FIXABLE, f"File type '.{ext}' not accepted for {sid}.", subject=sid,
                         fix=f"For '{_label(c, sid)}': please upload a PDF, JPG, JPEG or PNG file."))
        if d.get("size_bytes", 0) > max_bytes:
            out.append(F(rule, "TOO_LARGE", Severity.FIXABLE, f"File for {sid} exceeds {pol['max_file_size_mb']} MB.", subject=sid,
                         fix=f"For '{_label(c, sid)}': please upload a file under {pol['max_file_size_mb']} MB."))
        if d.get("signature_ok") is False:
            out.append(F(rule, "BAD_SIGNATURE", Severity.FIXABLE, f"File for {sid} could not be read (invalid file content).", subject=sid,
                         fix=f"The file for '{_label(c, sid)}' appears corrupted or is not the type its name suggests. Please re-upload."))
        scan = (d.get("malware_scan") or {}).get("status", "NOT_SCANNED")
        if scan == "INFECTED":
            out.append(F(rule, "MALWARE", Severity.ESCALATE, f"Malware scanner flagged file for {sid}.", subject=sid, vv=False))
        elif pol.get("malware_scan_required") and scan != "CLEAN":
            return HandlerOutput(out, CheckStatus.NOT_RUN, "malware scan required by policy but unavailable")
    return HandlerOutput(out)


def doc_type_match(c: EvalContext, rule) -> HandlerOutput:
    out = []
    by_slot = {s.slot_id: s for s in c.slots}
    for d in c.sub.get("documents", []):
        s = by_slot.get(d.get("slot_id"))
        det = d.get("detected_type")
        if s and det and det != s.doc_type:
            out.append(F(rule, "WRONG_DOC_TYPE", Severity.FIXABLE,
                         f"The file uploaded for '{s.label}' looks like a different document type.", subject=s.slot_id,
                         fix=f"Please upload the correct document for: {s.label}."))
    return HandlerOutput(out)


def doc_validity(c: EvalContext, rule) -> HandlerOutput:
    out, warn_days = [], c.policy["document_expiry_warning_days"]
    by_slot = {s.slot_id: s for s in c.slots}
    for d in c.sub.get("documents", []):
        sid, dt = d.get("slot_id", "?"), d.get("doc_type") or by_slot.get(d.get("slot_id"), Slot("", "", "", "", "")).doc_type
        issue, exp = _parse(d.get("issue_date")), _parse(d.get("expiry_date"))
        if issue and issue > c.today:
            out.append(F(rule, "FUTURE_ISSUE_DATE", Severity.ESCALATE, f"Issue date for {sid} is in the future.", subject=sid, vv=False))
        if exp and exp < c.today:
            out.append(F(rule, "EXPIRED", Severity.FIXABLE, f"Document for {sid} has expired.", subject=sid,
                         fix=f"Please upload a current, unexpired version of '{_label(c, sid)}'."))
        elif exp and exp <= c.today + timedelta(days=warn_days):
            out.append(F(rule, "EXPIRING_SOON", Severity.WARN, f"Document for {sid} expires on {exp.isoformat()}.", subject=sid,
                         fix=f"'{_label(c, sid)}' expires soon; please plan to upload a renewed copy."))
        spec = c.cfg.country_rules["doc_types"].get(by_slot.get(sid, Slot("", "", "", "", "")).doc_type, {})
        max_age = spec.get("max_age_days")
        if max_age and issue and (c.today - issue).days > max_age:
            out.append(F(rule, "STALE_DOCUMENT", Severity.FIXABLE, f"Document for {sid} is older than {max_age} days.", subject=sid,
                         fix=f"Please upload a version of '{_label(c, sid)}' issued within the last {max_age} days."))
    return HandlerOutput(out)


def extraction_confidence(c: EvalContext, rule) -> HandlerOutput:
    """Low confidence / missing critical field: ask for a clearer re-upload first, then human review."""
    out, max_att = [], c.policy["max_reupload_attempts"]
    by_slot = {s.slot_id: s for s in c.slots}
    for d in c.sub.get("documents", []):
        sid, slot = d.get("slot_id", "?"), by_slot.get(d.get("slot_id"))
        if not slot:
            continue
        ex = d.get("extraction") or {}
        if ex.get("status") == "FAILED":
            weak = ["(extraction failed)"]
        else:
            weak = []
            for fld in c.cfg.country_rules["doc_types"].get(slot.doc_type, {}).get("critical_fields", []):
                val, conf = _val(d, fld)
                if val in (None, "") or conf < c.threshold(fld):
                    weak.append(fld)
        if not weak:
            continue
        attempts = int(d.get("upload_attempts", 1))
        if attempts < max_att:
            out.append(F(rule, "LOW_CONFIDENCE_REUPLOAD", Severity.FIXABLE,
                         f"We could not clearly read '{slot.label}' (unclear: {', '.join(weak)}).", subject=sid,
                         fix=f"Please re-upload a clearer, well-lit, uncropped scan or photo of '{slot.label}'."))
        else:
            out.append(F(rule, "LOW_CONFIDENCE_HUMAN_REVIEW", Severity.ESCALATE,
                         f"'{slot.label}' could not be read reliably after {attempts} attempts; routed to a human reviewer.",
                         subject=sid, fix=f"No action needed now; a reviewer will check '{slot.label}'."))
    return HandlerOutput(out)


# ============================================================ FORMAT (country)
def _reg_findings(c, rule, reg_type, validator, label, required, extra=None):
    r = c.reg(reg_type)
    out = []
    if not r or not r.get("value"):
        if required:
            out.append(F(rule, f"MISSING_{reg_type}", Severity.FIXABLE, f"{label} not provided.", subject=reg_type,
                         fields=["tax_registrations"], fix=f"Please provide your {label}."))
        return out
    if not validator(r["value"]):
        out.append(F(rule, f"INVALID_{reg_type}_FORMAT", Severity.FIXABLE,
                     f"{label} ({mask(r['value'])}) is not in the expected format.", subject=reg_type, fields=["tax_registrations"],
                     fix=f"Please re-check your {label} and enter it exactly as issued.", ev=[f"{reg_type}:{mask(r['value'])}"]))
    elif extra:
        out += extra(r)
    return out


def in_pan(c, rule):
    def holder(r):
        ht = V.pan_holder_type(r["value"])
        allowed = c.cfg.country_rules["pan_holder_by_entity"].get(c.vctx.entity_type)
        if allowed and ht not in allowed:
            return [F(rule, "PAN_HOLDER_MISMATCH", Severity.ESCALATE,
                      "The PAN holder category does not match the selected legal entity type; our team will confirm.",
                      subject="PAN", fields=["tax_registrations", "profile.entity_type"],
                      fix="Please confirm the legal entity type and PAN are correct.")]
        return []
    return HandlerOutput(_reg_findings(c, rule, "PAN", V.valid_pan, "PAN", True, holder))


def in_cin(c, rule):
    def listed(r):
        if c.vctx.entity_type == "private_limited" and V.clean(r["value"]).startswith("L"):
            return [F(rule, "CIN_LISTED_PREFIX", Severity.WARN, "CIN indicates a listed company but a private limited entity was selected.",
                      subject="CIN", vv=False)]
        return []
    return HandlerOutput(_reg_findings(c, rule, "CIN", V.valid_cin, "CIN", True, listed))


def in_llpin(c, rule):
    return HandlerOutput(_reg_findings(c, rule, "LLPIN", V.valid_llpin, "LLPIN", True))


def _indirect(c, rule, reg_type, validator, label, extra=None) -> HandlerOutput:
    status, reason = indirect_status(c.sub, reg_type)
    out = []
    if status is None:
        return HandlerOutput([F(rule, f"{reg_type}_STATUS_UNDECLARED", Severity.ESCALATE,
                                f"Please tell us whether you are registered for {label}.", subject=reg_type,
                                fields=["tax_registrations"], fix=f"Select registered / not registered / not applicable for {label}, with a reason if not registered.")])
    if status == "registered":
        r = c.reg(reg_type)
        if not r.get("value"):
            out.append(F(rule, f"MISSING_{reg_type}", Severity.FIXABLE, f"{label} number not provided.", subject=reg_type,
                         fix=f"Please provide your {label} number."))
        elif not validator(r["value"]):
            out.append(F(rule, f"INVALID_{reg_type}_FORMAT", Severity.FIXABLE,
                         f"{label} ({mask(r['value'])}) failed the format/checksum check.", subject=reg_type,
                         fix=f"Please re-check your {label} number.", ev=[f"{reg_type}:{mask(r['value'])}"]))
        elif extra:
            out += extra(r)
    elif status in ("not_registered", "not_applicable"):
        if reason and c.policy.get("accept_declared_indirect_tax_status_with_reason"):
            out.append(F(rule, f"{reg_type}_DECLARED_NOT_REGISTERED", Severity.INFO,
                         f"{label}: declared '{status}' ({reason}). Recorded as a declaration, not a legal determination.", subject=reg_type, vv=False))
        else:
            out.append(F(rule, f"{reg_type}_REASON_NEEDED", Severity.ESCALATE, f"{label} status needs a reason or review.", subject=reg_type,
                         fix="Please explain why you are not registered / it does not apply."))
    else:
        out.append(F(rule, f"{reg_type}_NEEDS_REVIEW", Severity.ESCALATE, f"{label} status '{status}' is routed to review.", subject=reg_type))
    return HandlerOutput(out)


def in_gstin(c, rule):
    def pan_consistency(r):
        pan = c.reg("PAN")
        if pan and pan.get("value") and V.clean(r["value"])[2:12] != V.clean(pan["value"]):
            return [F(rule, "GSTIN_PAN_MISMATCH", Severity.FIXABLE, "The PAN embedded in the GSTIN does not match the PAN provided.",
                      subject="GSTIN", fields=["tax_registrations"], fix="Please check that your GSTIN and PAN belong to the same business.")]
        return []
    return _indirect(c, rule, "GSTIN", V.valid_gstin, "GSTIN", pan_consistency)


def us_w9(c, rule):
    out, d = [], c.doc("w9")
    if not d:
        return HandlerOutput()   # missing slot is reported by GEN-004
    cls, conf = _val(d, "tax_classification")
    us_person = (d.get("extraction") or {}).get("us_person")
    if us_person is False or (cls and "foreign" in str(cls).lower()):
        return HandlerOutput([F(rule, "FOREIGN_PAYEE_TAX_REVIEW", Severity.ESCALATE,
                                "Your tax status needs review by our tax team (W-8 workflow not available online yet).", subject="w9",
                                fix="No action needed now; our tax team will contact you if needed.")])
    if cls and conf >= c.threshold("tax_classification"):
        allowed = c.cfg.country_rules["w9_classification_by_entity"].get(c.vctx.entity_type)
        if allowed and str(cls).lower() not in allowed:
            out.append(F(rule, "W9_CLASS_MISMATCH", Severity.ESCALATE,
                         "The tax classification on the W-9 differs from the selected entity type; our team will confirm.", subject="w9",
                         fix="Please confirm your legal entity type and W-9 classification."))
    return HandlerOutput(out)


def us_ein(c, rule):
    r = c.reg("EIN")
    if r and r.get("value") and not V.valid_ein_syntax(r["value"]):
        return HandlerOutput([F(rule, "INVALID_EIN_FORMAT", Severity.FIXABLE, f"EIN ({mask(r['value'])}) is not 9 digits.", subject="EIN",
                                fix="Please re-check your EIN/TIN (9 digits).")])
    return HandlerOutput()


def us_sales_tax(c, rule):
    return _indirect(c, rule, "SALES_TAX", lambda v: bool(v), "state sales/use tax")


def gb_company_number(c, rule):
    return HandlerOutput(_reg_findings(c, rule, "COMPANY_NUMBER", V.valid_uk_company_number, "Companies House number", True))


def gb_utr(c, rule):
    r = c.reg("UTR")
    if r and r.get("value") and not V.valid_utr(r["value"]):
        return HandlerOutput([F(rule, "INVALID_UTR_FORMAT", Severity.FIXABLE, f"UTR ({mask(r['value'])}) is not 10 digits.", subject="UTR",
                                fix="Please re-check your UTR (10 digits).")])
    return HandlerOutput()


def gb_vat(c, rule):
    return _indirect(c, rule, "VAT", V.valid_gb_vat, "VAT")


# ============================================================ BANKING
def bank_primary(c, rule):
    banks = c.sub.get("bank_accounts", [])
    n = sum(1 for b in banks if b.get("is_primary"))
    if not banks:
        return HandlerOutput([F(rule, "NO_BANK_ACCOUNT", Severity.FIXABLE, "No bank account provided.", fields=["bank_accounts"],
                                fix="Please add at least one bank account.")])
    if n != 1:
        return HandlerOutput([F(rule, "PRIMARY_COUNT", Severity.FIXABLE, f"{n} accounts are marked primary; exactly one is required.",
                                fields=["bank_accounts"], fix="Please mark exactly one account as primary.")])
    return HandlerOutput()


def bank_identifiers(c, rule):
    out = []
    for b in c.sub.get("bank_accounts", []):
        aid, cc, acct = b.get("id", "acct"), (b.get("country") or "").upper(), b.get("account_number", "")
        ident = b.get("identifier", "")
        bad = lambda code, msg, fix: out.append(F(rule, code, Severity.FIXABLE, msg, subject=aid, fields=[f"bank_accounts.{aid}"], fix=fix))
        if cc == "IN":
            if not V.valid_ifsc(ident): bad("BAD_IFSC", f"IFSC ({mask(ident)}) is not in the expected format.", "Please re-check the IFSC code.")
            if not re.fullmatch(r"\d{9,18}", V.clean(acct, " -")): bad("BAD_ACCT_IN", "Account number should be 9-18 digits.", "Please re-check the account number.")
        elif cc == "US":
            if not V.valid_aba(ident): bad("BAD_ABA", f"ABA routing number ({mask(ident)}) failed validation.", "Please re-check the 9-digit ABA routing number.")
            if (b.get("routing_use") or "").upper() not in ("ACH", "WIRE"): bad("MISSING_ROUTING_USE", "Routing use (ACH or wire) not specified.", "Please state whether the routing number is for ACH or wire payments.")
            if not V.valid_us_account(acct): bad("BAD_ACCT_US", "Account number should be 4-17 digits.", "Please re-check the account number.")
        elif cc == "GB":
            if not V.valid_sort_code(ident): bad("BAD_SORT", f"Sort code ({mask(ident)}) is not 6 digits.", "Please re-check the sort code.")
            if not V.valid_uk_account(acct): bad("BAD_ACCT_GB", "UK account number should be 8 digits.", "Please re-check the account number.")
        else:
            iban = b.get("iban")
            if iban and V.valid_iban(iban):
                out.append(F(rule, "OTHER_COUNTRY_IBAN_OK", Severity.INFO, "Bank country not configured; IBAN passed checksum.", subject=aid, vv=False))
            else:
                out.append(F(rule, "BANK_COUNTRY_UNCONFIGURED", Severity.ESCALATE, "Bank country is not configured; manual review needed.", subject=aid))
        if b.get("iban") and cc in ("IN", "US", "GB") and not V.valid_iban(b["iban"]):
            out.append(F(rule, "BAD_IBAN", Severity.FIXABLE, f"IBAN ({mask(b['iban'])}) failed validation.", subject=aid, fix="Please re-check the IBAN."))
    return HandlerOutput(out)


def bank_ownership(c, rule):
    out, legal, trade = [], c.profile.get("legal_name", ""), c.profile.get("trading_name") or ""
    for b in c.sub.get("bank_accounts", []):
        aid = b.get("id", "acct")
        holder = (
            b.get("holder_name")
            or b.get("account_holder_name")
            or b.get("account_holder")
            or ""
        )
        htype = b.get("holder_type", "business")
        rel = b.get("relationship")

        # Backward-compatible mapping for declarations submitted by the
        # VendorFlow frontend. "same_legal_entity" is not treated as proof
        # of a name match; the holder-name comparison below must establish it.
        if not rel:
            frontend_relationship = b.get("account_relationship")
            relationship_map = {
                "same_legal_entity": None,
                "sole_proprietor": "sole_proprietor",
                "director_authorised_individual": "director_authorised_individual",
                "related_party": "related_party",
                "joint": "joint",
                "other": "other",
            }
            rel = relationship_map.get(frontend_relationship)
            if frontend_relationship in {
                "sole_proprietor",
                "director_authorised_individual",
                "joint",
            }:
                htype = "individual"
        m = compare_names(holder, legal, order_insensitive=(c.vctx.entity_type == "sole_proprietor"))
        m2 = compare_names(holder, trade) if trade else None
        best = m if (not m2 or m.tier in ("EXACT", "COSMETIC")) else (m2 if m2.tier in ("EXACT", "COSMETIC") else m)
        if best.tier in ("EXACT", "COSMETIC"):
            if best.tier == "COSMETIC":
                out.append(F(rule, "HOLDER_COSMETIC", Severity.INFO, f"Account holder name matches business name ({best.note}).", subject=aid, vv=False))
            if c.vctx.entity_type == "sole_proprietor" and htype == "individual":
                pol = c.policy.get("sole_prop_personal_account")
                if pol == "accept_with_evidence":
                    out.append(F(rule, "SOLE_PROP_OWN_ACCOUNT", Severity.INFO,
                                 "Sole proprietor's own-name account accepted under buyer policy (bank evidence required and cross-checked).",
                                 subject=aid, vv=False))
                else:
                    out.append(F(rule, "SOLE_PROP_REVIEW", Severity.ESCALATE, "Sole proprietor personal account routed to human review per policy.", subject=aid,
                                 fix="No action needed; a reviewer will confirm."))
            continue
        if best.tier == "ABBREVIATED" or best.tier == "FORM_MISSING":
            out.append(F(rule, "HOLDER_ABBREVIATED", Severity.WARN, f"Account holder name is an abbreviation/variant of the business name ({best.note}).", subject=aid, vv=False))
            continue
        # genuine difference
        has_auth = bool(c.doc(f"bank_auth:{aid}"))
        if not rel:
            out.append(F(rule, "HOLDER_DIFFERS_NO_RELATIONSHIP", Severity.FIXABLE,
                         "The bank account holder name differs from the business name.", subject=aid, fields=[f"bank_accounts.{aid}"],
                         fix="Please explain the relationship between the account holder and your business, and upload supporting evidence (e.g. authorisation letter)."))
        elif rel in ("unrelated", "other"):
            out.append(F(rule, "HOLDER_UNRELATED", Severity.ESCALATE, "Account holder is unrelated/unclear relative to the business; do not approve until relationship established.",
                         subject=aid, vv=False))
            out.append(F(rule, "HOLDER_RELATIONSHIP_UNCLEAR", Severity.FIXABLE, "We could not establish the relationship between the account holder and your business.",
                         subject=aid, fix="Please provide documents showing the relationship, or use an account in the business's name."))
        elif not has_auth:
            out.append(F(rule, "HOLDER_NEEDS_EVIDENCE", Severity.FIXABLE, f"Account holder differs from the business (declared: {rel}); evidence missing.", subject=aid,
                         fix="Please upload an authorisation letter or other evidence of the relationship."))
        else:
            out.append(F(rule, "HOLDER_RELATED_REVIEW", Severity.ESCALATE, f"Account holder differs from the business (declared: {rel}); evidence supplied, human review required.",
                         subject=aid, fix="No action needed now; a reviewer will assess the evidence."))
    return HandlerOutput(out)


def bank_doc_xref(c, rule):
    out = []
    for b in c.sub.get("bank_accounts", []):
        aid = b.get("id", "acct")
        d = c.doc(f"bank_evidence:{aid}")
        if not d:
            continue
        h, hc = _val(d, "account_holder")
        a, ac = _val(d, "account_number")
        if (h is None or hc < c.threshold("account_holder")) or (a is None or ac < c.threshold("account_number")):
            continue  # extraction rule (GEN-008) owns this; this check cannot conclude
        if V.clean(a, " -") != V.clean(b.get("account_number", ""), " -"):
            out.append(F(rule, "BANK_ACCT_MISMATCH", Severity.FIXABLE,
                         f"Account number on the form ({mask(b.get('account_number'))}) differs from the bank document ({mask(a)}).", subject=aid,
                         fields=[f"bank_accounts.{aid}", f"documents.bank_evidence:{aid}"], fix="Please correct the account number or upload the matching bank document."))
        m = compare_names(h, b.get("holder_name", ""), order_insensitive=True)
        if m.tier in ("MISMATCH", "FORM_CONFLICT"):
            out.append(F(rule, "BANK_HOLDER_DOC_MISMATCH", Severity.FIXABLE, "The account holder on the bank document differs from the form.", subject=aid,
                         fix="Please make sure the account holder name on the form matches the bank document."))
        elif m.tier == "AMBIGUOUS":
            out.append(F(rule, "BANK_HOLDER_DOC_AMBIGUOUS", Severity.ESCALATE, "Account holder name on bank document is similar to, but not the same as, the form.", subject=aid))
        ident = b.get("identifier")
        di, dic = _val(d, "ifsc") if b.get("country") == "IN" else (None, 0)
        if di and dic >= 0.8 and V.clean(di) != V.clean(ident):
            out.append(F(rule, "BANK_IFSC_MISMATCH", Severity.FIXABLE, "IFSC on the bank document differs from the form.", subject=aid, fix="Please correct the IFSC."))
    return HandlerOutput(out)


def bank_country_context(c, rule):
    out = []
    for b in c.sub.get("bank_accounts", []):
        cc = (b.get("country") or "").upper()
        if cc and cc != c.vctx.registration_country:
            note = "within" if cc in c.vctx.operating_countries else "outside"
            out.append(F(rule, "CROSS_BORDER_BANK", Severity.INFO, f"Cross-border bank account ({cc}) recorded; {note} declared operating countries. Evaluated, not rejected.",
                         subject=b.get("id", "acct"), vv=False))
    return HandlerOutput(out)


# ============================================================ CROSS-REFERENCE
def xref_legal_name(c, rule):
    out, form_name = [], c.profile.get("legal_name", "")
    sole = c.vctx.entity_type == "sole_proprietor"
    for s in c.slots:
        if not s.name_xref:
            continue
        d = c.doc(s.slot_id)
        if not d:
            continue
        nm, conf = _val(d, "name")
        if nm is None or conf < c.threshold("name"):
            continue
        m = compare_names(nm, form_name, order_insensitive=sole)
        t = m.tier
        if t == "EXACT":
            continue
        if t == "COSMETIC":
            out.append(F(rule, "NAME_COSMETIC", Severity.INFO, f"Name on {s.label} differs only in formatting ({m.note}). Original values preserved.", subject=s.slot_id, vv=False))
        elif t in ("ABBREVIATED", "FORM_MISSING"):
            out.append(F(rule, "NAME_VARIANT", Severity.WARN, f"Name on {s.label} is a variant of the form name ({m.note}).", subject=s.slot_id, vv=False))
        elif t == "AMBIGUOUS":
            out.append(F(rule, "NAME_AMBIGUOUS", Severity.ESCALATE, f"Name on {s.label} is similar but not equivalent to the legal name; our team will confirm.",
                         subject=s.slot_id, fix="Please confirm the legal name matches your registration documents."))
        else:  # MISMATCH / FORM_CONFLICT
            out.append(F(rule, "NAME_MISMATCH", Severity.FIXABLE, f"The name on {s.label} does not match the legal business name on the form ({m.note}).", subject=s.slot_id,
                         fields=["profile.legal_name", f"documents.{s.slot_id}"], fix="Please correct the legal name or upload the document that matches it."))
    return HandlerOutput(out)


def xref_identifiers(c, rule):
    out, idmap = [], c.cfg.country_rules["registration_id_map"]
    for r in c.sub.get("tax_registrations", []):
        t = (r.get("type") or "").upper()
        spec = idmap.get(t)
        if not spec or not r.get("value"):
            continue
        d = c.doc(spec["slot"])
        if not d:
            continue
        dv, conf = _val(d, spec["field"])
        if dv is None or conf < c.threshold(spec["field"]):
            continue
        a, b = V.clean(r["value"], " -"), V.clean(str(dv), " -")
        if spec.get("compare") == "last4":
            a, b = a[-4:], b[-4:]
        if a != b:
            out.append(F(rule, f"{t}_FORM_DOC_MISMATCH", Severity.FIXABLE,
                         f"The {t} on the form ({mask(r['value'])}) does not match the {t} on the uploaded document ({mask(dv)}).", subject=t,
                         fields=["tax_registrations", f"documents.{spec['slot']}"],
                         fix=f"Please check your {t}: correct the form entry, or upload the document that shows the right number.",
                         ev=[f"{t}:form={mask(r['value'])}", f"{t}:doc={mask(dv)}"]))
    return HandlerOutput(out)


def xref_address(c, rule):
    addr = c.profile.get("registered_address") or {}
    form_tokens = set(re.findall(r"[a-z0-9]+", f"{addr.get('city','')} {addr.get('postcode','')}".lower()))
    out = []
    for s in c.slots:
        d = c.doc(s.slot_id)
        av, conf = _val(d, "address")
        if av and form_tokens and conf >= 0.6:
            doc_tokens = set(re.findall(r"[a-z0-9]+", str(av).lower()))
            if not form_tokens & doc_tokens:
                out.append(F(rule, "ADDRESS_MISMATCH", Severity.WARN, f"Address on {s.label} shares no city/postcode with the form address.", subject=s.slot_id, vv=False))
    return HandlerOutput(out)


# ============================================================ RISK (internal-only findings)
def _bank_key(b):
    return f"{(b.get('country') or '').upper()}:{V.clean(b.get('identifier',''))}:{V.clean(b.get('account_number',''), ' -')}"


def dup_bank(c, rule):
    out, legal = [], c.profile.get("legal_name", "")
    for b in c.sub.get("bank_accounts", []):
        key = _bank_key(b)
        for v in c.existing_vendors:
            if key in v.get("bank_keys", []):
                m = compare_names(v["legal_name"], legal)
                same = m.tier in ("EXACT", "COSMETIC")
                code = "BANK_ON_EXISTING_VENDOR_SAME_NAME" if same else "BANK_ON_DIFFERENT_VENDOR"
                out.append(F(rule, code, Severity.ESCALATE,
                             f"Bank account ({mask(b.get('account_number'))}) already linked to existing vendor {v['vendor_id']}"
                             f"{'' if same else ' under a different name'}. Investigate relationship; not proof of fraud.",
                             subject=b.get("id", "acct"), vv=False, esc=True, ev=[f"existing_vendor:{v['vendor_id']}"]))
    return HandlerOutput(out)


def dup_tax(c, rule):
    out, legal = [], c.profile.get("legal_name", "")
    for r in c.sub.get("tax_registrations", []):
        t, val = (r.get("type") or "").upper(), V.clean(r.get("value", ""), " -")
        if not val:
            continue
        for v in c.existing_vendors:
            if V.clean(v.get("tax_ids", {}).get(t, ""), " -") == val:
                same = compare_names(v["legal_name"], legal).tier in ("EXACT", "COSMETIC")
                out.append(F(rule, "TAXID_ON_EXISTING_VENDOR" + ("_SAME_NAME" if same else "_DIFFERENT_NAME"), Severity.ESCALATE,
                             f"{t} ({mask(val)}) already recorded for existing vendor {v['vendor_id']}"
                             f"{'' if same else ' under a different name'}. Investigate; not proof of fraud.",
                             subject=t, vv=False, esc=True, ev=[f"existing_vendor:{v['vendor_id']}"]))
    return HandlerOutput(out)


def sanctions(c, rule):
    if c.sanctions is None:
        return HandlerOutput([], CheckStatus.NOT_RUN, "no sanctions adapter configured")
    p = c.profile
    names = [p.get("legal_name"), p.get("trading_name"), (p.get("authorised_rep") or {}).get("name"), *p.get("directors", [])]
    resp = c.sanctions.screen([n for n in names if n])
    if resp.status != "OK":
        return HandlerOutput([], CheckStatus.NOT_RUN, f"screening provider unavailable ({resp.provider}); failing closed")
    out = [F(rule, "SANCTIONS_POTENTIAL_MATCH", Severity.ESCALATE,
             f"Potential screening match for '{m['screened_name']}' (score {m['score']}, {'synthetic list' if resp.synthetic else resp.provider}). Human review required; not a determination.",
             subject=m["screened_name"], vv=False, esc=True) for m in resp.matches]
    note = "synthetic demo list; no real sanctions provider connected" if resp.synthetic else resp.provider
    return HandlerOutput(out, None, note)


HANDLERS: dict[str, Callable[[EvalContext, dict], HandlerOutput]] = {
    k: v for k, v in globals().items()
    if k in {"profile_fields", "entity_configured", "declaration", "slots_complete", "file_quality", "doc_type_match", "doc_validity",
             "extraction_confidence", "in_pan", "in_cin", "in_llpin", "in_gstin", "us_w9", "us_ein", "us_sales_tax", "gb_company_number",
             "gb_utr", "gb_vat", "bank_primary", "bank_identifiers", "bank_ownership", "bank_doc_xref", "bank_country_context",
             "xref_legal_name", "xref_identifiers", "xref_address", "dup_bank", "dup_tax", "sanctions"}
}
