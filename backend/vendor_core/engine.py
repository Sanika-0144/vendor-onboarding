"""Orchestrator: applicability -> run rules (with stage events) -> decide -> communicate. Fail-closed on handler errors."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .adapters import SanctionsAdapter
from .applicability import CONFIG_DIR, Config, VendorContext, load_config, resolve_applicability, resolve_slots, Slot
from .communication import VendorMessage, build_vendor_message, internal_note, vendor_safe_findings, vendor_tracking
from .decision import decide
from .models import Applicability, CheckResult, CheckStatus, Decision, DecisionStatus, Finding, Severity, derive_status
from .resubmission import RISK_RULES, changed_paths, diff_findings, fingerprints, rules_to_rerun
from .rules import HANDLERS, EvalContext
from .security import get_secret_key

STAGE_ORDER = ["INTAKE", "DOCUMENTS", "FORMAT", "BANKING", "CROSS_REFERENCE", "RISK"]
STAGE_LABELS = {"INTAKE": "Intake & completeness", "DOCUMENTS": "Document checks", "FORMAT": "Tax & registration validation",
                "BANKING": "Banking validation", "CROSS_REFERENCE": "Cross-referencing", "RISK": "Risk checks (internal)",
                "DECISION": "Decision roll-up", "COMMUNICATION": "Vendor communication"}


@dataclass
class EvaluationResult:
    application_ref: str
    version: int
    rule_version: str
    context: dict[str, Any]
    applicability: list[dict[str, Any]]
    slots: list[dict[str, Any]]
    results: dict[str, CheckResult]
    decision: Decision
    document_statuses: dict[str, str]
    vendor_message: VendorMessage
    fingerprints: dict[str, str]
    findings: list[Finding]
    events: list[dict[str, Any]] = field(default_factory=list)
    rerun: dict[str, Any] | None = None
    finding_diff: dict[str, list[str]] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self, *, internal: bool = True) -> dict[str, Any]:
        """internal=False returns the VENDOR-SAFE view only."""
        if not internal:
            return {"application_ref": self.application_ref, "version": self.version,
                    "application_state": self.decision.application_state,
                    "status": self.decision.status.value,
                    "tracking": vendor_tracking(self.decision.application_state, self.decision.status),
                    "document_statuses": self.document_statuses,
                    "required_actions": vendor_safe_findings(self.findings),
                    "message": self.vendor_message.to_dict()}
        return {"application_ref": self.application_ref, "version": self.version, "rule_version": self.rule_version,
                "context": self.context, "applicability": self.applicability, "slots": self.slots,
                "results": {k: v.to_dict() for k, v in self.results.items()},
                "decision": self.decision.to_dict(), "document_statuses": self.document_statuses,
                "vendor_message": self.vendor_message.to_dict(), "internal_findings": internal_note(self.findings),
                "events": self.events, "rerun": self.rerun, "finding_diff": self.finding_diff, "notes": self.notes}


class OnboardingEngine:
    def __init__(self, cfg: Config | None = None, existing_vendors: list[dict] | None = None,
                 sanctions: SanctionsAdapter | None = None, today: date | None = None, hmac_key: bytes | None = None):
        self.cfg = cfg or load_config()
        self.existing = existing_vendors if existing_vendors is not None else \
            json.loads((CONFIG_DIR / "existing_vendors.json").read_text())["vendors"]
        self.sanctions = sanctions
        self.today = today or date.today()
        self.key = hmac_key or get_secret_key()

    # ------------------------------------------------------------------
    def evaluate(self, sub: dict[str, Any], *, application_ref: str = "APP-DEMO", version: int = 1,
                 previous: EvaluationResult | None = None, reviewer_actions: list[dict] | None = None,
                 on_event: Callable[[dict], None] | None = None, step_delay: float = 0.0) -> EvaluationResult:
        events: list[dict] = []

        def emit(ev: dict):
            ev["seq"] = len(events) + 1
            events.append(ev)
            if on_event:
                on_event(ev)
            if step_delay:
                time.sleep(step_delay)

        cfg = self.cfg
        vctx = VendorContext.from_submission(sub, cfg.policy)
        applic = resolve_applicability(cfg, vctx, sub)
        applic_map = {a.rule_id: a for a in applic}
        slots = resolve_slots(cfg, vctx, sub)
        fps = fingerprints(sub, self.key)

        # ---- resubmission planning
        rerun_info, rerun_set, notes = None, None, []
        if previous and previous.rule_version == cfg.rule_version:
            ch = changed_paths(previous.fingerprints, fps)
            had_flag = any(f.rule_id in RISK_RULES and f.severity in (Severity.ESCALATE, Severity.BLOCKER) for f in previous.findings)
            rerun_set = rules_to_rerun(cfg.rules, ch, had_flag)
            # applicability changes force a rerun of that rule
            for rid, a in applic_map.items():
                pa = next((x for x in previous.applicability if x["rule_id"] == rid), None)
                if not pa or pa["applicability"] != a.applicability.value:
                    rerun_set.add(rid)
            live = {rid for rid, a in applic_map.items() if a.applicability != Applicability.NOT_APPLICABLE}
            rerun_info = {"changed_inputs": ch, "rules_rerun": sorted(rerun_set & live),
                          "rules_reused": sorted(live - rerun_set), "risk_flag_before": had_flag}
            if had_flag and any(p in ("bank_accounts", "tax_registrations") for p in ch):
                notes.append("Bank/tax details changed after a risk flag: all risk checks re-run and flagged for review.")
        elif previous:
            notes.append("Rule version changed since previous evaluation: full re-run.")

        ectx = EvalContext(sub, vctx, cfg, slots, self.existing, self.sanctions, self.today,
                           {a.rule_id: a.applicability.value for a in applic})
        results: dict[str, CheckResult] = {}
        emit({"type": "run_started", "application_ref": application_ref, "version": version, "rule_version": cfg.rule_version})
        emit({"type": "applicability_resolved", "stage": "INTAKE",
              "summary": {"registration_country": vctx.registration_country, "entity_type": vctx.entity_type, "categories": vctx.categories,
                          "tax_jurisdictions": vctx.tax_jurisdictions, "bank_countries": vctx.bank_countries, "policy": vctx.policy_id,
                          "required_rules": sum(a.applicability == Applicability.REQUIRED for a in applic),
                          "not_applicable_rules": sum(a.applicability == Applicability.NOT_APPLICABLE for a in applic)}})

        for stage in STAGE_ORDER:
            rules = [r for r in cfg.rules if r["stage"] == stage]
            emit({"type": "stage_started", "stage": stage, "label": STAGE_LABELS[stage]})
            for rule in rules:
                rid, a = rule["rule_id"], applic_map[rule["rule_id"]]
                reused = previous is not None and rerun_set is not None and rid not in rerun_set and rid in previous.results
                if a.applicability == Applicability.NOT_APPLICABLE:
                    res = CheckResult(rid, a.applicability, CheckStatus.NOT_RUN, [], [], cfg.rule_version, stage, f"Not applicable: {a.reason}")
                elif reused:
                    old = previous.results[rid]
                    res = CheckResult(rid, a.applicability, old.check_status, list(old.findings), list(old.evidence_refs), old.rule_version, stage,
                                      "reused from previous version (inputs unchanged)")
                else:
                    try:
                        out = HANDLERS[rule["handler"]](ectx, rule)
                        status = out.status or derive_status(out.findings)
                        res = CheckResult(rid, a.applicability, status, out.findings, out.evidence, cfg.rule_version, stage, out.note or a.reason)
                    except Exception as exc:  # fail closed: errors can never approve
                        res = CheckResult(rid, a.applicability, CheckStatus.ERROR,
                                          [Finding(rid, "RULE_ERROR", Severity.ESCALATE, f"Technical error while running rule {rid}.", vendor_visible=False)],
                                          [], cfg.rule_version, stage, f"{type(exc).__name__}: {exc}")
                results[rid] = res
                emit({"type": "rule_completed", "stage": stage, "rule_id": rid, "name": rule["name"], "applicability": a.applicability.value,
                      "check_status": res.check_status.value, "reused": reused, "finding_count": len(res.findings),
                      "findings": [{"finding_id": f.finding_id, "severity": f.severity.value, "message": f.message, "vendor_visible": f.vendor_visible}
                                   for f in res.findings if f.severity != Severity.PASS], "note": res.note})
            emit({"type": "stage_completed", "stage": stage})

        # ---- changed-after-flag guard
        if previous and rerun_info and rerun_info["risk_flag_before"] and any(p in ("bank_accounts", "tax_registrations") for p in rerun_info["changed_inputs"]):
            g = Finding("RSK-004", "DETAILS_CHANGED_AFTER_FLAG", Severity.ESCALATE,
                        "Bank or tax details were changed after a risk flag; reviewer must re-assess.", vendor_visible=False, escalate=True)
            results["RSK-004"] = CheckResult("RSK-004", Applicability.REQUIRED, CheckStatus.REVIEW_REQUIRED, [g], [], cfg.rule_version, "RISK", "guard")
            emit({"type": "rule_completed", "stage": "RISK", "rule_id": "RSK-004", "name": "Details changed after risk flag",
                  "applicability": "REQUIRED", "check_status": "REVIEW_REQUIRED", "reused": False, "finding_count": 1,
                  "findings": [{"finding_id": g.finding_id, "severity": "ESCALATE", "message": g.message, "vendor_visible": False}], "note": "guard"})
            reviewer_actions = [a for a in (reviewer_actions or []) if a.get("finding_id", "").split("|")[0] not in RISK_RULES]
            notes.append("Earlier reviewer resolutions of risk findings were voided because details changed.")

        self._apply_reviewer_actions(results, reviewer_actions or [], cfg, emit)

        # ---- decision
        findings = [f for r in results.values() for f in r.findings]
        decision = decide(applic, results, cfg.rule_version)
        emit({"type": "stage_started", "stage": "DECISION", "label": STAGE_LABELS["DECISION"]})
        emit({"type": "decision", "stage": "DECISION", "status": decision.status.value, "application_state": decision.application_state,
              "reason_count": len(decision.reasons), "needs_human_review": decision.needs_human_review})
        msg = build_vendor_message(application_ref, decision.status, findings)
        emit({"type": "stage_started", "stage": "COMMUNICATION", "label": STAGE_LABELS["COMMUNICATION"]})
        emit({"type": "communication_built", "stage": "COMMUNICATION", "vendor_items": len(msg.items), "internal_hidden": msg.internal_hidden_count})
        emit({"type": "run_completed", "status": decision.status.value})

        diff = diff_findings(previous.findings, findings) if previous else None
        return EvaluationResult(application_ref, version, cfg.rule_version, vctx.__dict__.copy(), [
            {"rule_id": a.rule_id, "applicability": a.applicability.value, "reason": a.reason} for a in applic],
            [s.to_dict() for s in slots], results, decision, self._doc_statuses(sub, slots, findings), msg, fps, findings,
            events, rerun_info, diff, notes)

    # ------------------------------------------------------------------
    @staticmethod
    def _apply_reviewer_actions(results, actions, cfg, emit):
        """Authorised reviewer actions only (RBAC is enforced at the API layer, not here)."""
        for act in actions:
            kind = act.get("type")
            if kind == "confirm_blocker":
                f = Finding(act["rule_id"], "CONFIRMED_BLOCKER", Severity.BLOCKER,
                            f"Reviewer {act.get('reviewer','?')} confirmed a disqualifying condition: {act.get('reason','')}",
                            vendor_visible=False)
                res = results.setdefault(act["rule_id"], CheckResult(act["rule_id"], Applicability.REQUIRED, CheckStatus.FAIL, [], [], cfg.rule_version, "RISK"))
                res.findings.append(f)
                res.check_status = CheckStatus.FAIL
                emit({"type": "reviewer_action", "action": kind, "rule_id": act["rule_id"], "reviewer": act.get("reviewer")})
            elif kind == "resolve_escalation":
                for res in results.values():
                    for i, f in enumerate(res.findings):
                        if f.finding_id == act["finding_id"] and f.severity == Severity.ESCALATE:
                            res.findings[i] = Finding(f.rule_id, f.code, Severity.INFO,
                                                      f"Resolved by reviewer {act.get('reviewer','?')}: {act.get('note','')}",
                                                      f.subject, f.fields, False, "", False, f.evidence_refs)
                    res.check_status = derive_status(res.findings) if res.check_status != CheckStatus.NOT_RUN else res.check_status
                emit({"type": "reviewer_action", "action": kind, "finding_id": act["finding_id"], "reviewer": act.get("reviewer")})

    @staticmethod
    def _doc_statuses(sub, slots: list[Slot], findings: list[Finding]) -> dict[str, str]:
        out = {}
        by_slot = {s.slot_id: s for s in slots}
        for d in sub.get("documents", []):
            sid = d.get("slot_id")
            s = by_slot.get(sid)
            rel = [f for f in findings if f.subject == sid or (s and s.account_id and f.rule_id == "BNK-004" and f.subject == s.account_id)]
            if any(f.severity == Severity.ESCALATE for f in rel):
                out[sid] = "HUMAN_REVIEW"
            elif any(f.severity in (Severity.FIXABLE, Severity.BLOCKER) for f in rel):
                out[sid] = "ACTION_REQUIRED"
            else:
                out[sid] = "ACCEPTED"
        return out
