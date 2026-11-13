import copy
import json
from datetime import date

import pytest

from demo.scenarios import *  # noqa
from demo import scenarios as S
from vendor_core import OnboardingEngine, SyntheticSanctionsAdapter, UnavailableSanctionsAdapter, load_config
from vendor_core import validators as V
from vendor_core.audit import AuditLog
from vendor_core.communication import validate_polished
from vendor_core.decision import decide
from vendor_core.models import Applicability, CheckResult, CheckStatus, DecisionStatus, Finding, Severity
from vendor_core.names import compare_names
from vendor_core.security import mask, mask_deep

TODAY = date(2026, 11, 12)


@pytest.fixture
def eng():
    return OnboardingEngine(sanctions=SyntheticSanctionsAdapter(), today=TODAY, hmac_key=b"test-key")


def ids(r, *sev):
    return {f.finding_id for f in r.findings if f.severity.value in sev}


# ------------------------------------------------------------ validators (public test vectors)
def test_gstin_known_vector_and_generated():
    assert V.valid_gstin("27AAPFU0939F1ZV")
    assert V.valid_gstin(V.make_gstin("AABCA1234C"))
    assert not V.valid_gstin("27AAPFU0939F1ZW")


def test_identifier_validators():
    assert V.valid_pan("AABCA1234C") and not V.valid_pan("AABC1234CA")
    assert V.valid_ifsc("HDFC0001234") and not V.valid_ifsc("HDFC1001234")
    assert V.valid_cin("U29100PN2012PTC145678") and not V.valid_cin("X29100PN2012PTC145678")
    assert V.valid_aba("021000021") and not V.valid_aba("123456789")
    assert V.valid_iban("GB82 WEST 1234 5698 7654 32") and not V.valid_iban("GB82WEST12345698765433")
    assert V.valid_uk_company_number("SC123456") and not V.valid_uk_company_number("12345")
    assert V.valid_sort_code("20-00-00") and V.valid_utr("1234567890")


# ------------------------------------------------------------ names
def test_name_cosmetic_and_form_rules():
    assert compare_names("ABC Manufacturing Pvt. Ltd.", "ABC Manufacturing Private Limited").tier == "COSMETIC"
    assert compare_names("Acme Solutions Pvt Ltd", "Acme Solutions LLP").tier == "FORM_CONFLICT"
    assert compare_names("Acme Sol", "Acme Solutions").tier == "ABBREVIATED"
    assert compare_names("Acme Traders", "Zenith Components").tier == "MISMATCH"
    assert compare_names("Rahul Verma", "Verma Rahul", order_insensitive=True).tier == "COSMETIC"


def test_fuzzy_similarity_never_passes():
    m = compare_names("ABC Manufacturing", "ABD Manufacturing")
    assert m.tier in ("AMBIGUOUS", "MISMATCH")


# ------------------------------------------------------------ happy paths & edge cases
@pytest.mark.parametrize("key", ["happy_in", "happy_us", "happy_gb"])
def test_happy_paths_approve(eng, key):
    r = eng.evaluate(S.SCENARIOS[key][1]())
    assert r.decision.status == DecisionStatus.APPROVED, r.decision.reasons


def test_edge1_cosmetic_name_approved_with_info(eng):
    r = eng.evaluate(S.edge1_cosmetic_name())
    assert r.decision.status == DecisionStatus.APPROVED
    assert any(f.code == "NAME_COSMETIC" and f.severity == Severity.INFO for f in r.findings)
    assert r.findings and S.edge1_cosmetic_name()["profile"]["legal_name"] == "ABC Manufacturing Pvt. Ltd."  # original preserved


def test_edge2a_sole_prop_own_account_not_rejected(eng):
    r = eng.evaluate(S.edge2a_sole_prop_own_account())
    assert r.decision.status == DecisionStatus.APPROVED
    assert any(f.code == "SOLE_PROP_OWN_ACCOUNT" for f in r.findings)


def test_edge2a_policy_human_review(eng):
    e = OnboardingEngine(cfg=load_config(policy_overrides={"sole_prop_personal_account": "human_review"}),
                         sanctions=SyntheticSanctionsAdapter(), today=TODAY, hmac_key=b"k")
    r = e.evaluate(S.edge2a_sole_prop_own_account())
    assert r.decision.status == DecisionStatus.PENDING and r.decision.needs_human_review


