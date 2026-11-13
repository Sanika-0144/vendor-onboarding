"""Masking, HMAC fingerprints and field encryption (dev/demo controls, not a production security certification)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

SENSITIVE_KEYS = {"account_number", "pan", "tin", "ssn", "ein", "gstin", "iban", "value", "routing_number",
                  "aba", "sort_code", "ifsc", "cin", "llpin", "utr", "vat", "company_number"}


def mask(value: Any, keep: int = 4) -> str:
    s = "" if value is None else str(value)
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


def mask_deep(obj: Any) -> Any:
    """Return a copy with values of sensitive keys masked (for logs/audit)."""
    if isinstance(obj, dict):
        return {k: (mask(v) if k.lower() in SENSITIVE_KEYS and isinstance(v, (str, int)) else mask_deep(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_deep(i) for i in obj]
    return obj


def hmac_fingerprint(value: Any, key: bytes) -> str:
    canon = json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    return hmac.new(key, canon, hashlib.sha256).hexdigest()


def get_secret_key() -> bytes:
    """Dev fallback only. Production: secrets manager. Never commit keys."""
    return os.environ.get("VENDOR_HMAC_KEY", "dev-only-insecure-key").encode()


def get_fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get("VENDOR_FERNET_KEY")
    if not key:
        raise RuntimeError("Set VENDOR_FERNET_KEY (generate with Fernet.generate_key()). Never commit it.")
    return Fernet(key.encode())


def encrypt_field(plain: str) -> str:
    return get_fernet().encrypt(plain.encode()).decode()


def decrypt_field(token: str) -> str:
    return get_fernet().decrypt(token.encode()).decode()
