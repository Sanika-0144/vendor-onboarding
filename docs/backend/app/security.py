"""Local-demo encryption helpers. Set VENDOR_FERNET_KEY in the environment for deployments."""
import os
import base64
import hashlib
from pathlib import Path
from cryptography.fernet import Fernet

BACKEND_DIR = Path(__file__).resolve().parents[1]
KEY_FILE = BACKEND_DIR / ".dev_fernet_key"

def get_fernet() -> Fernet:
    key = os.getenv("VENDOR_FERNET_KEY")
    if not key:
        if KEY_FILE.exists():
            key = KEY_FILE.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            KEY_FILE.write_text(key)
            try: KEY_FILE.chmod(0o600)
            except OSError: pass
        print("WARNING: using a local development Fernet key. Set VENDOR_FERNET_KEY for deployment; never commit the key.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError):
        # Render generateValue creates a strong random secret but not necessarily
        # Fernet's URL-safe base64 format. Derive a stable 32-byte Fernet key.
        derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
        return Fernet(derived)

SENSITIVE_KEYS = {"account_number", "iban", "value", "tin", "tax_id", "tax_identifier"}

def protect(value, fernet: Fernet):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS and item not in (None, ""):
                out[key] = "enc:" + fernet.encrypt(str(item).encode()).decode()
            else: out[key] = protect(item, fernet)
        return out
    if isinstance(value, list): return [protect(v, fernet) for v in value]
    return value

def reveal(value, fernet: Fernet):
    if isinstance(value, dict):
        return {k: (fernet.decrypt(v[4:].encode()).decode() if isinstance(v, str) and v.startswith("enc:") else reveal(v, fernet)) for k,v in value.items()}
    if isinstance(value, list): return [reveal(v, fernet) for v in value]
    return value