def test_edge2b_third_party_account_pending_not_rejected(eng):
    r = eng.evaluate(S.edge2b_sole_prop_third_party())
    assert r.decision.status == DecisionStatus.PENDING
    assert "BNK-003|acct1|HOLDER_UNRELATED" in ids(r, "ESCALATE")


def test_edge3_pan_mismatch_pending_vendor_visible(eng):
    r = eng.evaluate(S.edge3_pan_mismatch())
    assert r.decision.status == DecisionStatus.PENDING and r.decision.application_state == "ACTION_REQUIRED"
    assert "GEN-010|PAN|PAN_FORM_DOC_MISMATCH" in ids(r, "FIXABLE")
    assert any("PAN" in i["text"] for i in r.vendor_message.items)


def test_edge4_duplicate_bank_internal_only(eng):
    r = eng.evaluate(S.edge4_duplicate_bank())
    assert r.decision.status == DecisionStatus.PENDING and r.decision.application_state == "UNDER_REVIEW"
    dup = [f for f in r.findings if f.rule_id == "RSK-001"]
    assert dup and all(not f.vendor_visible for f in dup)
    vendor_view = json.dumps(r.to_dict(internal=False)).lower()
    for leak in ("duplicate", "existing vendor", "v-1001", "50100123456789", "risk", "fraud"):
        assert leak not in vendor_view


def test_similarity_alone_is_not_a_blocker(eng):
    r = eng.evaluate(S.edge4b_sanctions_hit())
    assert r.decision.status == DecisionStatus.PENDING          # potential match -> human review, NOT rejected
    assert not any(f.severity == Severity.BLOCKER for f in r.findings)


def test_reviewer_confirmed_blocker_rejects_and_vendor_not_told(eng):
    r = eng.evaluate(S.edge4b_sanctions_hit(),
                     reviewer_actions=[{"type": "confirm_blocker", "rule_id": "RSK-003", "reviewer": "r1", "reason": "confirmed against official source"}])
    assert r.decision.status == DecisionStatus.REJECTED
    body = r.vendor_message.body.lower()
    assert "sanction" not in body and "screening" not in body


def test_reviewer_can_resolve_escalation(eng):
    r1 = eng.evaluate(S.edge4_duplicate_bank())
    fid = next(f.finding_id for f in r1.findings if f.rule_id == "RSK-001")
    r2 = eng.evaluate(S.edge4_duplicate_bank(), reviewer_actions=[{"type": "resolve_escalation", "finding_id": fid, "reviewer": "r2", "note": "same group company, verified"}])
    assert r2.decision.status == DecisionStatus.APPROVED


# ------------------------------------------------------------ fail-closed behaviour
def test_unavailable_sanctions_provider_fails_closed():
    e = OnboardingEngine(sanctions=UnavailableSanctionsAdapter(), today=TODAY, hmac_key=b"k")
    r = e.evaluate(S.in_private_limited())
    assert r.decision.status == DecisionStatus.PENDING
    assert any(x["type"] == "REQUIRED_RULE_NOT_RUN" and x["rule_id"] == "RSK-003" for x in r.decision.reasons)


def test_no_sanctions_adapter_fails_closed_when_policy_requires():
    e = OnboardingEngine(sanctions=None, today=TODAY, hmac_key=b"k")
    assert e.evaluate(S.in_private_limited()).decision.status == DecisionStatus.PENDING


def test_sanctions_not_required_by_policy_is_not_applicable():
    e = OnboardingEngine(cfg=load_config(policy_overrides={"require_sanctions_screening": False}), sanctions=None, today=TODAY, hmac_key=b"k")
    r = e.evaluate(S.in_private_limited())
    assert r.decision.status == DecisionStatus.APPROVED
    assert r.results["RSK-003"].check_status == CheckStatus.NOT_RUN       # N/A is recorded, not a pass


def test_empty_rule_set_never_approves():
    assert decide([], {}, "v").status == DecisionStatus.PENDING


def test_handler_error_fails_closed(eng, monkeypatch):
    from vendor_core import rules
    def boom(c, r): raise RuntimeError("kaboom")
    monkeypatch.setitem(rules.HANDLERS, "in_pan", boom)
    r = eng.evaluate(S.in_private_limited())
    assert r.results["IN-001"].check_status == CheckStatus.ERROR
    assert r.decision.status == DecisionStatus.PENDING


