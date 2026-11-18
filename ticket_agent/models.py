from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=1200)
    category: Literal["access", "billing", "technical", "security", "other"]
    priority: Literal["low", "normal", "high", "urgent"]
    sentiment: Literal["positive", "neutral", "negative"]
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(min_length=1, max_length=5)
    suggested_steps: list[str] = Field(max_length=8)
    kb_ids: list[str] = Field(max_length=5)
    draft_reply: str = Field(min_length=1, max_length=3000)
    needs_human: bool
    reason: str = Field(min_length=1, max_length=1000)
