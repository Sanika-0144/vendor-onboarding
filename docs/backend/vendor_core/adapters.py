"""Adapter contracts. NO live provider is connected: every implementation here is synthetic or a stub.

Anything returning synthetic=True must be labelled as such in the UI.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .applicability import CONFIG_DIR
from .names import compare_names


@dataclass
class ScreeningResponse:
    status: str                      # "OK" | "UNAVAILABLE"
    matches: list[dict[str, Any]] = field(default_factory=list)
    synthetic: bool = True
    provider: str = "synthetic-demo"


class SanctionsAdapter(Protocol):
    def screen(self, names: list[str]) -> ScreeningResponse: ...


class SyntheticSanctionsAdapter:
    """Demo-only. Matches against configs/sanctions_synthetic.json using conservative name comparison."""

    def __init__(self, path: Path | None = None):
        data = json.loads((path or CONFIG_DIR / "sanctions_synthetic.json").read_text())
        self.entries = data["entries"]

    def screen(self, names: list[str]) -> ScreeningResponse:
        matches = []
        for n in filter(None, names):
            for e in self.entries:
                for cand in [e["name"], *e.get("aliases", [])]:
                    m = compare_names(n, cand)
                    if m.tier in ("EXACT", "COSMETIC", "FORM_MISSING", "ABBREVIATED", "AMBIGUOUS"):
                        matches.append({"screened_name": n, "list_entry": e["name"], "score": round(m.score, 1), "tier": m.tier})
        return ScreeningResponse("OK", matches)


class UnavailableSanctionsAdapter:
    """Simulates a provider outage. The engine must fail closed (PENDING), never approve."""

    def screen(self, names: list[str]) -> ScreeningResponse:
        return ScreeningResponse("UNAVAILABLE", [], synthetic=True, provider="unavailable")


class ExtractionAdapter(Protocol):
    """Contract for document classification + extraction (implement with an approved OCR / document-AI provider).

    Return shape per document (validated by code; model output is UNTRUSTED):
      {"detected_type": "PAN_CARD",
       "status": "OK" | "FAILED",
       "fields": {"name": {"value": "...", "confidence": 0.97, "page": 1}, ...},
       "issue_date": "YYYY-MM-DD" | None, "expiry_date": "YYYY-MM-DD" | None}
    Never infer absent values (return null). Do not send full TIN/SSN/EIN/bank numbers to an ordinary external LLM:
    redact or pre-mask before the call and return tin_last4 only.
    """

    def extract(self, file_path: str, expected_doc_type: str) -> dict[str, Any]: ...


class StubExtractionAdapter:
    def extract(self, file_path: str, expected_doc_type: str) -> dict[str, Any]:
        raise NotImplementedError("No OCR/document-AI provider is connected. Implement ExtractionAdapter.")
