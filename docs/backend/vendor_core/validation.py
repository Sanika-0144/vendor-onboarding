"""Deterministic, explainable vendor application validation.

These checks are internal consistency/format checks only; they do not query
PAN/GST/MCA registries or banks and never constitute official verification.
"""
from __future__ import annotations
import re
from collections import defaultdict
from typing import Any
from .names import compare_names

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
CIN_RE = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def _finding(code: str, field: str, severity: str, status: str, message: str,
             source: str = "application", action: str = "") -> dict[str, Any]:
    return {"code": code, "field": field, "severity": severity,
            "status": status, "message": message, "source": source,
            "action": action}


def _value(regs: list[dict], kind: str) -> str:
    item = next((x for x in regs if str(x.get("type", "")).upper() == kind), {})
    return str(item.get("value") or "").strip().upper()


def validate_submission(sub: dict[str, Any], required_slots: list[dict] | None = None) -> dict[str, Any]:
    profile = sub.get("profile") or {}
    regs = sub.get("tax_registrations") or []
    banks = sub.get("bank_accounts") or []
    docs = sub.get("documents") or []
    findings: list[dict[str, Any]] = []
    legal_name = str(profile.get("legal_name") or "").strip()
    pan, gstin, cin = (_value(regs, k) for k in ("PAN", "GSTIN", "CIN"))

    for kind, value, pattern, label in (
        ("PAN", pan, PAN_RE, "PAN"), ("GSTIN", gstin, GSTIN_RE, "GSTIN"),
        ("CIN", cin, CIN_RE, "CIN"),
    ):
        if value:
            valid = bool(pattern.fullmatch(value))
            findings.append(_finding(f"{kind}_{'FORMAT_OK' if valid else 'FORMAT_INVALID'}", kind,
                "info" if valid else "blocker", "pass" if valid else "mismatch",
                f"{label} format {'is valid' if valid else 'does not match the expected Indian format'}.",
                action="Check the value against the original certificate." if not valid else ""))
        else:
            findings.append(_finding(f"{kind}_NOT_PROVIDED", kind, "info", "not_provided",
                f"{label} has not been provided; no format check was possible."))

    if pan and gstin and GSTIN_RE.fullmatch(gstin):
        consistent = gstin[2:12] == pan
        findings.append(_finding("GSTIN_PAN_CONSISTENCY", "GSTIN/PAN", "info" if consistent else "blocker",
            "pass" if consistent else "mismatch",
            "GSTIN embeds the same PAN supplied in the tax registration." if consistent else
            "The PAN embedded in GSTIN differs from the supplied PAN.",
            action="Check both identifiers against their source certificates." if not consistent else ""))

    # Cross-document field checks use only fields extracted by OCR and are never treated as proof.
    extracted_docs = []
    for doc in docs:
        fields = doc.get("extracted_fields") or {}
        extracted_docs.append((doc, fields))
        for kind, expected in (("pan", pan), ("gstin", gstin), ("cin", cin)):
            candidates = fields.get(kind) or []
            if isinstance(candidates, str): candidates = [candidates]
            if expected and candidates:
                match = expected in [str(x).strip().upper() for x in candidates]
                findings.append(_finding(f"DOC_{kind.upper()}_{'MATCH' if match else 'MISMATCH'}",
                    kind.upper(), "info" if match else "blocker", "pass" if match else "mismatch",
                    f"OCR candidate in {doc.get('filename') or doc.get('slot_id')} {'matches' if match else 'differs from'} the saved {kind.upper()}.",
                    source=str(doc.get("slot_id") or "document"),
                    action="Review the original document and correct the saved value or upload the correct file." if not match else ""))
        candidate_name = fields.get("legal_name")
        if legal_name and candidate_name:
            comparison = compare_names(legal_name, str(candidate_name))
            if comparison.tier in ("EXACT", "COSMETIC"):
                status, severity = "pass", "info"
            elif comparison.tier in ("FORM_MISSING", "ABBREVIATED", "AMBIGUOUS"):
                status, severity = "needs_review", "review"
            else:
                status, severity = "mismatch", "blocker"
            findings.append(_finding("DOC_LEGAL_NAME_" + status.upper(), "legal_name", severity, status,
                f"Company name from {doc.get('filename') or doc.get('slot_id')}: {comparison.note} (similarity {comparison.score:.0f}%).",
                source=str(doc.get("slot_id") or "document"),
                action="Reviewer should compare the original document; correct the company name if needed." if status != "pass" else ""))

    if legal_name:
        findings.append(_finding("LEGAL_NAME_PRESENT", "legal_name", "info", "pass", "Legal business name is present."))
    else:
        findings.append(_finding("LEGAL_NAME_MISSING", "legal_name", "blocker", "missing", "Legal business name is missing.", action="Complete the Company Profile."))

    for bank in banks:
        bank_id = str(bank.get("id") or "bank")
        holder = str(bank.get("holder_name") or bank.get("account_holder_name") or bank.get("account_holder") or "").strip()
        ifsc = str(bank.get("identifier") or bank.get("ifsc") or "").strip().upper()
        if ifsc:
            valid = bool(IFSC_RE.fullmatch(ifsc))
            findings.append(_finding("IFSC_FORMAT_" + ("OK" if valid else "INVALID"), f"bank:{bank_id}:ifsc",
                "info" if valid else "blocker", "pass" if valid else "mismatch",
                f"IFSC format {'is valid' if valid else 'is invalid'} for bank account {bank_id}.",
                action="Check the IFSC on bank-issued evidence." if not valid else ""))
        else:
            findings.append(_finding("IFSC_MISSING", f"bank:{bank_id}:ifsc", "blocker", "missing",
                f"IFSC is missing for bank account {bank_id}.", action="Provide the bank IFSC."))
        if holder and legal_name:
            match = compare_names(legal_name, holder)
            if match.tier in ("EXACT", "COSMETIC"):
                status, severity = "pass", "info"
                message = "Bank account holder name matches the legal business name."
            elif bank.get("ownership_evidence_ref"):
                status, severity = "needs_review", "review"
                message = "Bank account holder differs from the legal business name; authorisation evidence is linked and requires reviewer assessment."
            else:
                status, severity = "mismatch", "blocker"
                message = "Bank account holder differs from the legal business name and no authorisation evidence is linked."
            findings.append(_finding("BANK_HOLDER_" + status.upper(), f"bank:{bank_id}:holder", severity, status,
                message, action="Confirm the account relationship and provide appropriate authorisation evidence." if status != "pass" else ""))
        else:
            findings.append(_finding("BANK_HOLDER_UNAVAILABLE", f"bank:{bank_id}:holder", "review", "needs_review",
                "Bank account holder name is unavailable for a name comparison."))

        for doc, fields in extracted_docs:
            extracted_holder = fields.get("account_holder_name")
            if extracted_holder and holder:
                comparison = compare_names(holder, str(extracted_holder))
                status = "pass" if comparison.tier in ("EXACT", "COSMETIC") else "needs_review"
                findings.append(_finding("BANK_DOC_HOLDER_" + status.upper(), f"bank:{bank_id}:holder", "info" if status == "pass" else "review", status,
                    f"OCR account-holder candidate {comparison.note}.", source=str(doc.get("slot_id") or "document"),
                    action="Compare the original bank evidence with the entered holder name." if status != "pass" else ""))

    # Duplicate file hashes across different slots are a strong internal duplicate signal.
    by_hash: dict[str, list[str]] = defaultdict(list)
    for doc in docs:
        digest = str(doc.get("sha256") or "").strip().lower()
        if digest: by_hash[digest].append(str(doc.get("slot_id") or "unknown"))
    for slots in by_hash.values():
        if len(slots) > 1:
            findings.append(_finding("DUPLICATE_DOCUMENT", "documents", "review", "needs_review",
                "The same file content has been uploaded to multiple document slots: " + ", ".join(slots) + ".",
                source="documents", action="Confirm that each slot contains the correct document."))

    present = {str(d.get("slot_id")) for d in docs}
    for slot in required_slots or []:
        slot_id = str(slot.get("slot_id") or "")
        if slot_id and slot_id not in present:
            findings.append(_finding("REQUIRED_DOCUMENT_MISSING", slot_id, "blocker", "missing",
                f"Required document is missing: {slot.get('label') or slot_id}.", source="document_check",
                action="Upload the required document."))

    blockers = sum(x["severity"] == "blocker" for x in findings)
    reviews = sum(x["severity"] == "review" for x in findings)
    missing = sum(x["status"] == "missing" for x in findings)
    if blockers: overall = "BLOCKED"
    elif reviews: overall = "NEEDS_REVIEW"
    elif missing: overall = "INCOMPLETE"
    else: overall = "READY_FOR_REVIEW"
    return {"overall_status": overall, "summary": {"total": len(findings), "blockers": blockers,
            "review_items": reviews, "missing": missing, "passed": sum(x["status"] == "pass" for x in findings)},
            "findings": findings,
            "limitations": ["These are deterministic format and cross-document consistency checks only.",
                "No live PAN, GSTIN, MCA/CIN, sanctions, or bank-account verification service is connected.",
                "OCR-extracted values are candidates and must be checked against the original document."]}
