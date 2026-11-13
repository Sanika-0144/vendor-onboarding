"""Vendor-safe messaging. Built ONLY from vendor-visible findings. Internal-only findings never reach the vendor.

An LLM may polish wording, but validate_polished() enforces that it cannot add/drop actions; otherwise fall back to the template.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import DecisionStatus, Finding, Severity


@dataclass
class VendorMessage:
    subject: str
    body: str
    items: list[dict[str, str]] = field(default_factory=list)   # [{ref, finding_id, text, kind}]
    internal_hidden_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"subject": self.subject, "body": self.body, "items": self.items}


def build_vendor_message(app_ref: str, status: DecisionStatus, findings: list[Finding]) -> VendorMessage:
    hidden = sum(1 for f in findings if not f.vendor_visible and f.severity in (Severity.FIXABLE, Severity.ESCALATE, Severity.BLOCKER))
    if status == DecisionStatus.APPROVED:
        return VendorMessage(f"[{app_ref}] Your vendor application is approved",
                             "Thank you. Your application has been approved. No further action is needed.", [], hidden)
    if status == DecisionStatus.REJECTED:
        # Deliberately generic: do not disclose which internal control triggered the outcome.
        return VendorMessage(f"[{app_ref}] Update on your vendor application",
                             "We are unable to proceed with your application at this time. Please contact your procurement contact for next steps.",
                             [], hidden)
    actions = [f for f in findings if f.vendor_visible and f.severity == Severity.FIXABLE]
    reviews = [f for f in findings if f.vendor_visible and f.severity == Severity.ESCALATE]
    items, lines = [], []
    for i, f in enumerate(actions, 1):
        ref = f"A{i}"
        text = f.remediation or f.message
        items.append({"ref": ref, "finding_id": f.finding_id, "text": text, "kind": "action"})
        lines.append(f"  {i}. {text}  (Ref {ref})")
    for j, f in enumerate(reviews, 1):
        ref = f"R{j}"
        text = f.remediation or "An item is being reviewed by our team."
        items.append({"ref": ref, "finding_id": f.finding_id, "text": text, "kind": "review"})
        lines.append(f"  - {text}  (Ref {ref})")
    if actions:
        body = "Thank you for your application. To continue, please address the following:\n\n" + "\n".join(lines)
    else:
        body = "Thank you for your application. It is currently under review by our team. We will contact you if we need anything further."
        if lines:
            body += "\n\n" + "\n".join(lines)
    return VendorMessage(f"[{app_ref}] Action needed on your vendor application" if actions else f"[{app_ref}] Your vendor application is under review",
                         body, items, hidden)


def validate_polished(polished: str, msg: VendorMessage, findings: list[Finding]) -> tuple[bool, str]:
    """Reject LLM-polished text that drops actions or leaks internal findings."""
    for it in msg.items:
        if f"Ref {it['ref']}" not in polished:
            return False, f"missing item {it['ref']}"
    low = polished.lower()
    for f in findings:
        if not f.vendor_visible and f.finding_id.lower() in low:
            return False, "leaks internal finding id"
    for word in ("sanction", "fraud", "duplicate", "screening", "risk"):
        if word in low:
            return False, f"contains internal-control term '{word}'"
    return True, "ok"


def internal_note(findings: list[Finding]) -> list[dict[str, Any]]:
    """Reviewer-only view (masked values already). Requires role check at the API layer."""
    return [f.to_dict() for f in findings if f.severity in (Severity.ESCALATE, Severity.BLOCKER) or not f.vendor_visible]


def vendor_safe_findings(findings: list[Finding]) -> list[dict[str, Any]]:
    return [{"finding_id": f.finding_id, "severity": f.severity.value, "message": f.message, "action": f.remediation}
            for f in findings if f.vendor_visible and f.severity in (Severity.FIXABLE, Severity.ESCALATE)]


MILESTONES = ["Submitted", "Processing", "Action required / Under review", "Decision"]


def vendor_tracking(application_state: str, status: DecisionStatus | None) -> list[dict[str, str]]:
    reached = {"DRAFT": 0, "SUBMITTED": 1, "PROCESSING": 2, "ACTION_REQUIRED": 3, "UNDER_REVIEW": 3, "COMPLETED": 4}.get(application_state, 0)
    out = []
    for i, m in enumerate(MILESTONES, 1):
        state = "done" if i < reached or (i == reached and application_state == "COMPLETED") else ("current" if i == reached else "upcoming")
        out.append({"milestone": m, "state": state})
    if status:
        out[-1]["label"] = {"APPROVED": "Approved", "PENDING": "Pending", "REJECTED": "Closed"}[status.value]
    return out