def test_malware_scan_required_but_unavailable_fails_closed():
    e = OnboardingEngine(cfg=load_config(policy_overrides={"malware_scan_required": True}), sanctions=SyntheticSanctionsAdapter(), today=TODAY, hmac_key=b"k")
    s = S.in_private_limited()
    for d in s["documents"]: d["malware_scan"] = {"status": "NOT_SCANNED"}
    assert e.evaluate(s).decision.status == DecisionStatus.PENDING


def test_unknown_entity_type_routes_to_review_not_guessed(eng):
    s = S.in_private_limited(); s["profile"]["entity_type"] = "other"
    r = eng.evaluate(s)
    assert r.decision.status == DecisionStatus.PENDING and r.decision.needs_human_review
    assert r.results["IN-002"].applicability == Applicability.REVIEW_REQUIRED


# ------------------------------------------------------------ pre-submit / banking / docs
def test_missing_mandatory_items_pending(eng):
    s = S.in_private_limited(); s["profile"]["legal_name"] = ""; s["documents"] = [d for d in s["documents"] if d["slot_id"] != "pan_card"]
    r = eng.evaluate(s)
    assert {"GEN-001|-|MISSING_LEGAL_NAME", "GEN-004|pan_card|MISSING_DOC"} <= ids(r, "FIXABLE")


@pytest.mark.parametrize("primaries", [0, 2])
def test_exactly_one_primary_bank(eng, primaries):
    s = S.in_private_limited()
    b2 = copy.deepcopy(s["bank_accounts"][0]); b2["id"] = "acct2"
    s["bank_accounts"].append(b2)
    s["bank_accounts"][0]["is_primary"] = primaries == 2
    s["bank_accounts"][1]["is_primary"] = primaries == 2
    assert "BNK-001|-|PRIMARY_COUNT" in ids(eng.evaluate(s), "FIXABLE")


def test_cross_border_bank_is_info_not_failure(eng):
    s = S.gb_ltd(); s["bank_accounts"][0].update({"country": "US", "identifier": "021000021", "routing_use": "WIRE", "account_number": "000555666777"})
    s["documents"][1]["extraction"]["fields"]["account_number"]["value"] = "000555666777"
    r = eng.evaluate(s)
    assert any(f.code == "CROSS_BORDER_BANK" and f.severity == Severity.INFO for f in r.findings)
    assert r.decision.status == DecisionStatus.APPROVED


def test_expired_and_stale_and_expiring_docs(eng):
    s = S.sole_prop_base(); s["documents"].append(S._doc("trade_licence", "TRADE_LICENCE", {"name": "Rahul Verma"}, expiry="2026-10-01"))
    assert "GEN-007|trade_licence|EXPIRED" in ids(eng.evaluate(s), "FIXABLE")
    s = S.sole_prop_base(); s["documents"].append(S._doc("trade_licence", "TRADE_LICENCE", {"name": "Rahul Verma"}, expiry="2026-11-30"))
    r = eng.evaluate(s); assert r.decision.status == DecisionStatus.APPROVED and "GEN-007|trade_licence|EXPIRING_SOON" in ids(r, "WARN")
    s = S.in_private_limited(); s["documents"][-1]["issue_date"] = "2026-06-01"
    assert "GEN-007|bank_evidence:acct1|STALE_DOCUMENT" in ids(eng.evaluate(s), "FIXABLE")


def test_wrong_document_type_and_bad_file(eng):
    s = S.in_private_limited(); s["documents"][0]["detected_type"] = "BANK_EVIDENCE"; s["documents"][1]["filename"] = "x.exe"
    r = eng.evaluate(s)
    assert {"GEN-006|pan_card|WRONG_DOC_TYPE", "GEN-005|incorporation_cert|BAD_EXTENSION"} <= ids(r, "FIXABLE")


def test_low_confidence_reupload_then_human_review(eng):
    r1 = eng.evaluate(S.low_confidence(attempts=1))
    assert "GEN-008|pan_card|LOW_CONFIDENCE_REUPLOAD" in ids(r1, "FIXABLE") and r1.document_statuses["pan_card"] == "ACTION_REQUIRED"
    r2 = eng.evaluate(S.low_confidence(attempts=2))
    assert "GEN-008|pan_card|LOW_CONFIDENCE_HUMAN_REVIEW" in ids(r2, "ESCALATE") and r2.document_statuses["pan_card"] == "HUMAN_REVIEW"
    assert r2.decision.status == DecisionStatus.PENDING


