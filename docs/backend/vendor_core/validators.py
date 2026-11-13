"""Syntax / checksum validators for IN, US, GB identifiers.

IMPORTANT: passing these checks does NOT prove an identifier was issued, is active, or belongs to the vendor.
GSTIN checksum is a secondary implementation: validate against authoritative test vectors before production.
"""
from __future__ import annotations

import re

_B36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def clean(value: str | None, allowed_separators: str = " -") -> str:
    """Upper-case and strip ONLY the explicitly allowed separators."""
    if value is None:
        return ""
    out = str(value).strip().upper()
    for ch in allowed_separators:
        out = out.replace(ch, "")
    return out


# ---------------------------------------------------------------- India
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
# 4th character of PAN = holder type
PAN_HOLDER = {"P": "individual", "C": "company", "F": "firm_llp", "H": "huf", "A": "aop",
              "B": "boi", "G": "government", "J": "artificial_person", "L": "local_authority", "T": "trust"}


def valid_pan(v: str) -> bool:
    return bool(PAN_RE.match(clean(v)))


def pan_holder_type(v: str) -> str | None:
    v = clean(v)
    return PAN_HOLDER.get(v[3]) if valid_pan(v) else None


CIN_RE = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
LLPIN_RE = re.compile(r"^[A-Z]{3}-?[0-9]{4}$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def valid_cin(v: str) -> bool:
    return bool(CIN_RE.match(clean(v, " ")))


def valid_llpin(v: str) -> bool:
    return bool(LLPIN_RE.match(clean(v, " ")))


def valid_ifsc(v: str) -> bool:
    return bool(IFSC_RE.match(clean(v)))


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        val = _B36.index(ch) * (1 if i % 2 == 0 else 2)
        total += val // 36 + val % 36
    return _B36[(36 - total % 36) % 36]


def valid_gstin(v: str) -> bool:
    v = clean(v)
    if not GSTIN_RE.match(v):
        return False
    state = int(v[:2])
    if not (1 <= state <= 38 or state in (97, 99)):
        return False
    return gstin_check_char(v[:14]) == v[14]


def make_gstin(pan: str, state_code: str = "27", entity_no: str = "1") -> str:
    """Build a syntactically valid GSTIN (demo/test data only)."""
    base = f"{state_code}{clean(pan)}{entity_no}Z"
    return base + gstin_check_char(base)


# ---------------------------------------------------------------- United States
def valid_aba(v: str) -> bool:
    v = clean(v, " -")
    if not re.fullmatch(r"\d{9}", v):
        return False
    d = [int(c) for c in v]
    return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0


def valid_ein_syntax(v: str) -> bool:
    return bool(re.fullmatch(r"\d{2}\d{7}", clean(v, " -")))  # syntax only; does not prove issuance


def valid_us_account(v: str) -> bool:
    return bool(re.fullmatch(r"\d{4,17}", clean(v, " -")))


# ---------------------------------------------------------------- United Kingdom
def valid_uk_company_number(v: str) -> bool:
    return bool(re.fullmatch(r"(\d{8}|[A-Z]{2}\d{6}|[A-Z]{2}\d{5}[A-Z])", clean(v, " ")))


def valid_utr(v: str) -> bool:
    return bool(re.fullmatch(r"\d{10}", clean(v, " ")))


def valid_gb_vat(v: str) -> bool:
    v = clean(v, " -")
    if v.startswith("GB"):
        v = v[2:]
    if not re.fullmatch(r"\d{9}(\d{3})?", v):
        return False
    if len(v) == 12:  # branch trader: check first 9
        v = v[:9]
    weights = [8, 7, 6, 5, 4, 3, 2]
    s = sum(int(d) * w for d, w in zip(v[:7], weights))
    check = int(v[7:9])
    return (s + check) % 97 == 0 or (s + check + 55) % 97 == 0


def valid_sort_code(v: str) -> bool:
    return bool(re.fullmatch(r"\d{6}", clean(v, " -")))


def valid_uk_account(v: str) -> bool:
    return bool(re.fullmatch(r"\d{8}", clean(v, " -")))  # conservative syntax only


# ---------------------------------------------------------------- International
IBAN_LEN = {"GB": 22, "DE": 22, "FR": 27, "IN": None, "US": None}


def valid_iban(v: str) -> bool:
    v = clean(v, " -")
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", v):
        return False
    cc = v[:2]
    if IBAN_LEN.get(cc) and len(v) != IBAN_LEN[cc]:
        return False
    rearranged = v[4:] + v[:4]
    num = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(num) % 97 == 1


def valid_bic(v: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?", clean(v)))
