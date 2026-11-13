from __future__ import annotations
import hashlib, json, os, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import FastAPI, HTTPException, UploadFile, File, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .database import connect, init_db
from .security import get_fernet, protect, reveal

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_UPLOADS = ROOT / "private_uploads"
FERNET = get_fernet()
app = FastAPI(title="Vendor Onboarding API", version="0.1.0", description="Local demo API. Demo role headers are NOT production authentication.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup(): init_db()

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
def health(): return {"status":"ok", "service":"vendor-onboarding-api"}

@app.post("/api/vendor/applications")
def create_application(body: CreateBody):
    application_ref, stamp = ref(), now()
    submission = body.submission
    with connect() as db:
        db.execute("INSERT INTO applications(application_ref,state,version,created_at,updated_at) VALUES(?,?,?,?,?)", (application_ref,"DRAFT",0,stamp,stamp))
        save_version(db, application_ref, 0, submission)
    return {"application_ref":application_ref,"state":"DRAFT","version":0,"created_at":stamp,"updated_at":stamp}

@app.put("/api/vendor/applications/{application_ref}/draft")
def update_draft(application_ref: str, body: DraftBody):
    with connect() as db:
        row=db.execute("SELECT state,version FROM applications WHERE application_ref=?",(application_ref,)).fetchone()
        if not row: raise HTTPException(404,"Application not found")
        if row["state"] != "DRAFT" and row["state"] != "ACTION_REQUIRED": raise HTTPException(409,"Application is not editable")
        submission=fetch_submission(db,application_ref)
        if body.section:
            submission[body.section]=merge(submission.get(body.section,{}) if isinstance(submission.get(body.section),dict) else {},body.data)
        else: submission=merge(submission,body.data)
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
    with connect() as db:
        sub=fetch_submission(db,application_ref)
        row=db.execute("SELECT state FROM applications WHERE application_ref=?",(application_ref,)).fetchone()
        if not row: raise HTTPException(404,"Application not found")
        if row["state"] not in ("DRAFT","ACTION_REQUIRED"): raise HTTPException(409,"Application is not accepting documents")
        PRIVATE_UPLOADS.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256(content).hexdigest(); target=PRIVATE_UPLOADS/f"{application_ref}_{uuid.uuid4().hex}{suffix}"
        target.write_bytes(content)
        doc={"slot_id":slot_id,"doc_type":"UNKNOWN","filename":Path(file.filename or "upload").name,"size_bytes":len(content),"signature_ok":True,"sha256":digest,"upload_attempts":1}
        sub.setdefault("documents",[])
        previous=next((d for d in sub["documents"] if d.get("slot_id")==slot_id),None)
        if previous: doc["upload_attempts"]=int(previous.get("upload_attempts",1))+1; sub["documents"].remove(previous)
        sub["documents"].append(doc)
        version=db.execute("SELECT version FROM applications WHERE application_ref=?",(application_ref,)).fetchone()["version"]
        db.execute("UPDATE application_versions SET submission_json=? WHERE application_ref=? AND version=?",(json.dumps(protect(sub,FERNET)),application_ref,version))
        db.execute("INSERT INTO documents(application_ref,slot_id,original_filename,sha256,stored_path,status,created_at) VALUES(?,?,?,?,?,?,?)",(application_ref,slot_id,Path(file.filename or "upload").name,digest,str(target),"RECEIVED",now()))
    return {"slot_id":slot_id,"filename":Path(file.filename or "upload").name,"sha256":digest,"status":"RECEIVED","synthetic":True,"note":"File stored privately. No live malware scan or OCR is connected."}

@app.post("/api/vendor/applications/{application_ref}/presubmit")
def presubmit(application_ref: str):
    with connect() as db: sub=fetch_submission(db,application_ref)
    p=sub.get("profile",{}); blockers=[]; warnings=[]
    for key,label in [("country","Registration country"),("legal_name","Legal business name"),("entity_type","Legal entity type"),("categories","Vendor category"),("contact_name","Primary contact name"),("contact_email","Business email")]:
        if not p.get(key): blockers.append(f"{label} is required")
    if not p.get("registered_address"): blockers.append("Registered address is required")
    if not p.get("operating_countries"): warnings.append("Operating countries have not been provided")
    if not sub.get("tax_registrations"): warnings.append("No tax registration details have been added")
    if not sub.get("bank_accounts"): blockers.append("At least one bank account is required")
    if sub.get("bank_accounts") and sum(bool(b.get("is_primary")) for b in sub["bank_accounts"]) != 1: blockers.append("Exactly one bank account must be primary")
    from vendor_core.applicability import load_config, VendorContext, resolve_slots
    cfg=load_config(); slots=resolve_slots(cfg,VendorContext.from_submission(sub,cfg.policy),sub)
    present={d.get("slot_id") for d in sub.get("documents",[])}
    for slot in slots:
        if slot.requirement=="REQUIRED" and slot.slot_id not in present: blockers.append(f"Required document missing: {slot.label}")
    return {"ready":not blockers,"blockers":blockers,"warnings":warnings}

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

# Demo-only internal endpoints. Header-based roles are for a local presentation, never production auth.
ROLE_LEVEL={"procurement":1,"compliance":2,"admin":3}
def role_level(x_demo_role):
    if x_demo_role not in ROLE_LEVEL: raise HTTPException(403,"Set X-Demo-Role to procurement, compliance or admin. Demo-only; not real authentication.")
    return ROLE_LEVEL[x_demo_role]

@app.get("/api/internal/applications")
def internal_list(x_demo_role: str=Header(default="")):
    role_level(x_demo_role)
    with connect() as db: rows=db.execute("SELECT application_ref,state,decision_status,version,created_at,updated_at FROM applications ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]

@app.get("/api/internal/applications/{application_ref}")
def internal_detail(application_ref: str,x_demo_role: str=Header(default="")):
    level=role_level(x_demo_role)
    with connect() as db:
        row=db.execute("SELECT * FROM applications WHERE application_ref=?",(application_ref,)).fetchone()
        if not row: raise HTTPException(404,"Application not found")
        ev=db.execute("SELECT result_json FROM evaluations WHERE application_ref=? ORDER BY version DESC LIMIT 1",(application_ref,)).fetchone()
        sub=fetch_submission(db,application_ref)
    if not ev: return {"application":dict(row),"submission":mask_submission(sub),"evaluation":None}
    result=json.loads(ev["result_json"])
    if level==1:
        # Procurement sees operational progress, never reviewer-only findings, risk notes or raw engine events.
        result = {k: result.get(k) for k in ("application_ref", "version", "context", "applicability", "slots", "document_statuses", "vendor_message")}
        for document in sub.get("documents", []):
            document.pop("extraction", None)
            document.pop("malware_scan", None)
    return {"application":dict(row),"submission":mask_submission(sub),"evaluation":result}

def mask_submission(sub):
    sub=json.loads(json.dumps(sub))
    for group,key in [("tax_registrations","value"),("bank_accounts","account_number")]:
        for item in sub.get(group,[]):
            if item.get(key): item[key]="••••"+str(item[key])[-4:]
    return sub

@app.get("/api/internal/applications/{application_ref}/runs/{version}/events")
def internal_events(application_ref: str,version: int,x_demo_role: str=Header(default="")):
    level=role_level(x_demo_role)
    with connect() as db: rows=db.execute("SELECT event_json FROM events WHERE application_ref=? AND version=? ORDER BY seq",(application_ref,version)).fetchall()
    events=[json.loads(r[0]) for r in rows]
    if level==1:
        # Do not expose risk-stage events or hidden finding messages to procurement.
        events=[e for e in events if e.get("stage") != "RISK" and e.get("type") not in ("reviewer_action",)]
        for event in events:
            if isinstance(event.get("findings"),list):
                event["findings"]=[f for f in event["findings"] if f.get("vendor_visible") is True]
    return events

@app.get("/api/internal/applications/{application_ref}/audit")
def internal_audit(application_ref: str,x_demo_role: str=Header(default="")):
    role_level(x_demo_role)
    with connect() as db:
        if not db.execute("SELECT 1 FROM applications WHERE application_ref=?",(application_ref,)).fetchone(): raise HTTPException(404,"Application not found")
    return {"application_ref":application_ref,"events":[],"note":"Audit actions are added in the reviewer-actions milestone."}
