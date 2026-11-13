import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import database

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "reviewer.sqlite3")
    monkeypatch.setenv("VENDORFLOW_REVIEWER_SETUP_KEY", "test-reviewer-key")
    with TestClient(app) as test_client:
        yield test_client

def vendor_headers(client):
    r = client.post("/api/auth/register", json={"email":"supplier@example.test","full_name":"Synthetic Supplier","password":"SecurePass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def reviewer_headers(client):
    r = client.post("/api/auth/bootstrap-reviewer", json={"setup_key":"test-reviewer-key","email":"reviewer@example.test","full_name":"Demo Reviewer","password":"SecurePass123!","role":"reviewer"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}

def test_reviewer_can_view_queue_detail_comment_and_audit(client):
    vh = vendor_headers(client)
    rh = reviewer_headers(client)
    app_data = client.post("/api/vendor/applications", headers=vh, json={"submission":{"profile":{"legal_name":"Synthetic Example Private Limited"}}}).json()
    ref = app_data["application_ref"]
    queue = client.get("/api/internal/applications", headers=rh)
    assert queue.status_code == 200 and queue.json()[0]["application_ref"] == ref
    detail = client.get(f"/api/internal/applications/{ref}", headers=rh)
    assert detail.status_code == 200
    assert detail.json()["submission"]["profile"]["legal_name"] == "Synthetic Example Private Limited"
    comment = client.post(f"/api/internal/applications/{ref}/comments", headers=rh, json={"comment":"Please verify the uploaded evidence."})
    assert comment.status_code == 200
    audit = client.get(f"/api/internal/applications/{ref}/audit", headers=rh)
    assert audit.status_code == 200
    assert audit.json()["events"][0]["action"] == "COMMENT_ADDED"

def test_request_corrections_requires_reason_and_records_transition(client):
    vh = vendor_headers(client); rh = reviewer_headers(client)
    ref = client.post("/api/vendor/applications", headers=vh, json={"submission":{}}).json()["application_ref"]
    missing = client.post(f"/api/internal/applications/{ref}/actions", headers=rh, json={"action":"request_corrections","comment":""})
    assert missing.status_code == 422
    response = client.post(f"/api/internal/applications/{ref}/actions", headers=rh, json={"action":"request_corrections","comment":"Please upload clearer documents."})
    assert response.status_code == 200
    assert response.json()["state"] == "ACTION_REQUIRED"
    audit = client.get(f"/api/internal/applications/{ref}/audit", headers=rh).json()["events"]
    assert audit[0]["action"] == "REQUEST_CORRECTIONS"
    assert audit[0]["to_state"] == "ACTION_REQUIRED"

def test_approve_and_reject_are_final_and_vendor_cannot_access_reviewer_api(client):
    vh = vendor_headers(client); rh = reviewer_headers(client)
    ref = client.post("/api/vendor/applications", headers=vh, json={"submission":{}}).json()["application_ref"]
    forbidden = client.get("/api/internal/applications", headers=vh)
    assert forbidden.status_code == 403
    approved = client.post(f"/api/internal/applications/{ref}/actions", headers=rh, json={"action":"approve","comment":""})
    assert approved.status_code == 200 and approved.json()["state"] == "APPROVED"
    again = client.post(f"/api/internal/applications/{ref}/actions", headers=rh, json={"action":"reject","comment":"Changed mind"})
    assert again.status_code == 409

def test_reviewer_bootstrap_is_one_time(client):
    first = client.post("/api/auth/bootstrap-reviewer", json={"setup_key":"test-reviewer-key","email":"first-reviewer@example.test","full_name":"First Reviewer","password":"SecurePass123!","role":"reviewer"})
    assert first.status_code == 200, first.text
    second = client.post("/api/auth/bootstrap-reviewer", json={"setup_key":"test-reviewer-key","email":"second-reviewer@example.test","full_name":"Second Reviewer","password":"SecurePass123!","role":"reviewer"})
    assert second.status_code == 409


def test_security_headers_are_set(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
