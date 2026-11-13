"""Dependency-aware reruns, HMAC change detection, resolved / still_open / newly_introduced diff, attempt + lapse policy."""
from __future__ import annotations

from datetime import date, datetime
from fnmatch import fnmatch
from typing import Any

from .models import CheckResult, Severity
from .security import hmac_fingerprint

RISK_RULES = {"RSK-001", "RSK-002", "RSK-003"}


def flatten(sub: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for k, v in (sub.get("profile") or {}).items():
        flat[f"profile.{k}"] = v
    flat["tax_registrations"] = sub.get("tax_registrations", [])
    flat["bank_accounts"] = sub.get("bank_accounts", [])
    for d in sub.get("documents", []):
        flat[f"documents.{d.get('slot_id')}"] = {k: v for k, v in d.items() if k != "upload_attempts"}
    flat["declaration"] = sub.get("declaration", {})
    return flat


def fingerprints(sub: dict[str, Any], key: bytes) -> dict[str, str]:
    """HMAC per input path so diffs never store raw sensitive values."""
    return {path: hmac_fingerprint(val, key) for path, val in flatten(sub).items()}


def changed_paths(old: dict[str, str], new: dict[str, str]) -> list[str]:
    return sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))


def rules_to_rerun(catalog_rules: list[dict], changed: list[str], previous_had_risk_flag: bool) -> set[str]:
    out = set()
    for r in catalog_rules:
        if any(fnmatch(p, pat) for p in changed for pat in r["depends_on"]):
            out.add(r["rule_id"])
    # Bank or tax identifiers changed after a risk flag -> rerun ALL risk checks.
    if previous_had_risk_flag and any(p in ("bank_accounts", "tax_registrations") for p in changed):
        out |= RISK_RULES
    return out


def diff_findings(old: list, new: list) -> dict[str, list[str]]:
    o, n = {f.finding_id: f for f in old if f.severity not in (Severity.INFO, Severity.PASS)}, \
           {f.finding_id: f for f in new if f.severity not in (Severity.INFO, Severity.PASS)}
    return {"resolved": sorted(set(o) - set(n)), "still_open": sorted(set(o) & set(n)), "newly_introduced": sorted(set(n) - set(o))}


def attempt_policy(failed_attempts: int, submitted_on: date | None, today: date, policy: dict[str, Any]) -> dict[str, Any]:
    """Configurable defaults, not universal requirements."""
    escalate = failed_attempts >= policy["escalate_after_failed_attempts"]
    lapsed = bool(submitted_on and (today - submitted_on).days >= policy["lapse_pending_after_days"])
    return {"escalate_to_human": escalate, "lapsed": lapsed}


def parse_day(s: str | None) -> date | None:
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None
