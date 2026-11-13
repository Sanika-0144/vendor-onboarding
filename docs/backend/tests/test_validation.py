from vendor_core.validation import validate_submission


def base_submission():
    return {
        "profile": {"legal_name": "Acme Private Limited", "entity_type": "private_limited"},
        "tax_registrations": [
            {"type": "PAN", "value": "ABCDE1234F"},
            {"type": "GSTIN", "value": "27ABCDE1234F1Z5"},
            {"type": "CIN", "value": "U12345MH2020PTC123456"},
        ],
        "bank_accounts": [{"id": "acct-1", "holder_name": "Acme Pvt Ltd", "identifier": "HDFC0001234"}],
        "documents": [],
    }


def test_valid_identifier_formats_and_gstin_pan_consistency():
    result = validate_submission(base_submission())
    codes = {f["code"]: f for f in result["findings"]}
    assert codes["PAN_FORMAT_OK"]["status"] == "pass"
    assert codes["GSTIN_FORMAT_OK"]["status"] == "pass"
    assert codes["CIN_FORMAT_OK"]["status"] == "pass"
    assert codes["GSTIN_PAN_CONSISTENCY"]["status"] == "pass"


def test_gstin_with_different_pan_is_blocker():
    sub = base_submission()
    sub["tax_registrations"][1]["value"] = "27AAAAA1111A1Z5"
    result = validate_submission(sub)
    assert next(f for f in result["findings"] if f["code"] == "GSTIN_PAN_CONSISTENCY")["status"] == "mismatch"
    assert result["overall_status"] == "BLOCKED"


def test_invalid_ifsc_is_blocker():
    sub = base_submission()
    sub["bank_accounts"][0]["identifier"] = "BADIFSC"
    result = validate_submission(sub)
    assert next(f for f in result["findings"] if f["code"] == "IFSC_FORMAT_INVALID")["severity"] == "blocker"


def test_bank_holder_mismatch_without_evidence_is_blocker():
    sub = base_submission()
    sub["bank_accounts"][0]["holder_name"] = "Jane Doe"
    result = validate_submission(sub)
    finding = next(f for f in result["findings"] if f["code"].startswith("BANK_HOLDER_"))
    assert finding["status"] == "mismatch"


def test_bank_holder_mismatch_with_authorisation_evidence_routes_to_review():
    sub = base_submission()
    sub["bank_accounts"][0].update(holder_name="Jane Doe", ownership_evidence_ref="sha256-demo")
    result = validate_submission(sub)
    finding = next(f for f in result["findings"] if f["code"].startswith("BANK_HOLDER_"))
    assert finding["status"] == "needs_review"
    assert finding["severity"] == "review"


def test_duplicate_document_hash_across_slots_is_flagged():
    sub = base_submission()
    sub["documents"] = [
        {"slot_id": "pan_card", "sha256": "abc"},
        {"slot_id": "incorporation_cert", "sha256": "abc"},
    ]
    result = validate_submission(sub)
    assert any(f["code"] == "DUPLICATE_DOCUMENT" for f in result["findings"])


def test_missing_required_documents_are_flagged():
    result = validate_submission(base_submission(), [{"slot_id": "pan_card", "label": "PAN Card"}])
    assert any(f["code"] == "REQUIRED_DOCUMENT_MISSING" and f["field"] == "pan_card" for f in result["findings"])


def test_name_match_uses_conservative_comparison():
    sub = base_submission()
    sub["documents"] = [{"slot_id": "pan_card", "filename": "pan.pdf", "extracted_fields": {"legal_name": "Acme Pvt Ltd"}}]
    result = validate_submission(sub)
    name_finding = next(f for f in result["findings"] if f["code"].startswith("DOC_LEGAL_NAME_"))
    assert name_finding["status"] == "pass"


def test_fuzzy_name_similarity_does_not_auto_pass():
    sub = base_submission()
    sub["documents"] = [{"slot_id": "pan_card", "filename": "pan.pdf", "extracted_fields": {"legal_name": "Acme Privte Limited"}}]
    result = validate_submission(sub)
    name_finding = next(f for f in result["findings"] if f["code"].startswith("DOC_LEGAL_NAME_"))
    assert name_finding["status"] in ("needs_review", "mismatch")
