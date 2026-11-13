"""Append-only JSONL audit log with hash chaining. Detects some edits; NOT tamper-proof (a full-file rewrite defeats it)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .security import mask_deep


class AuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def _last_hash(self) -> str:
        last = "GENESIS"
        with self.path.open() as fh:
            for line in fh:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    def append(self, event_type: str, actor: str, application_id: str, version: int, rule_version: str, payload: dict[str, Any]) -> dict:
        rec = {"ts": datetime.now(timezone.utc).isoformat(), "event_type": event_type, "actor": actor,
               "application_id": application_id, "version": version, "rule_version": rule_version,
               "payload": mask_deep(payload), "prev_hash": self._last_hash()}
        rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()
        with self.path.open("a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        return rec

    def read(self, application_id: str | None = None) -> list[dict]:
        rows = [json.loads(l) for l in self.path.read_text().splitlines() if l.strip()]
        return [r for r in rows if application_id in (None, r["application_id"])]

    def verify(self) -> bool:
        prev = "GENESIS"
        for r in self.read():
            h = r.pop("hash")
            if r["prev_hash"] != prev or hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode()).hexdigest() != h:
                return False
            prev = h
        return True
