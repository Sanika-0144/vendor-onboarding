"""Core data models: Finding, CheckResult, Decision and the enums from the product brief (sections 5, 8)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Severity(str, Enum):
    PASS = "PASS"
    INFO = "INFO"
    WARN = "WARN"
    FIXABLE = "FIXABLE"
    ESCALATE = "ESCALATE"
    BLOCKER = "BLOCKER"


class Applicability(str, Enum):
    REQUIRED = "REQUIRED"
    CONDITIONAL = "CONDITIONAL"
    OPTIONAL = "OPTIONAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_RUN = "NOT_RUN"
    ERROR = "ERROR"


class DecisionStatus(str, Enum):
    APPROVED = "APPROVED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


@dataclass
class Finding:
    """One issue or note emitted by a check. Never contains raw sensitive values (use security.mask)."""
    rule_id: str
    code: str
    severity: Severity
    message: str
    subject: str = "-"
    fields: list[str] = field(default_factory=list)
    vendor_visible: bool = True
    remediation: str = ""
    escalate: bool = False
    evidence_refs: list[str] = field(default_factory=list)

    @property
    def finding_id(self) -> str:
        # Stable across runs so resubmission can diff resolved / still_open / new.
        return f"{self.rule_id}|{self.subject}|{self.code}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        d["finding_id"] = self.finding_id
        return d


@dataclass
class CheckResult:
    rule_id: str
    applicability: Applicability
    check_status: CheckStatus
    findings: list[Finding] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    rule_version: str = ""
    stage: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "applicability": self.applicability.value,
            "check_status": self.check_status.value,
            "findings": [f.to_dict() for f in self.findings],
            "evidence_refs": self.evidence_refs,
            "rule_version": self.rule_version,
            "stage": self.stage,
            "note": self.note,
        }


def derive_status(findings: list[Finding]) -> CheckStatus:
    sev = {f.severity for f in findings}
    if Severity.BLOCKER in sev or Severity.FIXABLE in sev:
        return CheckStatus.FAIL
    if Severity.ESCALATE in sev:
        return CheckStatus.REVIEW_REQUIRED
    return CheckStatus.PASS


@dataclass
class Decision:
    status: DecisionStatus
    application_state: str
    reasons: list[dict[str, Any]]
    needs_human_review: bool
    risk_score: int
    rule_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "application_state": self.application_state,
            "reasons": self.reasons,
            "needs_human_review": self.needs_human_review,
            "risk_score": self.risk_score,
            "rule_version": self.rule_version,
        }
