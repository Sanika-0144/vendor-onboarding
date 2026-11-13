"""Local-first account authentication for VendorFlow.
Tokens are HMAC signed and short lived. Use HTTPS and a strong secret in deployment.
"""
import base64, hashlib, hmac, json, os, secrets, time, uuid
from fastapi import HTTPException, Request
from .database import connect

SECRET = os.getenv("VENDORFLOW_AUTH_SECRET", "")
if not SECRET:
    # Local development only. Persist a random secret outside source control.
    from pathlib import Path
    keyfile = Path(__file__).resolve().parents[1] / ".auth_secret"
    if keyfile.exists(): SECRET = keyfile.read_text().strip()
    else:
        SECRET = secrets.token_urlsafe(48); keyfile.write_text(SECRET)
        try: keyfile.chmod(0o600)
        except OSError: pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def hash_password(password: str) -> str:
    if len(password) < 10: raise HTTPException(422, "Password must be at least 10 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310000)
    return f"pbkdf2_sha256$310000${_b64(salt)}${_b64(digest)}"

def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.urlsafe_b64decode(salt+"=="), int(rounds))
        return hmac.compare_digest(_b64(actual), digest)
    except Exception: return False

def issue_token(user: dict) -> str:
    payload = _b64(json.dumps({"sub":user["id"],"role":user["role"],"exp":int(time.time())+8*60*60},separators=(",",":")).encode())
    sig = _b64(hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return payload+"."+sig

def read_token(token: str):
    try:
        payload, sig = token.split(".",1)
        expected = _b64(hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected): return None
        data=json.loads(base64.urlsafe_b64decode(payload+"=="))
        if data["exp"] < time.time(): return None
        with connect() as db: row=db.execute("SELECT id,email,full_name,role,active FROM users WHERE id=?",(data["sub"],)).fetchone()
        if not row or not row["active"]: return None
        return dict(row)
    except Exception: return None

def current_user(request: Request):
    auth=request.headers.get("authorization","")
    if not auth.lower().startswith("bearer "): raise HTTPException(401,"Authentication required")
    user=read_token(auth.split(" ",1)[1])
    if not user: raise HTTPException(401,"Session expired or invalid. Please log in again.")
    return user

def create_user(email, full_name, password, role="vendor"):
    email=email.strip().lower()
    if "@" not in email or len(email)>254: raise HTTPException(422,"Enter a valid email address")
    if not full_name.strip(): raise HTTPException(422,"Full name is required")
    if role not in ("vendor","reviewer","admin"): raise HTTPException(422,"Invalid role")
    user={"id":"USR-"+uuid.uuid4().hex[:12].upper(),"email":email,"full_name":full_name.strip(),"role":role}
    try:
        with connect() as db:
            db.execute("INSERT INTO users(id,email,full_name,password_hash,role,created_at) VALUES(?,?,?,?,?,datetime('now'))",(user["id"],email,user["full_name"],hash_password(password),role))
    except Exception as e:
        if "UNIQUE" in str(e): raise HTTPException(409,"An account with this email already exists")
        raise
    return user
