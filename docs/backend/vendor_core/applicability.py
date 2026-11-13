"""Five-dimensional applicability: registration country, entity type, vendor category, rule jurisdiction, buyer policy.

NOT_APPLICABLE is never a pass: it is recorded with a reason. Unknown entity types route to REVIEW_REQUIRED, never guessed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Applicability

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"

# conditional rule -> registration type that drives it
INDIRECT_RULES = {"IN-004": "GSTIN", "US-003": "SALES_TAX", "GB-003": "VAT"}


@dataclass
class Config:
    country_rules: dict[str, Any]
    catalog: dict[str, Any]
    policy: dict[str, Any]

    @property
    def rule_version(self) -> str:
        return f"{self.catalog['catalog_version']}+{self.country_rules['version']}+policy-{self.policy['policy_version']}"

    @property
    def rules(self) -> list[dict[str, Any]]:
        return self.catalog["rules"]


def load_config(config_dir: Path | None = None, policy_overrides: dict[str, Any] | None = None) -> Config:
    d = Path(config_dir) if config_dir else CONFIG_DIR
    load = lambda n: json.loads((d / n).read_text())
    policy = load("buyer_policy_default.json")
    policy.update(policy_overrides or {})
    return Config(load("country_rules.json"), load("rule_catalog.json"), policy)


@dataclass
class VendorContext:
    registration_country: str
    entity_type: str
    categories: list[str]
    tax_jurisdictions: list[str]
    bank_countries: list[str]
    operating_countries: list[str]
    policy_id: str

    @classmethod
    def from_submission(cls, sub: dict[str, Any], policy: dict[str, Any]) -> "VendorContext":
        p = sub.get("profile", {})
        regs = sub.get("tax_registrations", [])
        banks = sub.get("bank_accounts", [])
        return cls(
            registration_country=(p.get("country") or "").upper(),
            entity_type=(p.get("entity_type") or "").lower(),
            categories=[c.lower() for c in p.get("categories", [])],
            tax_jurisdictions=sorted({(r.get("jurisdiction") or "").upper() for r in regs if r.get("jurisdiction")}),
            bank_countries=sorted({(b.get("country") or "").upper() for b in banks if b.get("country")}),
            operating_countries=[c.upper() for c in p.get("operating_countries", [])],
            policy_id=policy["policy_id"],
        )


@dataclass
class RuleApplicability:
    rule_id: str
    applicability: Applicability
    reason: str


def _matches(applies: dict[str, Any], ctx: VendorContext) -> tuple[bool, bool]:
    """Return (country_and_category_match, entity_restricted_but_unknown_entity)."""
    if "registration_country" in applies and ctx.registration_country not in applies["registration_country"]:
        return False, False
    if "categories" in applies and not set(applies["categories"]) & set(ctx.categories):
        return False, False
    if "entity_types" in applies:
        if ctx.entity_type == "other":
            return True, True
        if ctx.entity_type not in applies["entity_types"]:
            return False, False
    return True, False


def indirect_status(sub: dict[str, Any], reg_type: str) -> tuple[str | None, str | None]:
    """Declared status + reason for an indirect-tax registration type (None if not declared)."""
    for r in sub.get("tax_registrations", []):
        if (r.get("type") or "").upper() == reg_type:
            return (r.get("status") or None), (r.get("status_reason") or None)
    return None, None


def _resolve_indirect(reg_type: str, sub: dict[str, Any], policy: dict[str, Any]) -> tuple[Applicability, str]:
    status, reason = indirect_status(sub, reg_type)
    if status is None:
        return Applicability.CONDITIONAL, f"{reg_type} registration status not declared (condition unresolved)"
    if status == "registered":
        return Applicability.REQUIRED, f"{reg_type} declared as registered"
    if status in ("not_registered", "not_applicable"):
        if reason and policy.get("accept_declared_indirect_tax_status_with_reason"):
            return (Applicability.NOT_APPLICABLE,
                    f"{reg_type} declared '{status}' with reason; accepted under buyer policy {policy['policy_id']} "
                    f"(a declaration, not a legal determination)")
        return Applicability.REVIEW_REQUIRED, f"{reg_type} declared '{status}' without an acceptable reason"
    return Applicability.REVIEW_REQUIRED, f"{reg_type} status '{status}' needs review"


def resolve_applicability(cfg: Config, ctx: VendorContext, sub: dict[str, Any]) -> list[RuleApplicability]:
    out: list[RuleApplicability] = []
    for rule in cfg.rules:
        rid = rule["rule_id"]
        ok, unknown_entity = _matches(rule.get("applies_to", {}), ctx)
        if not ok:
            out.append(RuleApplicability(rid, Applicability.NOT_APPLICABLE,
                                         "context does not match (country / entity type / category)"))
            continue
        if unknown_entity:
            out.append(RuleApplicability(rid, Applicability.REVIEW_REQUIRED,
                                         "entity type 'other' is not configured; human review required"))
            continue
        flag = rule.get("policy_flag")
        if flag:
            if cfg.policy.get(flag):
                out.append(RuleApplicability(rid, Applicability.REQUIRED, f"required by buyer policy ({flag})"))
            else:
                out.append(RuleApplicability(rid, Applicability.NOT_APPLICABLE, f"buyer policy does not enable {flag}"))
            continue
        if rid in INDIRECT_RULES:
            app, why = _resolve_indirect(INDIRECT_RULES[rid], sub, cfg.policy)
            out.append(RuleApplicability(rid, app, why))
            continue
        out.append(RuleApplicability(rid, Applicability(rule["applicability"]), "applies to this vendor context"))
    return out


# ------------------------------------------------------------------ document slots
@dataclass
class Slot:
    slot_id: str
    label: str
    doc_type: str
    group: str
    requirement: str          # REQUIRED | RECOMMENDED | OPTIONAL | NOT_APPLICABLE | REVIEW_REQUIRED
    reason: str = ""
    name_xref: bool = False
    account_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def resolve_slots(cfg: Config, ctx: VendorContext, sub: dict[str, Any]) -> list[Slot]:
    slots: list[Slot] = []
    for s in cfg.country_rules["document_slots"]:
        ok, unknown_entity = _matches(s.get("applies_to", {}), ctx)
        if not ok:
            continue
        req, reason = s["requirement"], ""
        if unknown_entity:
            req, reason = "REVIEW_REQUIRED", "entity type not configured"
        elif req == "CONDITIONAL":
            cond_type = s["condition"]["registration_type"]
            app, reason = _resolve_indirect(cond_type, sub, cfg.policy)
            req = {Applicability.REQUIRED: "REQUIRED", Applicability.NOT_APPLICABLE: "NOT_APPLICABLE"}.get(app, "REVIEW_REQUIRED")
        slots.append(Slot(s["slot_id"], s["label"], s["doc_type"], s["group"], req, reason, s.get("name_xref", False)))
    for b in sub.get("bank_accounts", []):
        aid = b.get("id", "acct")
        slots.append(Slot(f"bank_evidence:{aid}", f"Bank evidence for account {aid}", "BANK_EVIDENCE", "banking",
                          "REQUIRED", "each bank account needs evidence", False, aid))
        slots.append(Slot(f"bank_auth:{aid}", f"Account-holder authorisation letter ({aid})", "AUTH_LETTER", "banking",
                          "OPTIONAL", "needed only if the account holder differs from the business", False, aid))
    return slots
