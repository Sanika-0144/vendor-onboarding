"""Private document OCR and conservative field extraction.

OCR is performed locally with Tesseract. Optional AI extraction uses an
OpenAI-compatible chat-completions endpoint only when explicitly configured.
Raw OCR text is never returned to vendor-facing API responses.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def _ocr_pdf(path: Path) -> str:
    import fitz
    import pytesseract
    from PIL import Image

    chunks: list[str] = []
    with fitz.open(path) as pdf:
        for page in pdf:
            native_text = page.get_text("text").strip()
            if len(native_text) >= 40:
                chunks.append(native_text)
                continue
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            chunks.append(pytesseract.image_to_string(image, config="--psm 6"))
    return "\n".join(chunks).strip()


def _ocr_image(path: Path) -> str:
    import pytesseract
    from PIL import Image, ImageOps

    image = Image.open(path).convert("RGB")
    image = ImageOps.grayscale(image)
    return pytesseract.image_to_string(image, config="--psm 6").strip()


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _ocr_pdf(path)
    if suffix in {".jpg", ".jpeg", ".png"}:
        return _ocr_image(path)
    raise ValueError("Unsupported document format")


def rule_based_fields(text: str) -> dict[str, Any]:
    """Conservative candidate extraction; values must be verified by a human."""
    patterns = {
        "pan": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        "gstin": r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b",
        "cin": r"\b[A-Z]{1,3}[0-9]{2,6}[A-Z]{2,4}[0-9]{3,8}\b",
        "ifsc": r"\b[A-Z]{4}0[A-Z0-9]{6}\b",
    }
    found: dict[str, Any] = {}
    upper = text.upper()
    for field, pattern in patterns.items():
        matches = list(dict.fromkeys(re.findall(pattern, upper)))
        if matches:
            found[field] = matches[:5]
    # Names may appear inline ("NAME: FAKUDA") or on the line after a
    # label (common in scanned forms and table-based PDFs). Keep legal names
    # separate from bank account-holder names.
    lines = [line.strip() for line in upper.splitlines() if line.strip()]
    label_patterns = (
        (re.compile(r"^(?:LEGAL\s+)?NAME(?:\s*\([^)]*\))?\s*[:\-]?\s*(.*)$"), "legal_name"),
        (re.compile(r"^(?:ACCOUNT\s*HOLDER|A/C\s*NAME)(?:\s*\([^)]*\))?\s*[:\-]?\s*(.*)$"), "account_holder_name"),
    )
    for index, line in enumerate(lines):
        for label_pattern, field_name in label_patterns:
            match = label_pattern.match(line)
            if not match:
                continue
            candidate = match.group(1).strip(" .:-")
            if not candidate and index + 1 < len(lines):
                next_line = lines[index + 1]
                # Do not treat another field label or a section heading as a name.
                if not re.match(
                    r"^(?:PAN|GSTIN|CIN|IFSC|DOCUMENT|NAME|ACCOUNT\s*HOLDER|A/C\s*NAME)\b",
                    next_line,
                ):
                    candidate = next_line.strip(" .:-")
            if candidate and re.fullmatch(r"[A-Z][A-Z .&'-]{1,69}", candidate):
                found[field_name] = candidate
            break
    return found


async def _ai_fields(text: str) -> dict[str, Any] | None:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_API_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("LLM_MODEL", "").strip()
    if not (api_key and base_url and model):
        return None

    import httpx

    prompt = (
        "Extract only clearly visible vendor identity and bank fields from this OCR text. "
        "Return one JSON object with possible keys legal_name, pan, gstin, cin, ifsc, "
        "account_holder_name. Use null for absent or ambiguous values. Do not infer or "
        "correct characters. Include no prose. OCR TEXT:\n" + text[:16000]
    )
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "You extract fields from supplied OCR text. Never invent missing values."},
                    {"role": "user", "content": prompt},
                ],
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return {k: v for k, v in parsed.items() if v not in (None, "", [])}


async def analyse_document(path: Path) -> dict[str, Any]:
    text = extract_text(path)
    if len(text.strip()) < 8:
        return {
            "status": "NEEDS_REVIEW",
            "extraction_method": "tesseract_ocr",
            "extracted_fields": {},
            "warnings": ["No readable text was detected. Upload a clearer scan or PDF."],
            "text_length": len(text),
        }

    fields = rule_based_fields(text)
    method = "ocr_and_rules"
    warnings = ["Extracted values are candidates only; verify them against the original document."]
    try:
        ai = await _ai_fields(text)
        if ai:
            fields = {**fields, **ai}
            method = "ocr_and_ai"
    except Exception:
        warnings.append("AI extraction was unavailable; OCR and conservative pattern extraction were used.")

    return {
        "status": "EXTRACTED" if fields else "NEEDS_REVIEW",
        "extraction_method": method,
        "extracted_fields": fields,
        "warnings": warnings,
        "text_length": len(text),
        "ocr_text": text[:30000],
    }