def test_unresolved_gst_applicability_pending(eng):
    s = S.sole_prop_base(); s["tax_registrations"] = [t for t in s["tax_registrations"] if t["type"] != "GSTIN"]
    r = eng.evaluate(s)
    assert r.decision.status == DecisionStatus.PENDING and r.results["IN-004"].applicability == Applicability.CONDITIONAL


def test_gst_not_registered_without_reason_goes_to_review(eng):
    s = S.sole_prop_base(); s["tax_registrations"][1].pop("status_reason")
    assert eng.evaluate(s).results["IN-004"].applicability == Applicability.REVIEW_REQUIRED


def test_us_foreign_payee_routes_to_tax_review(eng):
    s = S.us_llc(); s["documents"][0]["extraction"]["us_person"] = False
    r = eng.evaluate(s)
    assert "US-001|w9|FOREIGN_PAYEE_TAX_REVIEW" in ids(r, "ESCALATE")


def test_bank_holder_differs_asks_relationship(eng):
    s = S.in_private_limited(); s["bank_accounts"][0].update({"holder_name": "Priya Nair", "holder_type": "individual"})
    s["documents"][-1]["extraction"]["fields"]["account_holder"]["value"] = "Priya Nair"
    r = eng.evaluate(s)
    assert "BNK-003|acct1|HOLDER_DIFFERS_NO_RELATIONSHIP" in ids(r, "FIXABLE") and r.decision.status == DecisionStatus.PENDING


def test_bank_ownership_accepts_frontend_relationship_field_names(eng):
    s = S.in_private_limited()
    account = s["bank_accounts"][0]
    account.update({
        "holder_name": "Priya Nair",
        "holder_type": "individual",
        "account_relationship": "director_authorised_individual",
        "relationship": "director_authorised_individual",
    })
    s["documents"].append({
        "slot_id": f"bank_auth:{account['id']}",
        "doc_type": "AUTH_LETTER",
        "signature_ok": True,
    })
    result = eng.evaluate(s)
    assert "BNK-003|acct1|HOLDER_RELATED_REVIEW" in ids(result, "ESCALATE")


def test_bank_ownership_missing_authorisation_requests_evidence(eng):
    s = S.in_private_limited()
    account = s["bank_accounts"][0]
    account.update({
        "holder_name": "Priya Nair",
        "holder_type": "individual",
        "account_relationship": "director_authorised_individual",
        "relationship": "director_authorised_individual",
    })
    s["documents"] = [
        d for d in s.get("documents", [])
        if d.get("slot_id") != f"bank_auth:{account['id']}"
    ]
    result = eng.evaluate(s)
    assert "BNK-003|acct1|HOLDER_NEEDS_EVIDENCE" in ids(result, "FIXABLE")


def test_bank_ownership_same_entity_still_requires_name_match(eng):
    s = S.in_private_limited()
    account = s["bank_accounts"][0]
    account.update({
        "holder_name": "Unrelated Test Person",
        "account_relationship": "same_legal_entity",
        "relationship": None,
    })
    result = eng.evaluate(s)
    assert "BNK-003|acct1|HOLDER_DIFFERS_NO_RELATIONSHIP" in ids(result, "FIXABLE")


# ------------------------------------------------------------ privacy / masking / communication
def test_findings_never_contain_raw_identifiers(eng):
    r = eng.evaluate(S.edge3_pan_mismatch())
    blob = json.dumps(r.to_dict())
    assert "AABCA1234D" not in blob and "50200098765432" not in blob
    assert mask("AABCA1234C") == "******234C" and mask_deep({"pan": "AABCA1234C", "x": 1})["pan"].endswith("234C")


def test_vendor_message_contains_every_visible_fixable(eng):
    r = eng.evaluate(S.edge3_pan_mismatch())
    vis = [f for f in r.findings if f.vendor_visible and f.severity == Severity.FIXABLE]
    assert len(r.vendor_message.items) >= len(vis) > 0
    assert {i["finding_id"] for i in r.vendor_message.items if i["kind"] == "action"} == {f.finding_id for f in vis}


def test_polish_validator_blocks_dropped_items_and_leaks(eng):
    r = eng.evaluate(S.edge3_pan_mismatch())
    ok, _ = validate_polished(r.vendor_message.body, r.vendor_message, r.findings); assert ok
    assert not validate_polished("Please fix your PAN.", r.vendor_message, r.findings)[0]
    assert not validate_polished(r.vendor_message.body + " (fraud screening)", r.vendor_message, r.findings)[0]


