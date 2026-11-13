"""Deterministic decision roll-up (brief section 8.5). The LLM never touches this."""
from __future__ import annotations

from .applicability import RuleApplicability
from .models import Applicability, CheckResult, CheckStatus, Decision, DecisionStatus, Severity

SEV_WEIGHT = {Severity.INFO: 0, Severity.WARN: 1, Severity.FIXABLE: 3, Severity.ESCALATE: 5, Severity.BLOCKER: 20}


def decide(applic: list[RuleApplicability], results: dict[str, CheckResult], rule_version: str) -> Decision:
    reasons: list[dict] = []
    all_findings = [f for r in results.values() for f in r.findings]
    score = sum(SEV_WEIGHT.get(f.severity, 0) for f in all_findings)
    needs_human = any(f.severity == Severity.ESCALATE for f in all_findings)

    blockers = [f for f in all_findings if f.severity == Severity.BLOCKER]
    if blockers:
        reasons = [{"type": "BLOCKER", "rule_id": f.rule_id, "finding_id": f.finding_id} for f in blockers]
        return Decision(DecisionStatus.REJECTED, "COMPLETED", reasons, needs_human, score, rule_version)

    expected = [a for a in applic if a.applicability == Applicability.REQUIRED]
    if not expected:  # an empty rule set must never approve
        reasons.append({"type": "EMPTY_EXPECTED_RULE_SET"})

    for a in applic:
        res = results.get(a.rule_id)
        if a.applicability in (Applicability.CONDITIONAL, Applicability.REVIEW_REQUIRED):
            reasons.append({"type": "UNRESOLVED_APPLICABILITY", "rule_id": a.rule_id, "detail": a.reason})
            needs_human = needs_human or a.applicability == Applicability.REVIEW_REQUIRED
        if a.applicability == Applicability.REQUIRED:
            if res is None:
                reasons.append({"type": "REQUIRED_RULE_MISSING", "rule_id": a.rule_id})
            elif res.check_status in (CheckStatus.NOT_RUN, CheckStatus.ERROR):
                reasons.append({"type": f"REQUIRED_RULE_{res.check_status.value}", "rule_id": a.rule_id, "detail": res.note})
            elif res.check_status in (CheckStatus.FAIL, CheckStatus.REVIEW_REQUIRED):
                pass  # explained by the findings below

    for f in all_findings:
        if f.severity in (Severity.FIXABLE, Severity.ESCALATE):
            reasons.append({"type": f.severity.value, "rule_id": f.rule_id, "finding_id": f.finding_id})

    if reasons:
        visible_fix = any(f.severity == Severity.FIXABLE and f.vendor_visible for f in all_findings)
        state = "ACTION_REQUIRED" if visible_fix else "UNDER_REVIEW"
        return Decision(DecisionStatus.PENDING, state, reasons, needs_human, score, rule_version)
    return Decision(DecisionStatus.APPROVED, "COMPLETED", [], needs_human, score, rule_version)
