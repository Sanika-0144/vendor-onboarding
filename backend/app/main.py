from __future__ import annotations
import hashlib, json, os, uuid, re, secrets, socket, struct, time, threading
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .database import connect, init_db
from .security import get_fernet, protect, reveal
from .auth import current_user, create_user, issue_token, verify_password
from .document_intelligence import analyse_document
from vendor_core.validation import validate_submission

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_UPLOADS = Path(os.getenv("VENDORFLOW_UPLOAD_DIR", str(ROOT / "private_uploads"))).resolve()
FERNET = get_fernet()
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize persistent storage when the API process starts."""
    init_db()
    yield

app = FastAPI(title="Vendor Onboarding API", version="0.2.0", description="Vendor onboarding API with private OCR document extraction.", lifespan=lifespan)
_allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_allowed_origins.extend(x.strip() for x in os.getenv("FRONTEND_ORIGINS", "").split(",") if x.strip())
app.add_middleware(CORSMiddleware, allow_origins=_allowed_origins, allow_credentials=True, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

# Lightweight per-process throttling. For multi-instance deployments, use a shared Redis limiter.
_RATE_LOCK = threading.Lock()
_RATE_BUCKETS: dict[str, list[float]] = {}
def _rate_limited(key: str, limit: int, window: int) -> bool:
    now_ts = time.monotonic()
    with _RATE_LOCK:
        hits = [t for t in _RATE_BUCKETS.get(key, []) if now_ts - t < window]
        if len(hits) >= limit:
            _RATE_BUCKETS[key] = hits
            return True
        hits.append(now_ts); _RATE_BUCKETS[key] = hits
        if len(_RATE_BUCKETS) > 5000:
            for old_key in list(_RATE_BUCKETS)[:1000]: _RATE_BUCKETS.pop(old_key, None)
        return False

def _clamav_scan(content: bytes) -> str:
    host = os.getenv("CLAMAV_HOST", "").strip()
    if not host:
        return "UNSCANNED"
    port = int(os.getenv("CLAMAV_PORT", "3310"))
    timeout = float(os.getenv("CLAMAV_TIMEOUT_SECONDS", "8"))
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"zINSTREAM\0")
            for offset in range(0, len(content), 65536):
                chunk = content[offset:offset+65536]
                sock.sendall(struct.pack("!I", len(chunk)) + chunk)
            sock.sendall(struct.pack("!I", 0))
            response = sock.recv(4096).decode("utf-8", "replace")
        if " OK" in response: return "CLEAN"
        if " FOUND" in response: return "INFECTED"
        return "ERROR"
    except Exception:
        return "ERROR"

@app.middleware("http")
async def enforce_account_access(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    path=request.url.path
    if path in ("/api/auth/login", "/api/auth/register", "/api/auth/bootstrap-reviewer"):
        ip = request.client.host if request.client else "unknown"
        limit = 8 if path.endswith("/login") else (30 if path.endswith("/register") else 5)
        if _rate_limited(f"{ip}:{path}", limit, 60):
            return JSONResponse(status_code=429, content={"detail":"Too many attempts. Please wait a minute and try again."}, headers={"Retry-After":"60"})
    if path in ("/health", "/api/auth/register", "/api/auth/login", "/api/auth/bootstrap-reviewer") or path.startswith("/docs") or path.startswith("/openapi.json"):
        return await call_next(request)
    if path.startswith("/api/"):
        try:
            user=current_user(request)
            request.state.user=user
            if path.startswith("/api/internal/") and user["role"] not in ("reviewer","admin"):
                return JSONResponse(status_code=403,content={"detail":"Reviewer access required"})
            if path.startswith("/api/vendor/") and user["role"] != "vendor":
                return JSONResponse(status_code=403,content={"detail":"Vendor account required"})
            match=re.match(r"^/api/vendor/applications/([^/]+)",path)
            if match:
                app_ref=match.group(1)
                with connect() as db:
                    row=db.execute("SELECT owner_user_id FROM applications WHERE application_ref=?",(app_ref,)).fetchone()
                if row is None: return JSONResponse(status_code=404,content={"detail":"Application not found"})
                if row["owner_user_id"] != user["id"]:
                    return JSONResponse(status_code=404,content={"detail":"Application not found"})
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code,content={"detail":exc.detail})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if os.getenv("RENDER") or os.getenv("VENDORFLOW_ENV") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if os.getenv("RENDER") or os.getenv("VENDORFLOW_ENV") == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def now(): return datetime.now(timezone.utc).isoformat()
def ref(): return "VND-" + uuid.uuid4().hex[:8].upper()
def fetch_submission(db, application_ref):
    row = db.execute("SELECT submission_json FROM application_versions WHERE application_ref=? ORDER BY version DESC LIMIT 1", (application_ref,)).fetchone()
    if not row: raise HTTPException(404, "Application not found")
    return reveal(json.loads(row["submission_json"]), FERNET)
def save_version(db, application_ref, version, submission):
    db.execute("INSERT INTO application_versions(application_ref,version,submission_json,created_at) VALUES(?,?,?,?)", (application_ref, version, json.dumps(protect(submission, FERNET)), now()))

def merge(a, b):
    for k,v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict): merge(a[k],v)
        else: a[k]=v
    return a

def safe_status(result):
    # Engine's explicit vendor-safe serializer is the only source for vendor evaluation details.
    return result.to_dict(internal=False)

class CreateBody(BaseModel): submission: dict[str, Any] = Field(default_factory=dict)
class DraftBody(BaseModel): section: str | None = None; data: dict[str, Any] = Field(default_factory=dict)
class DeclarationBody(BaseModel): accepted: bool; version: str = "v1"; actor: str = "vendor"

@app.get("/health")
def health():
    try:
        with connect() as db: db.execute("SELECT 1").fetchone()
        return {"status":"ok", "database":"ok", "service":"vendor-onboarding-api"}
    except Exception:
        raise HTTPException(503, "Service storage is unavailable")

class RegisterBody(BaseModel): email: str; full_name: str; password: str
class LoginBody(BaseModel): email: str; password: str
class BootstrapReviewerBody(BaseModel): setup_key: str; email: str; full_name: str; password: str; role: str = "reviewer"

@app.post("/api/auth/register")
def register(body: RegisterBody):
    user=create_user(body.email,body.full_name,body.password,"vendor")
    return {"access_token":issue_token(user),"token_type":"bearer","user":user}

@app.post("/api/auth/login")
def login(body: LoginBody):
    with connect() as db: row=db.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE",(body.email.strip(),)).fetchone()
    if not row or not row["active"] or not verify_password(body.password,row["password_hash"]):
        raise HTTPException(401,"Email or password is incorrect")
    user={k:row[k] for k in ("id","email","full_name","role")}
    return {"access_token":issue_token(user),"token_type":"bearer","user":user}

@app.post("/api/auth/bootstrap-reviewer")
def bootstrap_reviewer(body: BootstrapReviewerBody):
    setup=os.getenv("VENDORFLOW_REVIEWER_SETUP_KEY","")
    if not setup or not secrets.compare_digest(setup,body.setup_key):
        raise HTTPException(403,"Reviewer setup is disabled or setup key is invalid")
    if body.role not in ("reviewer","admin"): raise HTTPException(422,"Role must be reviewer or admin")
    with connect() as db:
        existing = db.execute("SELECT COUNT(*) AS n FROM users WHERE role IN ('reviewer','admin')").fetchone()["n"]
    if existing:
        raise HTTPException(409, "Reviewer bootstrap has already been used. Create additional reviewers through an administrator workflow.")
    user=create_user(body.email,body.full_name,body.password,body.role)
    return {"access_token":issue_token(user),"token_type":"bearer","user":user}

@app.get("/api/auth/me")
def auth_me(request: Request): return request.state.user

@app.get("/api/vendor/my-applications")
def my_applications(request: Request):
    user=request.state.user
    with connect() as db: rows=db.execute("SELECT application_ref,state,decision_status,version,created_at,updated_at FROM applications WHERE owner_user_id=? ORDER BY updated_at DESC",(user["id"],)).fetchall()
    return [dict(row) for row in rows]

@app.post("/api/vendor/applications")
def create_application(body: CreateBody, request: Request):
    application_ref, stamp = ref(), now(); submission=body.submission; user=request.state.user
    with connect() as db:
        db.execute("INSERT INTO applications(application_ref,state,version,owner_user_id,created_at,updated_at) VALUES(?,?,?,?,?,?)", (application_ref,"DRAFT",0,user["id"],stamp,stamp))
        save_version(db, application_ref, 0, submission)
    return {"application_ref":application_ref,"state":"DRAFT","version":0,"created_at":stamp,"updated_at":stamp}

@app.put("/api/vendor/applications/{application_ref}/draft")
def update_draft(application_ref: str, body: DraftBody):
    with connect() as db:
        row=db.execute("SELECT state,version FROM applications WHERE application_ref=?",(application_ref,)).fetchone()
        if not row: raise HTTPException(404,"Application not found")
        if row["state"] != "DRAFT" and row["state"] != "ACTION_REQUIRED": raise HTTPException(409,"Application is not editable")
        submission=fetch_submission(db,application_ref)
        if body.section == "bank_account_updates":
            updates = body.data.get("accounts")

            if not isinstance(updates, list):
                raise HTTPException(
                    422,
                    "bank_account_updates data must contain an accounts list"
                )

            existing_accounts = submission.setdefault("bank_accounts", [])

            allowed_fields = {
                "identifier",
                "account_number",
                "account_relationship",
                "account_relationship_explanation",
                "holder_name",
            }

            valid_relationships = {
                "same_legal_entity",
                "sole_proprietor",
                "director_authorised_individual",
                "related_party",
                "joint",
                "other",
            }

            for update in updates:
                if not isinstance(update, dict) or not update.get("id"):
                    raise HTTPException(
                        422,
                        "Each bank account update must contain an account id"
                    )

                account = next(
                    (
                        item for item in existing_accounts
                        if item.get("id") == update["id"]
                    ),
                    None,
                )

                if account is None:
                    raise HTTPException(
                        404,
                        f"Bank account {update['id']} not found"
                    )

                if not any(field in update for field in allowed_fields):
                    raise HTTPException(
                        422,
                        "Provide at least one bank account correction or ownership update"
                    )

                relationship = update.get(
                    "account_relationship",
                    account.get("account_relationship", "same_legal_entity"),
                )

                if not isinstance(relationship, str) or relationship not in valid_relationships:
                    raise HTTPException(
                        422,
                        "Invalid account holder relationship"
                    )

                explanation = update.get(
                    "account_relationship_explanation",
                    account.get("account_relationship_explanation", ""),
                )

                if relationship != "same_legal_entity":
                    if not isinstance(explanation, str) or not explanation.strip():
                        raise HTTPException(
                            422,
                            "Please explain the declared bank account ownership relationship"
                        )

                for field in allowed_fields:
                    if field not in update:
                        continue

                    value = update[field]

                    if field == "account_relationship_explanation":
                        if not isinstance(value, str):
                            raise HTTPException(
                                422,
                                "account_relationship_explanation must be a string"
                            )
                        value = value.strip()
                        if relationship != "same_legal_entity" and not value:
                            raise HTTPException(
                                422,
                                "Please explain the declared bank account ownership relationship"
                            )
                    else:
                        if not isinstance(value, str) or not value.strip():
                            raise HTTPException(
                                422,
                                f"{field} must be a non-empty string"
                            )
                        value = value.strip()

                    if field == "account_relationship" and value not in valid_relationships:
                        raise HTTPException(
                            422,
                            "Invalid account holder relationship"
                        )

                    if field == "identifier":
                        value = value.upper()

                    if field == "holder_name":
                        account["holder_name"] = value
                        account["account_holder_name"] = value

                    elif field == "account_relationship":
                        # Preserve the vendor-facing declaration and also map it
                        # to the legacy field consumed by vendor_core.rules.bank_ownership.
                        relationship_map = {
                            "same_legal_entity": None,
                            "sole_proprietor": "sole_proprietor",
                            "director_authorised_individual": "director_authorised_individual",
                            "related_party": "related_party",
                            "joint": "joint",
                            "other": "other",
                        }
                        account["account_relationship"] = value
                        account["relationship"] = relationship_map[value]

                        if value in {
                            "sole_proprietor",
                            "director_authorised_individual",
                            "joint",
                        }:
                            account["holder_type"] = "individual"
                        elif value in {"same_legal_entity", "related_party"}:
                            account.setdefault("holder_type", "business")

                    else:
                        account[field] = value

        elif body.section == "bank_accounts":
            accounts = body.data.get("accounts")
            if not isinstance(accounts, list):
                raise HTTPException(422, "bank_accounts data must contain an accounts list")
            submission["bank_accounts"] = accounts
        elif body.section == "tax_registration_updates":
            updates = body.data.get("registrations")

            if not isinstance(updates, list):
                raise HTTPException(
                    422,
                    "tax_registration_updates data must contain a registrations list"
                )

            existing_registrations = submission.setdefault(
                "tax_registrations", []
            )

            for update in updates:
                if not isinstance(update, dict) or not update.get("type"):
                    raise HTTPException(
                        422,
                        "Each tax registration update must contain a type"
                    )

                registration_type = update["type"]

                existing = next(
                    (
                        item for item in existing_registrations
                        if item.get("type") == registration_type
                    ),
                    None
                )

                if existing:
                    existing.update(update)
                else:
                    existing_registrations.append(update)

                # A vendor declaring that GST registration does not apply
                # should not retain an old GSTIN value.
                if (
                    registration_type == "GSTIN"
                    and update.get("status") == "not_registered"
                ):
                    target = next(
                        item for item in existing_registrations
                        if item.get("type") == "GSTIN"
                    )
                    target.pop("value", None)
        elif body.section == "tax_registrations":
            registrations = body.data.get("registrations")
            if not isinstance(registrations, list):
                raise HTTPException(422, "tax_registrations data must contain a registrations list")
            submission["tax_registrations"] = registrations
        elif body.section:
            submission[body.section] = merge(
                submission.get(body.section, {})
                if isinstance(submission.get(body.section), dict) else {},
                body.data
            )
        else:
            submission = merge(submission, body.data)

        version=row["version"]
        # Replace draft snapshot at the same version; submitted versions are immutable.
        db.execute("UPDATE application_versions SET submission_json=?,created_at=? WHERE application_ref=? AND version=?",(json.dumps(protect(submission,FERNET)),now(),application_ref,version))
        db.execute("UPDATE applications SET updated_at=? WHERE application_ref=?",(now(),application_ref))
    return {"application_ref":application_ref,"state":row["state"],"version":version,"saved":True}

@app.get("/api/vendor/applications/{application_ref}")
def get_application(application_ref: str):
    with connect() as db:
        row=db.execute("SELECT * FROM applications WHERE application_ref=?",(application_ref,)).fetchone()
        if not row: raise HTTPException(404,"Application not found")
        submission=fetch_submission(db,application_ref)
    # Vendor can see their own submitted fields, but tax and bank values are masked in readback.
    for tax in submission.get("tax_registrations",[]):
        if tax.get("value"): tax["value"]="••••"+str(tax["value"])[-4:]
    for bank in submission.get("bank_accounts",[]):
        if isinstance(bank, dict) and bank.get("account_number"):
            bank["account_number"] = "••••" + str(bank["account_number"])[-4:]
    # Do not return extracted document contents or internal adapter payloads to vendor clients.
    for document in submission.get("documents",[]):
        document.pop("extraction", None)
        document.pop("malware_scan", None)
        encrypted_fields = document.pop("extracted_fields_enc", None)
        if encrypted_fields:
            try:
                document["extracted_fields"] = json.loads(FERNET.decrypt(encrypted_fields.encode()).decode())
            except Exception:
                document["extracted_fields"] = {}
        document.pop("ocr_text_enc", None)
    return {"application_ref":row["application_ref"],"state":row["state"],"decision_status":row["decision_status"],"version":row["version"],"submission":submission}

@app.get("/api/vendor/applications/{application_ref}/requirements")
def requirements(application_ref: str):
    from vendor_core.applicability import load_config, VendorContext, resolve_applicability, resolve_slots
    with connect() as db: sub=fetch_submission(db,application_ref)
    cfg=load_config(); ctx=VendorContext.from_submission(sub,cfg.policy)
    return {"slots":[s.to_dict() for s in resolve_slots(cfg,ctx,sub)],"applicability":[{"rule_id":a.rule_id,"applicability":a.applicability.value,"reason":a.reason} for a in resolve_applicability(cfg,ctx,sub)]}

@app.post("/api/vendor/applications/{application_ref}/documents/{slot_id}")
async def upload_document(application_ref: str, slot_id: str, file: UploadFile = File(...)):
    allowed={".pdf":"application/pdf",".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png"}
    suffix=Path(file.filename or "").suffix.lower()
    if suffix not in allowed: raise HTTPException(415,"Only PDF, JPG, JPEG and PNG files are accepted")
    content=await file.read(10*1024*1024+1)
    if len(content)>10*1024*1024: raise HTTPException(413,"Maximum upload size is 10 MB")
    signatures={".pdf":content.startswith(b"%PDF-"),".jpg":content.startswith(b"\xff\xd8\xff"),".jpeg":content.startswith(b"\xff\xd8\xff"),".png":content.startswith(b"\x89PNG\r\n\x1a\n")}
    if not signatures[suffix]: raise HTTPException(415,"File content does not match its extension")
    scan_status = _clamav_scan(content)
    if scan_status == "INFECTED": raise HTTPException(422, "The uploaded file was flagged by the malware scanner and was rejected")
    if scan_status == "ERROR": raise HTTPException(503, "Malware scanning is configured but unavailable. The file was not accepted; please retry later.")
    with connect() as db:
        sub=fetch_submission(db,application_ref)
        row=db.execute("SELECT state FROM applications WHERE application_ref=?",(application_ref,)).fetchone()
        if not row: raise HTTPException(404,"Application not found")
        if row["state"] not in ("DRAFT","ACTION_REQUIRED"): raise HTTPException(409,"Application is not accepting documents")
        PRIVATE_UPLOADS.mkdir(parents=True,exist_ok=True)
        try: PRIVATE_UPLOADS.chmod(0o700)
        except OSError: pass
        digest=hashlib.sha256(content).hexdigest(); target=PRIVATE_UPLOADS/f"{application_ref}_{uuid.uuid4().hex}{suffix}"
        target.write_bytes(content)
        try: target.chmod(0o600)
        except OSError: pass
        doc={"slot_id":slot_id,"doc_type":"UNKNOWN","filename":Path(file.filename or "upload").name,"size_bytes":len(content),"signature_ok":True,"sha256":digest,"upload_attempts":1,"extraction_status":"PROCESSING","malware_scan":{"status":scan_status,"scanned_at":now() if scan_status == "CLEAN" else None}}
        sub.setdefault("documents",[])
        previous=next((d for d in sub["documents"] if d.get("slot_id")==slot_id),None)
        if previous:
            doc["upload_attempts"]=int(previous.get("upload_attempts",1))+1
            sub["documents"].remove(previous)

        # Associate an authorisation letter with the bank account identified
        # by the dynamic slot ID, e.g. bank_auth:acct-demo-1.
        if slot_id.startswith("bank_auth:"):
            account_id = slot_id.split(":", 1)[1]
            account = next(
                (
                    item for item in sub.get("bank_accounts", [])
                    if item.get("id") == account_id
                ),
                None,
            )

            if account is None:
                raise HTTPException(404, "Bank account not found")

            doc["doc_type"] = "AUTH_LETTER"
            account["ownership_evidence_ref"] = digest

        # OCR is local to this service. AI extraction is enabled only when an
        # OpenAI-compatible provider is explicitly configured in environment variables.
        try:
            analysis = await analyse_document(target)
            doc["extraction_status"] = analysis.get("status", "NEEDS_REVIEW")
            doc["extraction_method"] = analysis.get("extraction_method", "ocr")
            extracted_fields = analysis.get("extracted_fields", {})
            doc["extracted_fields_enc"] = FERNET.encrypt(json.dumps(extracted_fields).encode()).decode()
            doc["extraction_warnings"] = analysis.get("warnings", [])
            raw_ocr_text = analysis.get("ocr_text", "")
            doc["ocr_text_enc"] = FERNET.encrypt(raw_ocr_text.encode()).decode() if raw_ocr_text else ""
            doc["ocr_text_length"] = analysis.get("text_length", len(raw_ocr_text))
        except Exception as exc:
            doc["extraction_status"] = "FAILED"
            doc["extraction_method"] = "unavailable"
            doc["extracted_fields_enc"] = FERNET.encrypt(b"{}").decode()
            doc["extraction_warnings"] = ["OCR could not process this file. Check that it is readable and upload a clearer copy."]
        sub["documents"].append(doc)
        version=db.execute("SELECT version FROM applications WHERE application_ref=?",(application_ref,)).fetchone()["version"]
        db.execute("UPDATE application_versions SET submission_json=? WHERE application_ref=? AND version=?",(json.dumps(protect(sub,FERNET)),application_ref,version))
        db.execute("INSERT INTO documents(application_ref,slot_id,original_filename,sha256,stored_path,status,created_at) VALUES(?,?,?,?,?,?,?)",(application_ref,slot_id,Path(file.filename or "upload").name,digest,str(target),"RECEIVED",now()))
    warnings = list(doc.get("extraction_warnings", []))
    if scan_status == "UNSCANNED": warnings.append("Malware scanning is not configured. This file is marked UNSCANNED; configure ClamAV before production use.")
    return {"slot_id":slot_id,"filename":Path(file.filename or "upload").name,"sha256":digest,"status":"RECEIVED","malware_scan_status":scan_status,"extraction_status":doc.get("extraction_status", "NEEDS_REVIEW"),"extraction_method":doc.get("extraction_method", "ocr"),"extracted_fields":(analysis.get("extracted_fields", {}) if "analysis" in locals() else {}),"warnings":warnings,"note":"OCR candidates are not verification or approval. Review extracted values against the original document."}

# Legacy completeness-only presubmit route removed. The rules-engine-backed
# presubmit route below is the single registered endpoint.

@app.post("/api/vendor/applications/{application_ref}/submit")
def submit(application_ref: str, body: DeclarationBody, background_tasks: BackgroundTasks):
    if not body.accepted: raise HTTPException(400,"Declaration must be accepted")
    check=presubmit(application_ref)
    if not check["ready"]: raise HTTPException(422,detail=check)
    with connect() as db:
        row=db.execute("SELECT version,state FROM applications WHERE application_ref=?",(application_ref,)).fetchone()
        if not row: raise HTTPException(404,"Application not found")
        if row["state"] not in ("DRAFT","ACTION_REQUIRED"): raise HTTPException(409,"Application cannot be submitted in its current state")
        sub=fetch_submission(db,application_ref); version=row["version"]+1
        sub["declaration"]={"accepted":True,"version":body.version,"actor":body.actor,"timestamp":now()}
        save_version(db,application_ref,version,sub)
        db.execute("UPDATE applications SET state='PROCESSING',version=?,updated_at=? WHERE application_ref=?",(version,now(),application_ref))
    background_tasks.add_task(run_evaluation,application_ref,version,sub)
    return {"application_ref":application_ref,"state":"PROCESSING","version":version,"message":"Application submitted for deterministic evaluation"}

def run_evaluation(application_ref, version, sub):
    from vendor_core.engine import OnboardingEngine
    events=[]
    def on_event(event):
        events.append(event)
        with connect() as db: db.execute("INSERT INTO events(application_ref,version,seq,event_json,created_at) VALUES(?,?,?,?,?)",(application_ref,version,event.get("seq",len(events)),json.dumps(event),now()))
    result=OnboardingEngine().evaluate(sub,application_ref=application_ref,version=version,on_event=on_event,step_delay=0.15)
    result_json=json.dumps(result.to_dict(internal=True),default=lambda o:o.value if hasattr(o,"value") else str(o))
    with connect() as db:
        db.execute("INSERT INTO evaluations(application_ref,version,result_json,created_at) VALUES(?,?,?,?)",(application_ref,version,result_json,now()))
        db.execute("UPDATE applications SET state=?,decision_status=?,updated_at=? WHERE application_ref=?",(result.decision.application_state,result.decision.status.value,now(),application_ref))

@app.get("/api/vendor/applications/{application_ref}/status")
def vendor_status(application_ref: str):
    with connect() as db:
        row=db.execute("SELECT state,version,decision_status FROM applications WHERE application_ref=?",(application_ref,)).fetchone()
        if not row: raise HTTPException(404,"Application not found")
        ev=db.execute("SELECT result_json FROM evaluations WHERE application_ref=? ORDER BY version DESC LIMIT 1",(application_ref,)).fetchone()
    if not ev: return {"application_ref":application_ref,"state":row["state"],"version":row["version"],"status":"PROCESSING","tracking":[],"document_statuses":{},"required_actions":[],"message":{"items":[]}}
    result=json.loads(ev["result_json"])
    # Rebuild a vendor-safe response from explicitly filtered fields, not internal findings.
    from vendor_core.communication import vendor_tracking
    from vendor_core.models import DecisionStatus
    decision_status=DecisionStatus(result["decision"]["status"])
    state=result["decision"]["application_state"]
    return {"application_ref":application_ref,"version":result["version"],"application_state":state,"status":decision_status.value,"tracking":vendor_tracking(state,decision_status),"document_statuses":result.get("document_statuses",{}),"required_actions":result.get("vendor_message",{}).get("items",[]),"message":result.get("vendor_message",{})}

# Reviewer workflow: authenticated reviewer/admin accounts only.
def role_level(role):
    if role not in ("reviewer", "admin"):
        raise HTTPException(403, "Reviewer access required")
    return 2 if role == "reviewer" else 3

class ReviewerActionBody(BaseModel):
    action: str
    comment: str = ""

class ReviewerCommentBody(BaseModel):
    comment: str = Field(min_length=1, max_length=5000)

@app.get("/api/internal/applications")
def internal_list(request: Request):
    role_level(request.state.user["role"])
    with connect() as db:
        rows = db.execute(
            """SELECT a.application_ref,a.state,a.decision_status,a.version,a.created_at,a.updated_at,
               (SELECT COUNT(*) FROM reviewer_comments c WHERE c.application_ref=a.application_ref) AS comment_count
               FROM applications a ORDER BY CASE a.state WHEN 'PROCESSING' THEN 0 WHEN 'ACTION_REQUIRED' THEN 1 WHEN 'DRAFT' THEN 2 ELSE 3 END, a.updated_at DESC"""
        ).fetchall()
    return [dict(row) for row in rows]

@app.get("/api/internal/applications/{application_ref}")
def internal_detail(application_ref: str, request: Request):
    role_level(request.state.user["role"])
    with connect() as db:
        row = db.execute("SELECT * FROM applications WHERE application_ref=?", (application_ref,)).fetchone()
        if not row: raise HTTPException(404, "Application not found")
        ev = db.execute("SELECT result_json FROM evaluations WHERE application_ref=? ORDER BY version DESC LIMIT 1", (application_ref,)).fetchone()
        validation = db.execute("SELECT version,result_json,created_at FROM validation_runs WHERE application_ref=? ORDER BY id DESC LIMIT 1", (application_ref,)).fetchone()
        comments = db.execute("SELECT id,author_name,comment,action,created_at FROM reviewer_comments WHERE application_ref=? ORDER BY id DESC", (application_ref,)).fetchall()
        submission = fetch_submission(db, application_ref)
    evaluation = json.loads(ev["result_json"]) if ev else None
    return {
        "application": dict(row),
        "submission": mask_submission(submission),
        "evaluation": evaluation,
        "validation": ({"version": validation["version"], "result": json.loads(validation["result_json"]), "created_at": validation["created_at"]} if validation else None),
        "comments": [dict(c) for c in comments],
    }

def mask_submission(sub):
    sub=json.loads(json.dumps(sub))
    for group,key in [("tax_registrations","value"),("bank_accounts","account_number")]:
        for item in sub.get(group,[]):
            if item.get(key): item[key]="••••"+str(item[key])[-4:]
    return sub

@app.post("/api/internal/applications/{application_ref}/actions")
def reviewer_action(application_ref: str, body: ReviewerActionBody, request: Request):
    user = request.state.user
    role_level(user["role"])
    action = body.action.strip().lower()
    if action not in ("approve", "reject", "request_corrections"):
        raise HTTPException(422, "Action must be approve, reject or request_corrections")
    note = body.comment.strip()
    if action in ("reject", "request_corrections") and not note:
        raise HTTPException(422, "A reason is required for rejection or correction request")
    stamp = now()
    transitions = {"approve": ("APPROVED", "APPROVED"), "reject": ("REJECTED", "REJECTED"), "request_corrections": ("ACTION_REQUIRED", "PENDING")}
    to_state, decision = transitions[action]
    with connect() as db:
        row = db.execute("SELECT state FROM applications WHERE application_ref=?", (application_ref,)).fetchone()
        if not row: raise HTTPException(404, "Application not found")
        if row["state"] in ("APPROVED", "REJECTED"):
            raise HTTPException(409, "This application already has a final reviewer decision")
        from_state = row["state"]
        db.execute("UPDATE applications SET state=?,decision_status=?,updated_at=? WHERE application_ref=?", (to_state, decision, stamp, application_ref))
        if note:
            db.execute("INSERT INTO reviewer_comments(application_ref,author_user_id,author_name,comment,action,created_at) VALUES(?,?,?,?,?,?)", (application_ref,user["id"],user["full_name"],note,action.upper(),stamp))
        db.execute("INSERT INTO audit_logs(application_ref,actor_user_id,actor_name,actor_role,action,from_state,to_state,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (application_ref,user["id"],user["full_name"],user["role"],action.upper(),from_state,to_state,note,stamp))
    return {"application_ref":application_ref,"action":action,"state":to_state,"decision_status":decision,"updated_at":stamp}

@app.post("/api/internal/applications/{application_ref}/comments")
def add_reviewer_comment(application_ref: str, body: ReviewerCommentBody, request: Request):
    user=request.state.user; role_level(user["role"]); stamp=now(); comment=body.comment.strip()
    if not comment: raise HTTPException(422, "Comment cannot be blank")
    with connect() as db:
        if not db.execute("SELECT 1 FROM applications WHERE application_ref=?",(application_ref,)).fetchone(): raise HTTPException(404,"Application not found")
        cur=db.execute("INSERT INTO reviewer_comments(application_ref,author_user_id,author_name,comment,action,created_at) VALUES(?,?,?,?,?,?)",(application_ref,user["id"],user["full_name"],comment,"COMMENT",stamp))
        db.execute("INSERT INTO audit_logs(application_ref,actor_user_id,actor_name,actor_role,action,note,created_at) VALUES(?,?,?,?,?,?,?)",(application_ref,user["id"],user["full_name"],user["role"],"COMMENT_ADDED",comment,stamp))
        comment_id=cur.lastrowid
    return {"id":comment_id,"author_name":user["full_name"],"comment":comment,"action":"COMMENT","created_at":stamp}

@app.get("/api/internal/applications/{application_ref}/audit")
def internal_audit(application_ref: str, request: Request):
    role_level(request.state.user["role"])
    with connect() as db:
        if not db.execute("SELECT 1 FROM applications WHERE application_ref=?",(application_ref,)).fetchone(): raise HTTPException(404,"Application not found")
        rows=db.execute("SELECT id,actor_name,actor_role,action,from_state,to_state,note,created_at FROM audit_logs WHERE application_ref=? ORDER BY id DESC",(application_ref,)).fetchall()
    return {"application_ref":application_ref,"events":[dict(row) for row in rows]}

def _run_presubmit_rules(submission: dict[str, Any], application_ref: str) -> dict[str, Any]:
    """
    Run the same deterministic rules engine used after submission, without
    persisting an evaluation or changing the application state.

    FIXABLE findings block submission. ESCALATE findings are shown as human
    review items and may proceed to reviewer assessment.
    """
    from vendor_core.engine import OnboardingEngine

    result = OnboardingEngine().evaluate(
        submission,
        application_ref=application_ref,
        version=1,
        step_delay=0,
    )
    vendor_result = safe_status(result)
    actions = vendor_result.get("required_actions", [])

    blockers = [
        {
            "finding_id": item.get("finding_id"),
            "message": item.get("message", ""),
            "action": item.get("action", ""),
        }
        for item in actions
        if item.get("severity") in ("FIXABLE", "BLOCKER")
    ]
    review_items = [
        {
            "finding_id": item.get("finding_id"),
            "message": item.get("message", ""),
            "action": item.get("action", ""),
        }
        for item in actions
        if item.get("severity") == "ESCALATE"
    ]

    # Live sanctions screening is not connected in this demo. The engine
    # fails closed for that check; explain the limitation without exposing
    # internal risk-rule details or blocking submission for reviewer handling.
    integration_incomplete = any(
        str(reason.get("type", "")).endswith(("_NOT_RUN", "_ERROR", "_MISSING"))
        for reason in result.decision.reasons
    )

    return {
        "blockers": blockers,
        "review_items": review_items,
        "review_required": bool(
            review_items or result.decision.needs_human_review or integration_incomplete
        ),
        "integration_incomplete": integration_incomplete,
    }


@app.delete("/api/vendor/applications/{application_ref}/documents/{slot_id}")
def delete_document(application_ref: str, slot_id: str):
    """Remove a document from an editable application and clear linked evidence."""
    with connect() as db:
        row = db.execute(
            "SELECT state, version FROM applications WHERE application_ref=?",
            (application_ref,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Application not found")
        if row["state"] not in ("DRAFT", "ACTION_REQUIRED"):
            raise HTTPException(409, "Documents can only be removed from editable applications")

        submission = fetch_submission(db, application_ref)
        existing = [
            item for item in submission.get("documents", [])
            if item.get("slot_id") == slot_id
        ]
        if not existing:
            raise HTTPException(404, "No document is uploaded for this slot")

        records = db.execute(
            "SELECT stored_path FROM documents WHERE application_ref=? AND slot_id=?",
            (application_ref, slot_id),
        ).fetchall()
        upload_root = PRIVATE_UPLOADS.resolve()
        for record in records:
            stored = Path(record["stored_path"]).resolve()
            if stored != upload_root and upload_root in stored.parents:
                try:
                    stored.unlink(missing_ok=True)
                except OSError:
                    pass

        submission["documents"] = [
            item for item in submission.get("documents", [])
            if item.get("slot_id") != slot_id
        ]

        # Clear the evidence pointer used by the bank-ownership rule.
        if slot_id.startswith("bank_auth:"):
            account_id = slot_id.split(":", 1)[1]
            for account in submission.get("bank_accounts", []):
                if account.get("id") == account_id:
                    account.pop("ownership_evidence_ref", None)

        db.execute(
            "UPDATE application_versions SET submission_json=?, created_at=? "
            "WHERE application_ref=? AND version=?",
            (json.dumps(protect(submission, FERNET)), now(), application_ref, row["version"]),
        )
        db.execute(
            "DELETE FROM documents WHERE application_ref=? AND slot_id=?",
            (application_ref, slot_id),
        )
        db.execute(
            "UPDATE applications SET updated_at=? WHERE application_ref=?",
            (now(), application_ref),
        )

    return {"application_ref": application_ref, "slot_id": slot_id, "deleted": True}


@app.post("/api/vendor/applications/{application_ref}/validate")
def run_validation(application_ref: str):
    """Run internal consistency checks; this is not external registry verification."""
    with connect() as db:
        row = db.execute(
            "SELECT version FROM applications WHERE application_ref=?", (application_ref,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Application not found")
        submission = fetch_submission(db, application_ref)
        # Decrypt OCR candidates only inside the backend validation process.
        for document in submission.get("documents", []):
            encrypted = document.pop("extracted_fields_enc", None)
            if encrypted:
                try:
                    document["extracted_fields"] = json.loads(FERNET.decrypt(encrypted.encode()).decode())
                except Exception:
                    document["extracted_fields"] = {}
        from vendor_core.applicability import load_config, VendorContext, resolve_slots
        cfg = load_config()
        slots = resolve_slots(cfg, VendorContext.from_submission(submission, cfg.policy), submission)
        required = [{"slot_id": slot.slot_id, "label": slot.label}
                    for slot in slots if slot.requirement == "REQUIRED"]
        result = validate_submission(submission, required)
        stamp = now()
        db.execute(
            "INSERT INTO validation_runs(application_ref,version,result_json,created_at) VALUES(?,?,?,?)",
            (application_ref, row["version"], json.dumps(result), stamp),
        )
    return {"application_ref": application_ref, "version": row["version"],
            "created_at": stamp, **result}


@app.get("/api/vendor/applications/{application_ref}/validation")
def get_validation(application_ref: str):
    with connect() as db:
        row = db.execute(
            "SELECT version,result_json,created_at FROM validation_runs "
            "WHERE application_ref=? ORDER BY id DESC LIMIT 1", (application_ref,)
        ).fetchone()
    if not row:
        return {"application_ref": application_ref, "result": None}
    return {"application_ref": application_ref, "version": row["version"],
            "created_at": row["created_at"], "result": json.loads(row["result_json"])}


@app.post("/api/vendor/applications/{application_ref}/presubmit")
def presubmit(application_ref: str):
    with connect() as db:
        sub = fetch_submission(db, application_ref)

    p = sub.get("profile", {})
    blockers: list[Any] = []
    warnings: list[str] = []

    for key, label in [
        ("country", "Registration country"),
        ("legal_name", "Legal business name"),
        ("entity_type", "Legal entity type"),
        ("categories", "Vendor category"),
        ("contact_name", "Primary contact name"),
        ("contact_email", "Business email"),
    ]:
        if not p.get(key):
            blockers.append({
                "message": f"{label} is required",
                "action": "Complete the company profile.",
            })

    if not p.get("registered_address"):
        blockers.append({
            "message": "Registered address is required",
            "action": "Complete the registered address.",
        })
    if not p.get("operating_countries"):
        warnings.append("Operating countries have not been provided")
    if not sub.get("tax_registrations"):
        warnings.append("No tax registration details have been added")
    if not sub.get("bank_accounts"):
        blockers.append({
            "message": "At least one bank account is required",
            "action": "Add a bank account.",
        })
    if sub.get("bank_accounts") and sum(
        bool(b.get("is_primary")) for b in sub["bank_accounts"]
    ) != 1:
        blockers.append({
            "message": "Exactly one bank account must be primary",
            "action": "Select exactly one primary bank account.",
        })

    from vendor_core.applicability import load_config, VendorContext, resolve_slots

    cfg = load_config()
    slots = resolve_slots(cfg, VendorContext.from_submission(sub, cfg.policy), sub)
    present = {d.get("slot_id") for d in sub.get("documents", [])}
    for slot in slots:
        if slot.requirement == "REQUIRED" and slot.slot_id not in present:
            blockers.append({
                "message": f"Required document missing: {slot.label}",
                "action": "Upload the required document.",
            })

    engine_check = _run_presubmit_rules(sub, application_ref)
    blockers.extend(engine_check["blockers"])

    if engine_check["integration_incomplete"]:
        warnings.append(
            "Some external verification services are not connected in this demo. "
            "Those checks will need reviewer attention after submission."
        )

    review_items = engine_check["review_items"]
    review_required = engine_check["review_required"]

    return {
        "ready": len(blockers) == 0,
        "validation_status": (
            "BLOCKED" if blockers else
            "REVIEW_REQUIRED" if review_required else
            "READY"
        ),
        "blockers": blockers,
        "warnings": warnings,
        "review_required": review_required,
        "review_items": review_items,
    }