# ------------------------------------------------------------ resubmission
def test_resubmission_reruns_only_dependents_and_diffs(eng):
    bad = S.edge3_pan_mismatch()
    r1 = eng.evaluate(bad, application_ref="A1", version=1)
    assert r1.decision.status == DecisionStatus.PENDING
    r2 = eng.evaluate(S.edge3_resubmission_fixed(bad), application_ref="A1", version=2, previous=r1)
    assert r2.decision.status == DecisionStatus.APPROVED
    assert "GEN-010|PAN|PAN_FORM_DOC_MISMATCH" in r2.finding_diff["resolved"]
    assert r2.finding_diff["newly_introduced"] == []
    assert "tax_registrations" in r2.rerun["changed_inputs"]
    assert "BNK-002" in r2.rerun["rules_reused"] and "IN-001" in r2.rerun["rules_rerun"]


def test_bank_change_after_risk_flag_reruns_risk_and_escalates(eng):
    r1 = eng.evaluate(S.edge4_duplicate_bank(), application_ref="A2", version=1)
    fid = next(f.finding_id for f in r1.findings if f.rule_id == "RSK-001")
    changed = S.edge4_duplicate_bank()
    changed["bank_accounts"][0]["account_number"] = "50999988887777"
    changed["documents"][-1]["extraction"]["fields"]["account_number"]["value"] = "50999988887777"
    r2 = eng.evaluate(changed, application_ref="A2", version=2, previous=r1,
                      reviewer_actions=[{"type": "resolve_escalation", "finding_id": fid, "reviewer": "r", "note": "ok"}])
    assert {"RSK-001", "RSK-002", "RSK-003"} <= set(r2.rerun["rules_rerun"])
    assert "RSK-004|-|DETAILS_CHANGED_AFTER_FLAG" in ids(r2, "ESCALATE")
    assert r2.decision.status == DecisionStatus.PENDING


def test_unchanged_resubmission_reuses_everything(eng):
    s = S.in_private_limited()
    r1 = eng.evaluate(s); r2 = eng.evaluate(copy.deepcopy(s), previous=r1)
    assert r2.rerun["rules_rerun"] == [] and r2.decision.status == r1.decision.status


# ------------------------------------------------------------ events / audit
def test_live_events_stream_in_stage_order(eng):
    seen = []
    eng.evaluate(S.in_private_limited(), on_event=seen.append)
    stages = [e["stage"] for e in seen if e["type"] == "stage_started"]
    assert stages == ["INTAKE", "DOCUMENTS", "FORMAT", "BANKING", "CROSS_REFERENCE", "RISK", "DECISION", "COMMUNICATION"]
    assert seen[0]["type"] == "run_started" and seen[-1]["type"] == "run_completed"


def test_audit_chain_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    log.append("SUBMITTED", "vendor:1", "A1", 1, "rv", {"pan": "AABCA1234C", "note": "x"})
    log.append("DECIDED", "system", "A1", 1, "rv", {"status": "APPROVED"})
    assert log.verify() and "AABCA1234C" not in (tmp_path / "a.jsonl").read_text()
    lines = (tmp_path / "a.jsonl").read_text().replace("APPROVED", "REJECTED")
    (tmp_path / "a.jsonl").write_text(lines)
    assert not log.verify()


def test_presubmit_engine_routes_related_bank_holder_to_review(eng):
    from app.main import _run_presubmit_rules

    s = S.in_private_limited()
    account = s["bank_accounts"][0]
    account.update({
        "holder_name": "Aarav Mehta",
        "holder_type": "individual",
        "account_relationship": "director_authorised_individual",
        "relationship": "director_authorised_individual",
    })
    s["documents"].append({
        "slot_id": f"bank_auth:{account['id']}",
        "doc_type": "AUTH_LETTER",
        "signature_ok": True,
    })

    result = _run_presubmit_rules(s, "PRESUBMIT-RELATED-TEST")
    finding_ids = {item["finding_id"] for item in result["review_items"]}

    assert f"BNK-003|{account['id']}|HOLDER_RELATED_REVIEW" in finding_ids
    assert result["review_required"] is True


