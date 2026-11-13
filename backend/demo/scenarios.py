"""FICTIONAL demo submissions. All names, IDs and documents are synthetic; extraction output is simulated (no live OCR/LLM)."""
from __future__ import annotations

import copy
from typing import Any

from vendor_core.validators import make_gstin

PAN_ABC = "AABCA1234C"   # 4th char C = company
PAN_RV = "BXKPV4821Q"    # 4th char P = individual


def _doc(slot, doc_type, fields: dict[str, Any], *, issue=None, expiry=None, conf=0.97, filename=None, attempts=1):
    return {"slot_id": slot, "doc_type": doc_type, "detected_type": doc_type,
            "filename": filename or f"{slot}.pdf", "size_bytes": 220_000, "signature_ok": True,
            "malware_scan": {"status": "CLEAN", "synthetic": True},
            "extraction": {"status": "OK", "synthetic": True,
                           "fields": {k: {"value": v, "confidence": conf} for k, v in fields.items()}},
            "issue_date": issue, "expiry_date": expiry, "upload_attempts": attempts}


def in_private_limited() -> dict[str, Any]:
    """HAPPY PATH (India): fully consistent private limited company."""
    gstin = make_gstin(PAN_ABC)
    return {
        "profile": {
            "country": "IN", "legal_name": "ABC Manufacturing Private Limited", "trading_name": "ABC Mfg",
            "entity_type": "private_limited", "categories": ["goods"], "products_supplied": "Industrial fasteners",
            "registered_address": {"line1": "12 MIDC Road", "city": "Pune", "postcode": "411019", "country": "IN"},
            "operating_countries": ["IN"], "contact_name": "Anita Rao", "contact_email": "anita@abcmfg.example",
            "authorised_rep": {"name": "Vikram Shah", "designation": "Director"}, "directors": ["Vikram Shah"]},
        "tax_registrations": [
            {"type": "PAN", "jurisdiction": "IN", "value": PAN_ABC},
            {"type": "CIN", "jurisdiction": "IN", "value": "U29100PN2012PTC145678"},
            {"type": "GSTIN", "jurisdiction": "IN", "value": gstin, "status": "registered"}],
        "bank_accounts": [{"id": "acct1", "country": "IN", "bank_name": "Example Bank", "holder_name": "ABC Manufacturing Private Limited",
                           "holder_type": "business", "currency": "INR", "account_number": "50200098765432", "identifier": "HDFC0004321",
                           "is_primary": True}],
        "documents": [
            _doc("pan_card", "PAN_CARD", {"name": "ABC Manufacturing Private Limited", "pan": PAN_ABC}),
            _doc("incorporation_cert", "CERT_OF_INCORPORATION", {"name": "ABC Manufacturing Private Limited", "registration_number": "U29100PN2012PTC145678"}),
            _doc("gst_cert", "GST_CERTIFICATE", {"name": "ABC Manufacturing Private Limited", "gstin": gstin}),
            _doc("bank_evidence:acct1", "BANK_EVIDENCE", {"account_holder": "ABC Manufacturing Private Limited", "account_number": "50200098765432"}, issue="2026-10-01")],
        "declaration": {"accepted": True, "version": "v1"}}


def _rename(s: dict[str, Any], name: str) -> dict[str, Any]:
    """Rename the vendor consistently across form, bank holder and all extracted documents."""
    s["profile"]["legal_name"] = name
    s["profile"]["trading_name"] = None
    s["bank_accounts"][0]["holder_name"] = name
    for d in s["documents"]:
        f = d["extraction"]["fields"]
        if "name" in f: f["name"]["value"] = name
        if "account_holder" in f: f["account_holder"]["value"] = name
    return s


def edge1_cosmetic_name() -> dict[str, Any]:
    """EDGE 1: 'Pvt. Ltd.' on the form vs 'Private Limited' on documents -> APPROVED with INFO notes."""
    s = in_private_limited()
    s["profile"]["legal_name"] = "ABC Manufacturing Pvt. Ltd."
    s["bank_accounts"][0]["holder_name"] = "ABC Manufacturing Pvt. Ltd."
    return s


