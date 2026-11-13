"""Conservative name normalisation + tiered comparison.

Rules: original strings are never overwritten; fuzzy similarity alone NEVER passes (it only routes to human review).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

ABBREV = {"pvt": "private", "ltd": "limited", "corp": "corporation", "inc": "incorporated",
          "co": "company", "mfg": "manufacturing", "intl": "international"}
TITLES = {"mr", "mrs", "ms", "dr", "shri", "smt", "sri"}

# canonical legal-form suffixes, longest first
FORMS = [
    (("private", "limited"), "PRIVATE_LIMITED"),
    (("public", "limited", "company"), "PUBLIC_LIMITED"),
    (("plc",), "PUBLIC_LIMITED"),
    (("limited", "liability", "partnership"), "LLP"),
    (("llp",), "LLP"),
    (("llc",), "LLC"),
    (("limited",), "LIMITED"),
    (("incorporated",), "INC"),
    (("corporation",), "CORP"),
]


def _tokens(name: str) -> list[str]:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower().replace("&", " and ")
    toks = re.sub(r"[^a-z0-9]+", " ", s).split()
    return [ABBREV.get(t, t) for t in toks]


def normalise(name: str) -> tuple[str, str | None]:
    """Return (core_name, legal_form). Legal form is recorded, not silently discarded."""
    toks = _tokens(name)
    for suffix, canon in FORMS:
        n = len(suffix)
        if len(toks) > n and tuple(toks[-n:]) == suffix:
            return " ".join(toks[:-n]), canon
    return " ".join(toks), None


@dataclass
class NameMatch:
    tier: str          # EXACT | COSMETIC | FORM_MISSING | ABBREVIATED | FORM_CONFLICT | AMBIGUOUS | MISMATCH
    score: float
    form_a: str | None
    form_b: str | None
    note: str


def _prefix_abbrev(short: list[str], long: list[str]) -> bool:
    return len(short) == len(long) and all(l.startswith(s) and (len(s) >= 2) for s, l in zip(short, long)) and short != long


def compare_names(a: str, b: str, *, order_insensitive: bool = False) -> NameMatch:
    if (a or "").strip() == (b or "").strip() and (a or "").strip():
        return NameMatch("EXACT", 100.0, None, None, "identical strings")
    core_a, form_a = normalise(a)
    core_b, form_b = normalise(b)
    if order_insensitive:
        core_a = " ".join(sorted(t for t in core_a.split() if t not in TITLES))
        core_b = " ".join(sorted(t for t in core_b.split() if t not in TITLES))
    if core_a and core_a == core_b:
        if form_a == form_b:
            return NameMatch("COSMETIC", 100.0, form_a, form_b, "differs only in punctuation, case or abbreviation of the legal suffix")
        if form_a is None or form_b is None:
            return NameMatch("FORM_MISSING", 95.0, form_a, form_b, "legal-entity suffix present on one side only")
        return NameMatch("FORM_CONFLICT", 90.0, form_a, form_b, f"legal form differs ({form_a} vs {form_b})")
    ta, tb = core_a.split(), core_b.split()
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if _prefix_abbrev(short, long_):
        if form_a and form_b and form_a != form_b:
            return NameMatch("FORM_CONFLICT", 88.0, form_a, form_b, f"legal form differs ({form_a} vs {form_b})")
        return NameMatch("ABBREVIATED", 90.0, form_a, form_b, "one name looks like an abbreviation of the other")
    score = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio() * 100
    if score >= 85:
        return NameMatch("AMBIGUOUS", score, form_a, form_b, "names are similar but not equivalent")
    return NameMatch("MISMATCH", score, form_a, form_b, "names do not match")
