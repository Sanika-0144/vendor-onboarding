import asyncio

from app.document_intelligence import rule_based_fields, analyse_document


def test_rule_based_extraction_finds_indian_identifiers():
    text = "PAN: ABCDE1234F\nGSTIN: 27ABCDE1234F1Z5\nIFSC: HDFC0001234"
    fields = rule_based_fields(text)
    assert fields["pan"] == ["ABCDE1234F"]
    assert fields["gstin"] == ["27ABCDE1234F1Z5"]
    assert fields["ifsc"] == ["HDFC0001234"]


def test_rule_based_extraction_does_not_invent_missing_fields():
    assert rule_based_fields("A document with no registration identifiers") == {}


def test_analyse_document_marks_unreadable_file_for_review(monkeypatch, tmp_path):
    monkeypatch.setattr("app.document_intelligence.extract_text", lambda _path: "")
    result = asyncio.run(analyse_document(tmp_path / "empty.png"))
    assert result["status"] == "NEEDS_REVIEW"
    assert result["extracted_fields"] == {}


def test_rule_based_extraction_finds_name_on_following_line():
    text = "VENDORFLOW OCR TEST SHEET\nPAN (SYNTHETIC)\nABCDE1234F\nNAME\nFAKUDA"
    fields = rule_based_fields(text)
    assert fields["pan"] == ["ABCDE1234F"]
    assert fields["legal_name"] == "FAKUDA"


def test_rule_based_extraction_finds_inline_legal_name():
    fields = rule_based_fields("PAN: ABCDE1234F\nLEGAL NAME: FAKUDA")
    assert fields["legal_name"] == "FAKUDA"


def test_rule_based_extraction_does_not_use_next_field_as_name():
    fields = rule_based_fields("NAME\nPAN: ABCDE1234F")
    assert "legal_name" not in fields


def test_rule_based_extraction_finds_bank_holder_on_following_line():
    fields = rule_based_fields("ACCOUNT HOLDER\nFAKUDA")
    assert fields["account_holder_name"] == "FAKUDA"
