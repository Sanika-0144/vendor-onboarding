from pydantic import BaseModel, Field
from typing import Any

class DraftCreate(BaseModel):
    submission: dict[str, Any] = Field(default_factory=dict)

class DraftUpdate(BaseModel):
    section: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

class Declaration(BaseModel):
    accepted: bool
    version: str = "v1"
    actor: str = "vendor"