def sole_prop_base(holder: str = "Rahul Verma") -> dict[str, Any]:
    return {
        "profile": {
            "country": "IN", "legal_name": "Rahul Verma", "trading_name": "Verma Design Studio", "entity_type": "sole_proprietor",
            "categories": ["services"], "services_provided": "Graphic design",
            "registered_address": {"line1": "4 Rajpur Road", "city": "Dehradun", "postcode": "248001", "country": "IN"},
            "operating_countries": ["IN"], "contact_name": "Rahul Verma", "contact_email": "rahul@vermadesign.example"},
        "tax_registrations": [
            {"type": "PAN", "jurisdiction": "IN", "value": PAN_RV},
            {"type": "GSTIN", "jurisdiction": "IN", "status": "not_registered", "status_reason": "Turnover below threshold per proprietor; to be reviewed annually"}],
        "bank_accounts": [{"id": "acct1", "country": "IN", "bank_name": "Example Bank", "holder_name": holder, "holder_type": "individual",
                           "currency": "INR", "account_number": "30011122233344", "identifier": "SBIN0001234", "is_primary": True}],
        "documents": [
            _doc("pan_card", "PAN_CARD", {"name": "Rahul Verma", "pan": PAN_RV}),
            _doc("bank_evidence:acct1", "BANK_EVIDENCE", {"account_holder": holder, "account_number": "30011122233344"}, issue="2026-10-15")],
        "declaration": {"accepted": True, "version": "v1"}}


def edge2a_sole_prop_own_account() -> dict[str, Any]:
    """EDGE 2a: sole proprietor, bank account in own name -> NOT auto-rejected; accepted with note under policy."""
    return sole_prop_base("Rahul Verma")


def edge2b_sole_prop_third_party() -> dict[str, Any]:
    """EDGE 2b: sole proprietor, account in an unrelated person's name -> PENDING + human review."""
    s = sole_prop_base("Meera Kapoor")
    s["bank_accounts"][0]["relationship"] = "other"
    return s


def edge3_pan_mismatch() -> dict[str, Any]:
    """EDGE 3: PAN on form differs from PAN on uploaded card -> FIXABLE -> PENDING (vendor-visible)."""
    s = in_private_limited()
    s["tax_registrations"][0]["value"] = "AABCA1234D"   # typo on the form; PAN card + GSTIN still show ...234C
    return s


def edge3_resubmission_fixed(prev: dict[str, Any]) -> dict[str, Any]:
    """Vendor corrects the PAN on the form."""
    s = copy.deepcopy(prev)
    s["tax_registrations"][0]["value"] = PAN_ABC
    return s


def edge4_duplicate_bank() -> dict[str, Any]:
    """EDGE 4: new vendor submits a bank account already on existing vendor V-1001 -> internal ESCALATE, PENDING, vendor not told why."""
    s = _rename(in_private_limited(), "Zenith Components Private Limited")
    s["bank_accounts"][0].update({"account_number": "50100123456789", "identifier": "HDFC0001234"})
    for d in s["documents"]:
        if d["slot_id"] == "bank_evidence:acct1":
            d["extraction"]["fields"]["account_number"]["value"] = "50100123456789"
    return s


def edge4b_sanctions_hit() -> dict[str, Any]:
    """EDGE 4b: potential synthetic-list screening match -> ESCALATE; reviewer-confirmed -> BLOCKER -> REJECTED."""
    return _rename(in_private_limited(), "Blackwater Trading Co")


def low_confidence(attempts: int = 1) -> dict[str, Any]:
    """Low-confidence PAN extraction: attempts<2 -> ask re-upload (FIXABLE); attempts>=2 -> human review (ESCALATE)."""
    s = in_private_limited()
    for d in s["documents"]:
        if d["slot_id"] == "pan_card":
            d["extraction"]["fields"]["pan"]["confidence"] = 0.55
            d["upload_attempts"] = attempts
    return s


