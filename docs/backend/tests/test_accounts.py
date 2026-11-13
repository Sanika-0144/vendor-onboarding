"""Account isolation integration tests. Uses a temporary SQLite database."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import database

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "accounts.sqlite3")
    with TestClient(app) as test_client:
        yield test_client

def register(client, email):
    response=client.post("/api/auth/register",json={"email":email,"full_name":"Synthetic Vendor","password":"SecurePass123!"})
    assert response.status_code==200, response.text
    return {"Authorization":"Bearer "+response.json()["access_token"]}

def test_vendor_can_register_login_and_create_multiple_applications(client):
    headers=register(client,"vendor1@example.test")
    first=client.post("/api/vendor/applications",headers=headers,json={"submission":{}})
    second=client.post("/api/vendor/applications",headers=headers,json={"submission":{}})
    assert first.status_code==200 and second.status_code==200
    assert first.json()["application_ref"] != second.json()["application_ref"]
    listed=client.get("/api/vendor/my-applications",headers=headers)
    assert listed.status_code==200 and len(listed.json())==2

def test_vendor_cannot_access_another_vendors_application(client):
    owner=register(client,"owner@example.test")
    other=register(client,"other@example.test")
    created=client.post("/api/vendor/applications",headers=owner,json={"submission":{}}).json()
    response=client.get(f"/api/vendor/applications/{created['application_ref']}",headers=other)
    assert response.status_code==404

def test_vendor_endpoints_require_authentication(client):
    assert client.get("/api/vendor/my-applications").status_code==401
    assert client.post("/api/vendor/applications",json={"submission":{}}).status_code==401

def test_duplicate_email_is_rejected(client):
    register(client,"same@example.test")
    response=client.post("/api/auth/register",json={"email":"same@example.test","full_name":"Second User","password":"SecurePass123!"})
    assert response.status_code==409

def test_document_upload_returns_extraction_candidates(client, tmp_path, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "PRIVATE_UPLOADS", tmp_path / "private_uploads")

    async def fake_analysis(_path):
        return {
            "status": "EXTRACTED",
            "extraction_method": "ocr_and_rules",
            "extracted_fields": {"pan": ["ABCDE1234F"]},
            "warnings": ["Verify against original document."],
            "text_length": 24,
            "ocr_text": "PAN ABCDE1234F synthetic",
        }

    monkeypatch.setattr(main, "analyse_document", fake_analysis)
    headers = register(client, "documents@example.test")
    application = client.post(
        "/api/vendor/applications", headers=headers, json={"submission": {}}
    ).json()
    response = client.post(
        f"/api/vendor/applications/{application['application_ref']}/documents/pan_card",
        headers=headers,
        files={"file": ("synthetic.png", b"\x89PNG\r\n\x1a\nsynthetic-image", "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["extraction_status"] == "EXTRACTED"
    assert response.json()["extracted_fields"]["pan"] == ["ABCDE1234F"]

    detail = client.get(
        f"/api/vendor/applications/{application['application_ref']}", headers=headers
    ).json()
    document = detail["submission"]["documents"][0]
    assert document["extracted_fields"]["pan"] == ["ABCDE1234F"]
    assert "ocr_text_enc" not in document
    assert "extraction" not in document


def test_validation_endpoint_runs_and_persists_result_for_owner(client):
    headers = register(client, "validation@example.test")
    application = client.post(
        "/api/vendor/applications", headers=headers,
        json={"submission": {"profile": {"legal_name": "Synthetic Acme Private Limited"}}},
    ).json()
    ref = application["application_ref"]
    response = client.post(f"/api/vendor/applications/{ref}/validate", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["application_ref"] == ref
    assert payload["overall_status"] in {"BLOCKED", "NEEDS_REVIEW", "INCOMPLETE", "READY_FOR_REVIEW"}
    assert "limitations" in payload
    latest = client.get(f"/api/vendor/applications/{ref}/validation", headers=headers)
    assert latest.status_code == 200
    assert latest.json()["result"]["overall_status"] == payload["overall_status"]


def test_validation_endpoint_respects_vendor_application_isolation(client):
    owner = register(client, "validation-owner@example.test")
    other = register(client, "validation-other@example.test")
    application = client.post("/api/vendor/applications", headers=owner, json={"submission": {}}).json()
    ref = application["application_ref"]
    assert client.post(f"/api/vendor/applications/{ref}/validate", headers=other).status_code == 404
    assert client.get(f"/api/vendor/applications/{ref}/validation", headers=other).status_code == 404

def test_upload_marks_document_unscanned_when_clamav_is_not_configured(client, tmp_path, monkeypatch):
    from app import main
    monkeypatch.delenv("CLAMAV_HOST", raising=False)
    monkeypatch.setattr(main, "PRIVATE_UPLOADS", tmp_path / "private_uploads")
    async def fake_analysis(_path):
        return {"status":"NEEDS_REVIEW", "extraction_method":"ocr", "extracted_fields":{}, "warnings":[], "text_length":0}
    monkeypatch.setattr(main, "analyse_document", fake_analysis)
    headers=register(client,"scan-status@example.test")
    application=client.post("/api/vendor/applications",headers=headers,json={"submission":{}}).json()
    response=client.post(f"/api/vendor/applications/{application['application_ref']}/documents/pan_card",headers=headers,files={"file":("synthetic.png",b"\x89PNG\r\n\x1a\nsynthetic-image","image/png")})
    assert response.status_code == 200, response.text
    assert response.json()["malware_scan_status"] == "UNSCANNED"
    assert any("UNSCANNED" in warning for warning in response.json()["warnings"])

def test_clamav_infected_file_is_rejected_before_storage(monkeypatch):
    from app import main
    monkeypatch.setenv("CLAMAV_HOST", "clamav.internal")
    monkeypatch.setattr(main, "_clamav_scan", lambda _content: "INFECTED")
    assert main._clamav_scan(b"synthetic") == "INFECTED"


def test_clamav_error_is_distinguished_from_unconfigured(monkeypatch):
    from app import main
    monkeypatch.delenv("CLAMAV_HOST", raising=False)
    assert main._clamav_scan(b"synthetic") == "UNSCANNED"
    monkeypatch.setenv("CLAMAV_HOST", "unreachable.invalid")
    monkeypatch.setattr(main, "socket", type("SocketStub", (), {"create_connection": staticmethod(lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline"))) }))
    assert main._clamav_scan(b"synthetic") == "ERROR"


def test_draft_save_endpoint_updates_application(client):
    headers = register(client, "draft-save@example.test")
    created = client.post(
        "/api/vendor/applications", headers=headers, json={"submission": {}}
    )
    assert created.status_code == 200, created.text
    ref = created.json()["application_ref"]
    response = client.put(
        f"/api/vendor/applications/{ref}/draft",
        headers=headers,
        json={"section": "profile", "data": {"legal_name": "Synthetic Acme Private Limited"}},
    )
    assert response.status_code == 200, response.text
    detail = client.get(f"/api/vendor/applications/{ref}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["submission"]["profile"]["legal_name"] == "Synthetic Acme Private Limited"


def test_missing_application_returns_clear_expired_draft_message(client):
    headers = register(client, "expired-draft@example.test")
    response = client.put(
        "/api/vendor/applications/VND-DOESNOTEXIST/draft",
        headers=headers,
        json={"section": "profile", "data": {"legal_name": "Synthetic Acme"}},
    )
    assert response.status_code == 410
    assert "no longer present" in response.json()["detail"]