def test_presubmit_engine_blocks_related_bank_holder_without_evidence(eng):
    from app.main import _run_presubmit_rules

    s = S.in_private_limited()
    account = s["bank_accounts"][0]
    account.update({
        "holder_name": "Aarav Mehta",
        "holder_type": "individual",
        "account_relationship": "director_authorised_individual",
        "relationship": "director_authorised_individual",
    })
    s["documents"] = [
        document for document in s["documents"]
        if document.get("slot_id") != f"bank_auth:{account['id']}"
    ]

    result = _run_presubmit_rules(s, "PRESUBMIT-MISSING-AUTH-TEST")
    finding_ids = {item["finding_id"] for item in result["blockers"]}

    assert f"BNK-003|{account['id']}|HOLDER_NEEDS_EVIDENCE" in finding_ids


def test_presubmit_engine_does_not_treat_review_as_blocker(eng):
    from app.main import _run_presubmit_rules

    s = S.in_private_limited()
    account = s["bank_accounts"][0]
    account.update({
        "holder_name": "Aarav Mehta",
        "holder_type": "individual",
        "account_relationship": "director_authorised_individual",
        "relationship": "director_authorised_individual",
    })
    s["documents"].append({
        "slot_id": f"bank_auth:{account['id']}",
        "doc_type": "AUTH_LETTER",
        "signature_ok": True,
    })

    result = _run_presubmit_rules(s, "PRESUBMIT-REVIEW-NOT-BLOCKED")
    assert not any(
        item["finding_id"] == f"BNK-003|{account['id']}|HOLDER_RELATED_REVIEW"
        for item in result["blockers"]
    )
    assert any(
        item["finding_id"] == f"BNK-003|{account['id']}|HOLDER_RELATED_REVIEW"
        for item in result["review_items"]
    )



def test_presubmit_endpoint_is_registered_only_once():
    from app.main import app

    matching_routes = [
        route
        for route in app.routes
        if getattr(route, "path", None)
        == "/api/vendor/applications/{application_ref}/presubmit"
        and "POST" in (getattr(route, "methods", set()) or set())
    ]
    assert len(matching_routes) == 1


def test_delete_document_endpoint_is_registered():
    from app.main import app

    matching_routes = [
        route for route in app.routes
        if getattr(route, "path", None)
        == "/api/vendor/applications/{application_ref}/documents/{slot_id}"
        and "DELETE" in (getattr(route, "methods", set()) or set())
    ]
    assert len(matching_routes) == 1


def test_delete_bank_authorisation_document_clears_evidence_reference(tmp_path, monkeypatch):
    from app import database, main

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.sqlite3")
    private_uploads = tmp_path / "private_uploads"
    private_uploads.mkdir()
    monkeypatch.setattr(main, "PRIVATE_UPLOADS", private_uploads)
    database.init_db()

    application_ref = "DELETE-TEST"
    slot_id = "bank_auth:acct-demo-1"
    stored_file = private_uploads / "authorisation.pdf"
    stored_file.write_bytes(b"synthetic test document")
    stamp = main.now()
    submission = {
        "documents": [{"slot_id": slot_id, "filename": "authorisation.pdf"}],
        "bank_accounts": [{
            "id": "acct-demo-1",
            "holder_name": "Aarav Mehta",
            "account_relationship": "director_authorised_individual",
            "ownership_evidence_ref": "synthetic-digest",
        }],
    }

    with database.connect() as db:
        db.execute(
            "INSERT INTO applications(application_ref,state,version,created_at,updated_at) VALUES(?,?,?,?,?)",
            (application_ref, "DRAFT", 0, stamp, stamp),
        )
        main.save_version(db, application_ref, 0, submission)
        db.execute(
            "INSERT INTO documents(application_ref,slot_id,original_filename,sha256,stored_path,status,created_at) VALUES(?,?,?,?,?,?,?)",
            (application_ref, slot_id, "authorisation.pdf", "synthetic-digest", str(stored_file), "RECEIVED", stamp),
        )

    result = main.delete_document(application_ref, slot_id)

    assert result["deleted"] is True
    assert not stored_file.exists()
    with database.connect() as db:
        updated = main.fetch_submission(db, application_ref)
        remaining = db.execute(
            "SELECT COUNT(*) FROM documents WHERE application_ref=? AND slot_id=?",
            (application_ref, slot_id),
        ).fetchone()[0]
    assert not any(doc.get("slot_id") == slot_id for doc in updated["documents"])
    assert "ownership_evidence_ref" not in updated["bank_accounts"][0]
    assert remaining == 0