def us_llc() -> dict[str, Any]:
    """HAPPY PATH (US): LLC with W-9."""
    return {
        "profile": {"country": "US", "legal_name": "Lakeside Logistics LLC", "entity_type": "llc", "categories": ["services"],
                    "services_provided": "Freight brokerage",
                    "registered_address": {"line1": "500 Lake St", "city": "Austin", "postcode": "73301", "country": "US"},
                    "operating_countries": ["US"], "contact_name": "Dana Lee", "contact_email": "dana@lakeside.example",
                    "authorised_rep": {"name": "Dana Lee", "designation": "Manager"}},
        "tax_registrations": [{"type": "EIN", "jurisdiction": "US", "value": "98-7654321"},
                              {"type": "SALES_TAX", "jurisdiction": "US-TX", "status": "not_applicable", "status_reason": "Freight services not taxable for this vendor per its tax advisor"}],
        "bank_accounts": [{"id": "acct1", "country": "US", "bank_name": "Example Bank NA", "holder_name": "Lakeside Logistics LLC", "holder_type": "business",
                           "currency": "USD", "account_number": "000987654321", "identifier": "021000021", "routing_use": "ACH", "is_primary": True}],
        "documents": [
            _doc("w9", "W9", {"name": "Lakeside Logistics LLC", "tax_classification": "LLC", "tin_last4": "4321"}),
            _doc("formation_doc", "STATE_FORMATION_DOC", {"name": "Lakeside Logistics LLC"}),
            _doc("bank_evidence:acct1", "BANK_EVIDENCE", {"account_holder": "Lakeside Logistics LLC", "account_number": "000987654321"}, issue="2026-10-20")],
        "declaration": {"accepted": True, "version": "v1"}}


def gb_ltd() -> dict[str, Any]:
    """HAPPY PATH (UK): private limited company."""
    return {
        "profile": {"country": "GB", "legal_name": "Thames Print Ltd", "entity_type": "private_limited", "categories": ["goods"],
                    "products_supplied": "Printed packaging",
                    "registered_address": {"line1": "9 Canal Way", "city": "London", "postcode": "N1 9XX", "country": "GB"},
                    "operating_countries": ["GB"], "contact_name": "Sam Okoye", "contact_email": "sam@thamesprint.example",
                    "authorised_rep": {"name": "Sam Okoye", "designation": "Director"}},
        "tax_registrations": [{"type": "COMPANY_NUMBER", "jurisdiction": "GB", "value": "01234567"},
                              {"type": "VAT", "jurisdiction": "GB", "status": "not_registered", "status_reason": "Below VAT threshold; will review quarterly"}],
        "bank_accounts": [{"id": "acct1", "country": "GB", "bank_name": "Example Bank plc", "holder_name": "Thames Print Ltd", "holder_type": "business",
                           "currency": "GBP", "account_number": "12345678", "identifier": "20-00-00", "is_primary": True}],
        "documents": [
            _doc("companies_house_cert", "CERT_OF_INCORPORATION", {"name": "Thames Print Ltd", "registration_number": "01234567"}),
            _doc("bank_evidence:acct1", "BANK_EVIDENCE", {"account_holder": "Thames Print Ltd", "account_number": "12345678"}, issue="2026-10-10")],
        "declaration": {"accepted": True, "version": "v1"}}


SCENARIOS = {
    "happy_in": ("Happy path: India private limited", in_private_limited),
    "happy_us": ("Happy path: US LLC", us_llc),
    "happy_gb": ("Happy path: UK Ltd", gb_ltd),
    "edge1_cosmetic_name": ("Edge 1: cosmetic name variation", edge1_cosmetic_name),
    "edge2a_sole_prop_own": ("Edge 2a: sole proprietor, own-name account", edge2a_sole_prop_own_account),
    "edge2b_sole_prop_third_party": ("Edge 2b: sole proprietor, third-party account", edge2b_sole_prop_third_party),
    "edge3_pan_mismatch": ("Edge 3: PAN mismatch (then resubmit)", edge3_pan_mismatch),
    "edge4_duplicate_bank": ("Edge 4: duplicate bank account", edge4_duplicate_bank),
    "edge4b_sanctions": ("Edge 4b: potential screening match", edge4b_sanctions_hit),
    "low_confidence": ("Low-confidence extraction", low_confidence),
}
